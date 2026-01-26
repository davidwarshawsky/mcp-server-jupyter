import base64
import hashlib
import re
import json
import asyncio
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Any, Optional

# Global thread pool for CPU-bound tasks (JSON serialization, Pydantic validation)
# Size is configurable via Settings (pydantic-settings). Update via environment variable MCP_IO_POOL_SIZE.
from src.config import settings

import os

_io_pool_workers = int(
    os.getenv("MCP_IO_POOL_SIZE") or getattr(settings, "MCP_IO_POOL_SIZE", 4)
)
io_pool = ThreadPoolExecutor(max_workers=_io_pool_workers)

# Output truncation to prevent crashes from massive outputs
MAX_OUTPUT_LENGTH = 3000


def safe_unlink(path: Path, retries: int = 3) -> bool:
    """
    [DAY 2 OPT 2.2] Robust deletion that handles Windows file locking.
    Retries deletion with exponential backoff if PermissionError occurs.
    
    On Windows, if a file is open (e.g., VS Code is rendering an image),
    unlink() fails with PermissionError. This helper retries with backoff.
    
    Args:
        path: Path to file to delete
        retries: Number of retry attempts
        
    Returns:
        True if successfully deleted, False if locked/failed after retries
    """
    for i in range(retries):
        try:
            if path.exists():
                path.unlink()
            return True
        except PermissionError:
            if i < retries - 1:
                time.sleep(0.1 * (2 ** i))  # 0.1s, 0.2s, 0.4s exponential backoff
            else:
                logging.getLogger(__name__).warning(
                    f"[ASSET GC] Could not delete locked file {path.name} after {retries} attempts. Skipping."
                )
    return False


def check_asset_limits(asset_dir: Path, max_size_bytes: int = 1024 * 1024 * 1024):
    """
    [LAST MILE #2] Reactive asset pruning - prevent disk exhaustion.
    Stakeholder: QA & Edge Case Hunter

    Called after every asset write. If directory exceeds limit,
    immediately prune oldest files (LRU strategy).

    Args:
        asset_dir: Path to assets directory
        max_size_bytes: Maximum directory size (default: 1GB)
    """
    if not asset_dir.exists():
        return

    try:
        files = list(asset_dir.glob("*"))
        total_size = sum(f.stat().st_size for f in files if f.is_file())

        if total_size > max_size_bytes:
            # Target 80% of limit to avoid thrashing
            target_size = int(max_size_bytes * 0.8)

            # Sort by modification time (oldest first)
            # [BUG FIX] Filter out directories to prevent stat() errors
            files_sorted = sorted(
                [f for f in files if f.is_file()], key=lambda f: f.stat().st_mtime
            )

            for f in files_sorted:
                if total_size <= target_size:
                    break
                try:
                    sz = f.stat().st_size
                    # [DAY 2 OPT 2.2] Use safe_unlink instead of f.unlink() to handle Windows file locking
                    if safe_unlink(f):
                        total_size -= sz
                except Exception as e:
                    # Log but don't crash on other OS errors
                    logging.getLogger(__name__).warning(
                        f"[ASSET GC] Failed to process {f.name}: {e}"
                    )
    except Exception as e:
        # Don't let cleanup crash the main process, but log the issue
        logging.getLogger(__name__).error(f"[ASSET GC] Error during check: {e}")


def compress_traceback(traceback_lines: List[str]) -> List[str]:
    """
    [TOKENOMICS] Compress stack traces to save context window tokens.

    Removes frames from site-packages/dist-packages (library code)
    unless they are the immediate cause of the error.

    Problem: A pandas schema mismatch produces 60-line stack traces.
    This flushes 1,000+ tokens per error. After 3 retries, the agent
    has consumed 3,000 tokens on noise and "forgets" original instructions.

    Solution: Strip internal library frames, keep only:
    1. Traceback header
    2. User code frames
    3. Final error message

    Returns:
        Compressed traceback with library frames replaced by placeholder
    """
    if not traceback_lines:
        return []

    compressed = []
    # Always keep the header ("Traceback (most recent call last):")
    if traceback_lines:
        compressed.append(traceback_lines[0])

    # Filter intermediate frames
    user_frames = []
    inside_library_block = False
    skip_next_code_line = False

    for line in traceback_lines[1:]:
        stripped = line.strip()

        # Check if this is a "File ..." line
        is_file_line = stripped.startswith("File ")

        # Check if this is library code (based on the File path)
        is_lib = any(
            marker in line
            for marker in [
                "site-packages",
                "dist-packages",
                "lib/python",
                "<frozen",
                "importlib",
            ]
        )

        # Check if this is the final error message (no leading spaces, or is an exception type)
        # Error messages like "ValueError: ..." don't have "  " prefix OR they have exception format
        is_error_message = not line.startswith("  ") or (
            not is_file_line and not line.startswith("    ")
        )

        if is_file_line:
            # This is a "File ..." line
            if is_lib:
                # Library file - compress
                if not inside_library_block:
                    user_frames.append("  ... [Internal Library Frames] ...\n")
                    inside_library_block = True
                skip_next_code_line = True  # Skip the following code line too
            else:
                # User file - keep
                inside_library_block = False
                skip_next_code_line = False
                user_frames.append(line)
        elif skip_next_code_line and line.startswith("    "):
            # This is a code line following a library File line - skip it
            skip_next_code_line = False
        elif is_error_message:
            # Keep error messages
            inside_library_block = False
            skip_next_code_line = False
            user_frames.append(line)
        else:
            # User code line (follows a user File line)
            inside_library_block = False
            skip_next_code_line = False
            user_frames.append(line)

    compressed.extend(user_frames)
    return compressed


async def offload_json_dumps(data: Any) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(io_pool, lambda: json.dumps(data))


def _is_pydantic_model(obj: Any) -> bool:
    try:
        # Lazy import to avoid hard dependency
        from pydantic import BaseModel

        return isinstance(obj, BaseModel)
    except Exception:
        return False


def _as_serializable(obj: Any) -> Any:
    """Convert common objects to JSON-serializable structures."""
    try:
        # Dataclasses / pydantic models
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "__dict__") and not isinstance(obj, (str, bytes)):
            return obj.__dict__
        return obj
    except Exception:
        return str(obj)


def offload_to_thread(func):
    """
    Decorator for MCP tools that may return large payloads.

    Behavior:
    - If the wrapped function is synchronous, it will be executed in the shared io_pool.
    - If the wrapped function is async, it will be awaited normally and then
      any CPU-bound JSON serialization will be offloaded to the io_pool.
    - If the final result is a dict, dataclass, or pydantic model, it will be
      serialized to JSON inside the thread pool and returned as a list containing
      a single `mcp.types.TextContent(type="text", text=json_string)` object
      (which conforms to the MCP content list expected by clients).
    - If the result already appears to be a list of content objects, it is
      returned unchanged.
    """
    from functools import wraps
    import asyncio as _asyncio

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        loop = _asyncio.get_running_loop()

        # Execute the function (await if coroutine)
        if _asyncio.iscoroutinefunction(func):
            try:
                result = await func(*args, **kwargs)
            except Exception:
                # Propagate exception for upstream logging/handling
                raise
        else:
            # Run sync function in thread pool to avoid blocking event loop
            result = await loop.run_in_executor(io_pool, lambda: func(*args, **kwargs))

        # If the result already looks like content list, return as-is
        try:
            import mcp.types as _types

            if (
                isinstance(result, list)
                and len(result) > 0
                and isinstance(result[0], _types.TextContent)
            ):
                return result
        except Exception:
            pass

        # If result is already JSON string, wrap and return
        if isinstance(result, str):
            try:
                import mcp.types as _types

                return [_types.TextContent(type="text", text=result)]
            except Exception:
                return [{"type": "text", "text": result}]

        # For other types (dict, dataclass, pydantic), offload serialization
        def _serialize():
            try:
                serializable = _as_serializable(result)
                return json.dumps(serializable, default=str)
            except Exception:
                try:
                    return json.dumps(str(result))
                except Exception:
                    return '"<unserializable result>"'

        json_str = await loop.run_in_executor(io_pool, _serialize)

        try:
            import mcp.types as _types

            return [_types.TextContent(type="text", text=json_str)]
        except Exception:
            return [{"type": "text", "text": json_str}]

    return async_wrapper


async def offload_validation(model_class, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(io_pool, lambda: model_class(**kwargs))


def truncate_output(text: str, max_length: int = MAX_OUTPUT_LENGTH) -> str:
    """
    Truncate output to prevent crashes from massive outputs.
    Shows head and tail with truncation notice in the middle.

    Args:
        text: Output text to truncate
        max_length: Maximum characters to return (default: MAX_OUTPUT_LENGTH)

    Returns:
        Truncated text with notice, or original if under limit
    """
    if len(text) <= max_length:
        return text

    chars_removed = len(text) - max_length
    # Show first and last portions
    head_size = max_length // 2
    tail_size = max_length - head_size

    head = text[:head_size]
    tail = text[-tail_size:]

    truncation_msg = f"\n\n... [Truncated {chars_removed:,} characters] ...\n\n"
    return head + truncation_msg + tail


@dataclass
class ToolResult:
    """Standardized result format for all MCP tools."""

    success: bool
    data: Any
    error_msg: Optional[str] = None
    user_suggestion: Optional[str] = None

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self), indent=2)


def get_cell_hash(cell_source: str) -> str:
    """
    Calculate SHA-256 hash of cell content.
    [FIX] Normalize by stripping all whitespace so formatting-only changes
    (e.g., Black/Ruff) do not trigger perceived content drift.
    """
    import re

    # [FIX #4] Normalize by stripping all whitespace so formatting-only changes
    # (e.g., Black/Ruff) do not trigger perceived content drift.
    if cell_source is None:
        return ""
    normalized = re.sub(r"\s+", "", str(cell_source))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _convert_small_html_table_to_markdown(html: str) -> Optional[str]:
    """
    Convert small HTML tables to markdown for LLM consumption.

    Uses BeautifulSoup for robust parsing of pandas-generated HTML.
    Only processes tables with <= 10 rows and <= 10 columns to avoid context bloat.

    Returns:
        Markdown table string, or None if table is too large/parsing fails
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")
        if not table:
            return None

        # Extract all rows (both thead and tbody)
        rows = table.find_all("tr")
        if len(rows) > 10:  # Too many rows
            return None

        markdown_lines = []
        for i, row in enumerate(rows):
            # Get all cells (th or td)
            cells = row.find_all(["th", "td"])
            if len(cells) > 10:  # Too many columns
                return None

            # Clean cell text
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            markdown_lines.append("| " + " | ".join(cell_texts) + " |")

            # Add header separator after first row (if it looks like headers)
            if i == 0:
                markdown_lines.append("| " + " | ".join(["---"] * len(cells)) + " |")

        return "\n".join(markdown_lines)

    except Exception:
        # If BeautifulSoup isn't available or parsing fails, try a lightweight
        # regex-based parser for very small, well-formed tables (used in tests).
        try:
            rows = []
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
                cells = re.findall(r"<(?:th|td)[^>]*>(.*?)</(?:th|td)>", tr, flags=re.S | re.I)
                cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                rows.append(cells)

            if not rows or len(rows) > 10:
                return None

            markdown_lines = []
            for i, cells in enumerate(rows):
                if len(cells) > 10:
                    return None
                markdown_lines.append("| " + " | ".join(cells) + " |")
                if i == 0:
                    markdown_lines.append("| " + " | ".join(["---"] * len(cells)) + " |")

            return "\n".join(markdown_lines)
        except Exception:
            return None


def _render_plotly_chart(html_content: str, asset_dir: str) -> Optional[str]:
    """
    Renders a Plotly HTML chart to a static PNG image.

    Args:
        html_content: The HTML content of the Plotly chart.
        asset_dir: The directory to save the PNG file.

    Returns:
        The path to the saved PNG file, or None if rendering fails.
    """
    try:
        import plotly.io as pio
        from bs4 import BeautifulSoup
        import json

        # Find the script tag with the data
        soup = BeautifulSoup(html_content, "html.parser")
        script_tag = soup.find("script", {"type": "application/vnd.plotly.v1+json"})
        if not script_tag:
            return None

        chart_json = json.loads(script_tag.string)
        fig = pio.from_json(json.dumps(chart_json))

        # Save to a file
        content_hash = hashlib.sha256(html_content.encode()).hexdigest()[:16]
        asset_filename = f"plot_{content_hash}.png"
        asset_path = Path(asset_dir) / asset_filename

        pio.write_image(fig, str(asset_path), engine="kaleido")

        return str(asset_path)
    except Exception as e:
        # Log the error but don't crash
        import logging

        logging.getLogger(__name__).warning(
            f"Could not render Plotly chart to PNG: {e}"
        )
        return None


async def _sanitize_outputs_async(outputs: List[Any], asset_dir: str) -> str:
    """
    Internal async implementation of sanitize_outputs. Use the public wrapper `sanitize_outputs`
    which is backward-compatible with synchronous callers.
    """

    llm_summary = []
    raw_outputs = []

    Path(asset_dir).mkdir(parents=True, exist_ok=True)

    # Auto-gitignore assets/ to prevent pollution (Git-awareness)
    from src.asset_manager import ensure_assets_gitignored

    try:
        ensure_assets_gitignored(asset_dir)
    except Exception:
        pass

    # Configuration for text offloading ("Stubbing & Paging")
    MAX_INLINE_CHARS = 2000
    MAX_INLINE_LINES = 50

    # Asset priority: PDF > SVG > PNG > JPEG (higher number = higher priority)
    ASSET_PRIORITY = {
        "application/pdf": (4, "pdf", True),  # (priority, extension, is_binary)
        "image/svg+xml": (3, "svg", False),
        "image/png": (2, "png", True),
        "image/jpeg": (1, "jpeg", True),
    }

    # [SECRET REDACTION] Regex patterns (kept for backward compatibility)
    # Phase 3.3: Enhanced with entropy-based detection
    SECRET_PATTERNS = [
        r"sk-[a-zA-Z0-9]{20,}",  # OpenAI looking keys
        r"AKIA[0-9A-Z]{16}",  # AWS Access Key
        r"AIza[0-9A-Za-z-_]{35}",  # Google Cloud API Key
    ]

    def _redact_text(text: str) -> str:
        """
        Redact secrets using both regex patterns and entropy-based detection.

        Phase 3.3: Enhanced with Shannon entropy analysis to catch untagged secrets.
        Falls back to regex-only if entropy scanner fails.
        """
        # Step 1: Legacy regex-based redaction (fast path)
        for pattern in SECRET_PATTERNS:
            text = re.sub(pattern, "[REDACTED_SECRET]", text)

        # Step 2: Entropy-based detection (Phase 3.3)
        try:
            from .secret_scanner import redact_secrets

            text = redact_secrets(text, min_confidence=0.6)
        except Exception as e:
            # Fallback to regex-only if entropy scanner fails
            logger.warning(f"Entropy scanner failed, using regex-only: {e}")

        return text

    def _make_preview(text: str, max_lines: int) -> str:
        """Create a preview of text by showing first and last lines."""
        # First, truncate by chars if single line is huge
        MAX_PREVIEW_CHARS = 1000
        if len(text) > MAX_PREVIEW_CHARS * 2:  # heuristic: if crazy large
            half = MAX_PREVIEW_CHARS
            text = text[:half] + "\n... [long line truncated] ...\n" + text[-half:]

            return text

        lines = text.split("\n")
        preview_lines = max_lines // 2
        head = "\n".join(lines[:preview_lines])
        tail = "\n".join(lines[-preview_lines:])
        return f"{head}\n... [{len(lines) - max_lines} lines omitted] ...\n{tail}"

    def _offload_text_to_asset(
        raw_text: str, asset_dir: str, max_inline_chars: int, max_inline_lines: int
    ) -> tuple:
        """
        Offload large text to asset file and return (stub_text, asset_path, metadata).
        Returns (None, None, None) if text is small enough to keep inline.
        """
        if (
            len(raw_text) <= max_inline_chars
            and raw_text.count("\n") <= max_inline_lines
        ):
            return None, None, None

        # 1. Save to Asset
        # [SECURITY] Use SHA-256 for FIPS compliance (not MD5)
        content_hash = hashlib.sha256(raw_text.encode()).hexdigest()[:32]
        asset_filename = f"text_{content_hash}.txt"
        asset_path = Path(asset_dir) / asset_filename

        with open(asset_path, "w", encoding="utf-8") as f:
            f.write(raw_text)

        # Enforce storage quota/reactive pruning after asset write (best-effort)
        try:
            check_asset_limits(Path(asset_dir))
        except Exception:
            # Best-effort: do not fail the write if quota check fails
            pass

        # 2. Create Preview Stub
        preview = _make_preview(raw_text, max_inline_lines)
        line_count = raw_text.count("\n") + 1
        size_kb = len(raw_text) / 1024

        stub_msg = f"\n\n>>> FULL OUTPUT ({size_kb:.1f}KB, {line_count} lines) SAVED TO: {asset_filename} <<<"
        stub_text = preview + stub_msg

        # 3. Create Metadata
        metadata = {
            "mcp_asset": {
                "path": str(asset_path).replace("\\", "/"),
                "type": "text/plain",
                "size_bytes": len(raw_text),
                "line_count": line_count,
            }
        }

        return stub_text, asset_path, metadata

    for out in outputs:
        # Normalize to dict
        if hasattr(out, "to_dict"):
            out_dict = out.to_dict()
        elif isinstance(out, dict):
            out_dict = out
        else:
            # Fallback for objects that behave like dicts but might not be
            out_dict = out.__dict__ if hasattr(out, "__dict__") else {}

        output_type = out_dict.get("output_type", "")
        data = out_dict.get("data", {})
        metadata = out_dict.get("metadata", {})

        # --- 1. Build Raw Outputs for VS Code (Rich Visualization) ---
        # We need to map NBFormat types to what VS Code expects
        # NotebookOutput in TS expects { output_type, data, metadata, text, ... }
        clean_raw = {"output_type": output_type, "metadata": metadata}

        if output_type == "stream":
            clean_raw["name"] = out_dict.get("name", "stdout")
            clean_raw["text"] = out_dict.get("text", "")
        elif output_type == "error":
            clean_raw["ename"] = out_dict.get("ename", "")
            clean_raw["evalue"] = out_dict.get("evalue", "")
            clean_raw["traceback"] = out_dict.get("traceback", [])
        elif output_type in ["execute_result", "display_data"]:
            clean_raw["data"] = data
            clean_raw["execution_count"] = out_dict.get("execution_count")

        raw_outputs.append(clean_raw)

        # --- 2. Build LLM Summary (Text Only + Asset Paths) ---

        # Handle Binary Assets (Images, PDFs) with Priority
        if output_type in ["display_data", "execute_result"]:
            # Find highest priority asset in this output
            best_asset = None
            best_priority = -1

            for mime_type, (priority, ext, is_binary) in ASSET_PRIORITY.items():
                if mime_type in data and priority > best_priority:
                    best_asset = (mime_type, ext, is_binary, data[mime_type])
                    best_priority = priority

            # Save the best asset found
            if best_asset:
                mime_type, ext, is_binary, content = best_asset
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"[ASSET DEBUG] Detected asset: mime={mime_type}, ext={ext}, is_binary={is_binary}, content_len={len(content) if hasattr(content, '__len__') else 'N/A'}")
                try:
                    if is_binary:
                        # Decode base64 binary data
                        asset_bytes = base64.b64decode(content)
                        logger.info(f"[ASSET DEBUG] Decoded asset bytes: {len(asset_bytes)} bytes")
                        fname = (
                            f"asset_{hashlib.md5(asset_bytes).hexdigest()[:12]}.{ext}"
                        )
                        save_path = Path(asset_dir) / fname
                        with open(save_path, "wb") as f:
                            f.write(asset_bytes)
                        logger.info(f"[ASSET DEBUG] Saved asset to {save_path}")
                    else:
                        # SVG is text-based
                        content_bytes = (
                            content.encode("utf-8")
                            if isinstance(content, str)
                            else content
                        )
                        fname = (
                            f"asset_{hashlib.md5(content_bytes).hexdigest()[:12]}.{ext}"
                        )
                        save_path = Path(asset_dir) / fname
                        with open(save_path, "w", encoding="utf-8") as f:
                            f.write(
                                content
                                if isinstance(content, str)
                                else content.decode("utf-8")
                            )

                    # Enforce storage quota/reactive pruning after saving binary asset
                    try:
                        from pathlib import Path as _P

                        check_asset_limits(_P(asset_dir))
                    except Exception:
                        # Best-effort: don't fail the save if pruning fails
                        pass

                    # [PHASE 3.1] Inline Asset Rendering
                    # The VS Code extension will have a renderer for this type.
                    # Embed base64 data directly for robust rendering in sandboxed webviews.
                    data["application/vnd.mcp.asset+json"] = {
                        "path": str(
                            save_path
                        ),  # Keep path for reference, but don't use for rendering
                        "type": mime_type,
                        "content": content,  # The original base64 content
                        "alt": f"{ext.upper()} plot",
                    }
                    # Remove the original large binary data to save space
                    if mime_type in data:
                        del data[mime_type]

                    # Add a specific message for matplotlib
                    is_matplotlib = "matplotlib" in str(metadata).lower()
                    if is_matplotlib and ext == "png":
                        llm_summary.append(
                            f"[Matplotlib plot saved to: {save_path.name}]"
                        )
                    else:
                        llm_summary.append(
                            f"[{ext.upper()} ASSET SAVED TO: {save_path.name}]"
                        )
                except Exception as e:
                    llm_summary.append(f"[Error saving {ext.upper()}: {str(e)}]")

        # Handle Text (execute_result) with Asset Offloading
        if "text/plain" in data:
            text = data["text/plain"]
            # [SECRET REDACTION]
            text = _redact_text(text)

            # Check if text should be offloaded (before truncation!)
            stub_text, asset_path, asset_metadata = _offload_text_to_asset(
                text, asset_dir, MAX_INLINE_CHARS, MAX_INLINE_LINES
            )

            if stub_text:
                # Text was offloaded - use stub text (already has preview)
                data["text/plain"] = stub_text

                # Ensure metadata exists in out_dict
                if "metadata" not in out_dict:
                    out_dict["metadata"] = {}
                out_dict["metadata"].update(asset_metadata)

                clean_raw["metadata"].update(asset_metadata)
                llm_summary.append(stub_text)
            else:
                # Text NOT offloaded - apply truncation for inline display
                text = truncate_output(text)
                # Text is small enough to keep inline
                llm_summary.append(text)

        # Handle HTML (often pandas DataFrames)
        if "text/html" in data:
            html = data["text/html"]
            # [SECRET REDACTION] (Less likely in HTML but good hygiene)
            html = _redact_text(html)

            # Check for Plotly/Bokeh interactive charts
            is_plotly = "plotly" in html.lower() or "plotly.js" in html.lower()
            is_bokeh = "bokeh" in html.lower() or "bkroot" in html.lower()

            if is_plotly:
                # Attempt to render Plotly chart to static PNG
                # Save interactive HTML for the client to render while also creating a PNG for the agent
                try:
                    # Keep the interactive HTML for dual-stream rendering
                    data["application/vnd.mcp.interactive+html"] = html
                except Exception:
                    pass

                png_path = _render_plotly_chart(html, asset_dir)
                if png_path:
                    llm_summary.append(f"[PLOT RENDERED TO: {Path(png_path).name}]")
                else:
                    llm_summary.append(
                        "[Plotly Chart - Interactive View available in VS Code]"
                    )
            elif is_bokeh:
                # Chart detected
                chart_type = "Bokeh"
                llm_summary.append(
                    f"[{chart_type} Chart - Interactive View available in VS Code]"
                )
            elif "<table" in html.lower():
                # IMPROVEMENT: Show small tables inline, hide large ones
                # Limits: 10 rows × 10 columns to prevent context bloat
                if len(html) < 3000:  # Small HTML, worth trying to convert
                    markdown_table = _convert_small_html_table_to_markdown(html)
                    if markdown_table:
                        llm_summary.append("[Data Preview]:\n" + markdown_table)
                    else:
                        # Table too large or parsing failed
                        llm_summary.append(
                            "[HTML Table detected - Use inspect_variable() to view DataFrame]"
                        )
                else:
                    # Large HTML table
                    llm_summary.append(
                        "[Large HTML Table detected - Use inspect_variable() to view DataFrame]"
                    )
            else:
                # Non-table, non-chart HTML: strip tags and truncate
                clean_text = re.sub("<[^<]+?>", " ", html)
                clean_text = re.sub(r"\s+", " ", clean_text).strip()
                if len(clean_text) > 1500:
                    clean_text = clean_text[:750] + "... [TRUNCATED]"
                llm_summary.append(f"[HTML Content]: {clean_text}")

        # Handle Stream Text (stdout/stderr) with Asset Offloading
        if output_type == "stream":
            text = out_dict.get("text", "")
            # Strip ANSI escape codes
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            text = ansi_escape.sub("", text)

            # [TQDM SUPPORT] Detect progress bars and format nicely
            # Matches: 10%|###   | 10/100 or similar
            if "\r" in text or "it/s" in text:
                # Capture the last progress line if multiple updates
                lines = text.split("\r")
                if len(lines) > 1:
                    # Filter for tqdm-like lines (contain % or it/s)
                    progress_lines = [l for l in lines if "%" in l or "it/s" in l]
                    if progress_lines:
                        # Use the last meaningful progress update
                        latest = progress_lines[-1].strip()
                        if latest:
                            text = f"[Progress]: {latest}"

            # [SECRET REDACTION]
            text = _redact_text(text)

            # Check if text should be offloaded (before truncation!)
            stub_text, asset_path, asset_metadata = _offload_text_to_asset(
                text, asset_dir, MAX_INLINE_CHARS, MAX_INLINE_LINES
            )

            if stub_text:
                # Text was offloaded - use stub text (already has preview)
                out_dict["text"] = stub_text
                if "metadata" not in out_dict:
                    out_dict["metadata"] = {}
                out_dict["metadata"].update(asset_metadata)
                clean_raw["text"] = stub_text
                clean_raw["metadata"].update(asset_metadata)
                llm_summary.append(stub_text)
            else:
                # Text NOT offloaded - apply truncation for inline display
                text = truncate_output(text)
                # Text is small enough to keep inline
                llm_summary.append(text)

        # Handle Errors
        if output_type == "error":
            ename = out_dict.get("ename", "")
            evalue = out_dict.get("evalue", "")
            traceback = out_dict.get("traceback", [])

            # [TOKENOMICS] 1. Compress traceback FIRST (removes library noise)
            clean_traceback = compress_traceback(traceback)

            # 2. Strip ANSI escape codes
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            clean_traceback = [ansi_escape.sub("", line) for line in clean_traceback]

            # 3. Redact secrets
            clean_traceback = [_redact_text(line) for line in clean_traceback]

            # Build clean error message
            error_msg = f"Error: {ename}: {evalue}"
            if clean_traceback:
                # After compression, limit to last 20 lines (already compressed)
                error_msg += "\n" + "\n".join(clean_traceback[-20:])
            llm_summary.append(error_msg)

    # Return structured data for both LLM (summary) and VS Code (rich output)
    result = {"llm_summary": "\n".join(llm_summary), "raw_outputs": raw_outputs}

    # [LAST MILE #2] Reactive asset pruning after writing
    check_asset_limits(Path(asset_dir))

    # Offload JSON serialization to prevent blocking the event loop for large payloads
    return await offload_json_dumps(result)


def sanitize_outputs(outputs: List[Any], asset_dir: str) -> str:
    """Sync compatibility wrapper for `_sanitize_outputs_async`.

    If called from a normal synchronous context, executes the async implementation and
    returns the JSON result. If called when an event loop is present, this wrapper runs
    the async implementation in a background thread and returns the result to the caller
    to preserve synchronous calling semantics.
    """
    try:
        asyncio.get_running_loop()
        # Running loop exists — run async implementation in separate thread
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(asyncio.run, _sanitize_outputs_async(outputs, asset_dir))
            return fut.result()
    except RuntimeError:
        # No running loop — safe to run in-process
        return asyncio.run(_sanitize_outputs_async(outputs, asset_dir))


def get_project_root(start_path: Path) -> Path:
    """
    Finds the project root by looking for common markers (.git, pyproject.toml).
    Walks up from start_path.

    SECURITY: Never returns system root or paths outside user's home directory.
    """
    current = start_path.resolve()

    try:
        from src.config import load_and_validate_settings

        settings = load_and_validate_settings()
        home = (
            settings.get_data_dir().parent.resolve()
            if settings.MCP_DATA_DIR
            else Path.home().resolve()
        )
    except Exception:
        home = Path.home().resolve()

    for _ in range(10):  # Limit traversing depth
        # [SECURITY] Stop if we've escaped $HOME (prevents mounting system dirs)
        if not current.is_relative_to(home):
            import logging

            logging.getLogger(__name__).warning(
                f"[SECURITY] Project root search escaped HOME directory at {current}. "
                f"Falling back to start_path."
            )
            return start_path

        if (
            (current / ".git").exists()
            or (current / "pyproject.toml").exists()
            or (current / "requirements.txt").exists()
            or (current / ".devcontainer").exists()
            or (current / ".env").exists()
        ):
            return current

        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent

    # Fallback to start path if no root marker found
    return start_path


# Public helper to offload large text to assets (exposed for testing and tools)
def offload_text_to_asset(raw_text: str, asset_dir: str, max_inline_chars: int, max_inline_lines: int):
    """Public wrapper for text offloading logic used by sanitize_outputs.

    Returns (stub_text, asset_path, metadata) or (None, None, None) if not offloaded.
    """
    # Reuse the same logic as the internal helper defined in _sanitize_outputs_async
    if (
        len(raw_text) <= max_inline_chars
        and raw_text.count("\n") <= max_inline_lines
    ):
        return None, None, None

    content_hash = hashlib.sha256(raw_text.encode()).hexdigest()[:32]
    asset_filename = f"text_{content_hash}.txt"
    asset_path = Path(asset_dir) / asset_filename

    with open(asset_path, "w", encoding="utf-8") as f:
        f.write(raw_text)

    # Enforce storage quota/reactive pruning after asset write
    try:
        check_asset_limits(Path(asset_dir))
    except Exception:
        pass

    # Create a preview (first/last lines heuristic)
    MAX_PREVIEW_CHARS = 1000
    text_for_preview = raw_text
    if len(raw_text) > MAX_PREVIEW_CHARS * 2:
        half = MAX_PREVIEW_CHARS
        text_for_preview = raw_text[:half] + "\n... [long line truncated] ...\n" + raw_text[-half:]

    lines = text_for_preview.split("\n")
    preview_lines = max_inline_lines // 2
    head = "\n".join(lines[:preview_lines])
    tail = "\n".join(lines[-preview_lines:])
    preview = f"{head}\n... [{len(lines) - max_inline_lines} lines omitted] ...\n{tail}"

    line_count = raw_text.count("\n") + 1
    size_kb = len(raw_text) / 1024

    stub_msg = f"\n\n>>> FULL OUTPUT ({size_kb:.1f}KB, {line_count} lines) SAVED TO: {asset_filename} <<<"
    stub_text = preview + stub_msg

    metadata = {
        "mcp_asset": {
            "path": str(asset_path).replace("\\", "/"),
            "type": "text/plain",
            "size_bytes": len(raw_text),
            "line_count": line_count,
        }
    }

    return stub_text, asset_path, metadata