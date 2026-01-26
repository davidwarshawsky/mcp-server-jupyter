"""
Asset management tools for MCP Jupyter Server.

Provides tools for reading, analyzing, and cleaning up asset files
(offloaded outputs like large text files and binary assets like images).
"""

import json
import base64
from typing import List, Optional
from pathlib import Path
import mcp.types as types


def read_asset(asset_path: str, lines: Optional[List[int]] = None, search: Optional[str] = None, max_lines: int = 1000) -> str:
    """Module-level read_asset helper for tests and programmatic use.

    This mirrors the implementation registered as an MCP tool and is safe to call
    directly from code/tests that do not have an MCP runtime available.
    """
    # [DAY 3 OPT 3.3] Enforce HARD CAPS on return payload size
    MAX_RETURN_CHARS = 100_000  # 100KB hard limit
    MAX_RETURN_LINES = 500

    max_lines = min(max_lines, MAX_RETURN_LINES)

    resolved_path = str(Path(asset_path).resolve())
    if ".." in resolved_path or not resolved_path.endswith(".txt"):
        return json.dumps({"error": "Invalid asset path. Must be a .txt file without path traversal."})

    if not Path(asset_path).exists():
        return json.dumps({"error": f"Asset file not found: {asset_path}"})

    try:
        file_size = Path(asset_path).stat().st_size
        with open(asset_path, "r", encoding="utf-8", errors="replace") as f:
            if search:
                matches = []
                for i, line in enumerate(f, 1):
                    if search.lower() in line.lower():
                        matches.append(f"{i}: {line.rstrip()}")
                        if len(matches) >= max_lines:
                            matches.append(f"\n... [Search limit reached: {max_lines} matches shown] ...")
                            break

                if not matches:
                    return json.dumps({"content": f"No matches found for '{search}'", "file_size_bytes": file_size, "matches": 0})

                content = "\n".join(matches)
                # [DAY 3 OPT 3.3] Apply hard cap BEFORE returning
                if len(content) > MAX_RETURN_CHARS:
                    content = content[:MAX_RETURN_CHARS]
                    content += f"\n\n[SYSTEM] Output truncated. Exceeded {MAX_RETURN_CHARS//1024}KB limit."
                    content += f"\n[SYSTEM] Refine your search query to get more specific results."
                
                return json.dumps({"content": content, "file_size_bytes": file_size, "matches": len(matches)})

            elif lines:
                if len(lines) != 2 or lines[0] < 1 or lines[1] < lines[0]:
                    return json.dumps({"error": "Invalid line range. Use [start_line, end_line] where start >= 1 and end >= start."})

                start_line, end_line = lines
                end_line = min(end_line, start_line + max_lines - 1)

                selected_lines = []
                last_line = 0
                for i, line in enumerate(f, 1):
                    last_line = i
                    if i >= start_line:
                        selected_lines.append(line.rstrip())
                    if i >= end_line:
                        break

                content = "\n".join(selected_lines)
                # [DAY 3 OPT 3.3] Apply hard cap BEFORE returning
                if len(content) > MAX_RETURN_CHARS:
                    content = content[:MAX_RETURN_CHARS]
                    content += f"\n\n[SYSTEM] Output truncated. Exceeded {MAX_RETURN_CHARS//1024}KB limit."
                    content += f"\n[SYSTEM] Use 'lines' parameter to paginate (e.g., lines=[1000, 1100])."

                return json.dumps({"content": content, "file_size_bytes": file_size, "line_range": [start_line, min(end_line, last_line)], "lines_returned": len(selected_lines)})

            else:
                content_lines = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        content_lines.append(f"\n... [Content truncated at {max_lines} lines. Use 'lines' parameter for pagination] ...")
                        break
                    content_lines.append(line.rstrip())

                content = "\n".join(content_lines)
                # [DAY 3 OPT 3.3] Apply hard cap BEFORE returning
                if len(content) > MAX_RETURN_CHARS:
                    content = content[:MAX_RETURN_CHARS]
                    content += f"\n\n[SYSTEM] Output truncated. Exceeded {MAX_RETURN_CHARS//1024}KB limit."
                    content += f"\n[SYSTEM] Use 'lines' or 'search' parameters for targeted retrieval."

                return json.dumps({"content": content, "file_size_bytes": file_size, "lines_returned": len(content_lines), "note": "Use 'lines' or 'search' parameters for targeted retrieval"})

    except Exception as e:
        return json.dumps({"error": f"Failed to read asset: {str(e)}"})


def register_asset_tools(mcp):
    """Register asset management tools with the MCP server."""
    from src.utils import offload_to_thread
    from src.security import validate_path
    import logging

    logger = logging.getLogger(__name__)

    @mcp.tool()
    def peek_asset(asset_path: str) -> List[types.Content]:
        """
        [VISION] Look at an image asset generated by the kernel.
        Use this when you create a plot and need to analyze the visual results.
        This allows multimodal LLMs (Claude 3.5 Sonnet, GPT-4o) to see and describe charts you generate.

        Args:
            asset_path: Path to the asset (e.g., 'assets/plot_abc.png' or 'assets/analysis_xyz.txt')

        Returns:
            Image content (Base64) if image asset, or text preview if text asset

        Example:
            # After generating a matplotlib figure:
            # plt.savefig('assets/dist.png')
            # peek_asset('assets/dist.png')  # Returns image so agent can see it
        """
        # [IIRB ACCESSIBILITY FIX P1] "Blind Painter" - allow agent to see images it creates
        try:
            # Resolve relative to assets directory
            assets_dir = Path("assets").resolve()
            filename = Path(asset_path).name
            full_path = validate_path(filename, assets_dir)
        except Exception as e:
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]

        if not full_path.exists():
            return [
                types.TextContent(
                    type="text",
                    text="Error: Asset not found. Did you run the cell that generates it?",
                )
            ]

        # Determine MIME type
        suffix = full_path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }

        if suffix not in mime_map:
            # Fallback for non-images (text assets)
            if suffix == ".txt":
                try:
                    content = full_path.read_text(encoding="utf-8")
                    # Limit preview to first 5000 chars
                    preview = content[:5000]
                    if len(content) > 5000:
                        preview += (
                            f"\n... (truncated, {len(content) - 5000} more chars)"
                        )
                    return [
                        types.TextContent(
                            type="text", text=f"Text Asset Content:\n{preview}"
                        )
                    ]
                except Exception as e:
                    return [
                        types.TextContent(type="text", text=f"Error reading text: {e}")
                    ]
            return [
                types.TextContent(
                    type="text",
                    text=f"Cannot peek at {suffix} files visually. Use read_asset() for text files.",
                )
            ]

        # Return image content for multimodal agent
        try:
            with open(full_path, "rb") as f:
                image_data = f.read()
                b64_data = base64.b64encode(image_data).decode("utf-8")

            logger.info(
                f"🖼️ Agent peeking at image: {full_path.name} ({len(image_data)} bytes)"
            )
            return [
                types.ImageContent(
                    type="image", data=b64_data, mimeType=mime_map[suffix]
                )
            ]
        except Exception as e:
            logger.error(f"Error reading image {asset_path}: {e}")
            return [types.TextContent(type="text", text=f"Error reading image: {e}")]

    @mcp.tool()
    @offload_to_thread
    def read_asset(
        asset_path: str,
        lines: Optional[List[int]] = None,
        search: Optional[str] = None,
        max_lines: int = 1000,
    ) -> str:
        """
        Read content from an offloaded output file (assets/text_*.txt).
        Use this to selectively retrieve large outputs without loading everything into context.

        Agent Use Cases:
        - Search for errors in 50MB training logs: read_asset("assets/text_abc123.txt", search="error")
        - View specific section: read_asset("assets/text_abc123.txt", lines=[100, 200])
        - Check final results: read_asset("assets/text_abc123.txt", lines=[1, 50])

        Args:
            asset_path: Path to the asset file (e.g. "assets/text_abc123.txt")
            lines: [start_line, end_line] for pagination (1-based, inclusive)
            search: Search term for grep-like filtering (case-insensitive)
            max_lines: Maximum lines to return (default 1000, max 5000)

        Returns:
            Content from the asset file (filtered or paginated)
        """
        # FIXED: Enforce hard caps on return size
        MAX_RETURN_CHARS = 20000  # 20KB safety limit
        MAX_RETURN_LINES = 500  # 500 lines safety limit

        # Limit max_lines to prevent context overflow
        max_lines = min(max_lines, MAX_RETURN_LINES)

        # Security: Prevent path traversal
        resolved_path = str(Path(asset_path).resolve())
        if ".." in resolved_path or not resolved_path.endswith(".txt"):
            return json.dumps(
                {
                    "error": "Invalid asset path. Must be a .txt file without path traversal."
                }
            )

        # Check if file exists
        if not Path(asset_path).exists():
            return json.dumps({"error": f"Asset file not found: {asset_path}"})

        try:
            # Get file info
            file_size = Path(asset_path).stat().st_size

            with open(asset_path, "r", encoding="utf-8", errors="replace") as f:
                if search:
                    # Grep mode: efficient for finding specific content
                    matches = []
                    for i, line in enumerate(f, 1):
                        if search.lower() in line.lower():
                            matches.append(f"{i}: {line.rstrip()}")
                            if len(matches) >= max_lines:
                                matches.append(
                                    f"\n... [Search limit reached: {max_lines} matches shown] ..."
                                )
                                break

                    if not matches:
                        return json.dumps(
                            {
                                "content": f"No matches found for '{search}'",
                                "file_size_bytes": file_size,
                                "matches": 0,
                            }
                        )

                    return json.dumps(
                        {
                            "content": "\n".join(matches),
                            "file_size_bytes": file_size,
                            "matches": len(matches),
                        }
                    )

                elif lines:
                    # Pagination mode: read specific line range
                    if len(lines) != 2 or lines[0] < 1 or lines[1] < lines[0]:
                        return json.dumps(
                            {
                                "error": "Invalid line range. Use [start_line, end_line] where start >= 1 and end >= start."
                            }
                        )

                    start_line, end_line = lines
                    # Cap the range
                    end_line = min(end_line, start_line + max_lines - 1)

                    selected_lines = []
                    last_line = 0
                    for i, line in enumerate(f, 1):
                        last_line = i
                        if i >= start_line:
                            selected_lines.append(line.rstrip())
                        if i >= end_line:
                            break

                    content = "\n".join(selected_lines)

                    # Truncate content if too large
                    if len(content) > MAX_RETURN_CHARS:
                        content = (
                            content[:MAX_RETURN_CHARS]
                            + f"\n... [Truncated: Exceeded {MAX_RETURN_CHARS} char limit] ..."
                        )

                    return json.dumps(
                        {
                            "content": content,
                            "file_size_bytes": file_size,
                            "line_range": [start_line, min(end_line, last_line)],
                            "lines_returned": len(selected_lines),
                        }
                    )

                else:
                    # Default: return first N lines
                    content_lines = []
                    for i, line in enumerate(f):
                        if i >= max_lines:
                            content_lines.append(
                                f"\n... [Content truncated at {max_lines} lines. Use 'lines' parameter for pagination] ..."
                            )
                            break
                        content_lines.append(line.rstrip())

                    content = "\n".join(content_lines)

                    # Truncate content if too large
                    if len(content) > MAX_RETURN_CHARS:
                        content = (
                            content[:MAX_RETURN_CHARS]
                            + f"\n... [Truncated: Exceeded {MAX_RETURN_CHARS} char limit] ..."
                        )

                    return json.dumps(
                        {
                            "content": content,
                            "file_size_bytes": file_size,
                            "lines_returned": len(content_lines),
                            "note": "Use 'lines' or 'search' parameters for targeted retrieval",
                        }
                    )

        except Exception as e:
            return json.dumps({"error": f"Failed to read asset: {str(e)}"})

    @mcp.tool()
    def get_asset_content(asset_path: str) -> str:
        """
        Retrieve base64-encoded content of an asset file (PNG, PDF, SVG, etc.).

        **Use Case**: When the server reports `[PNG SAVED: assets/xyz.png]` and you need
        to analyze the image content with multimodal capabilities.

        **Security**: Only allows access to assets/ directory (prevents path traversal).

        Args:
            asset_path: Relative path to asset, typically from execution output
                       Format: "assets/asset_abc123.png" or just "asset_abc123.png"

        Returns:
            JSON with:
            - mime_type: MIME type of the asset (e.g., "image/png")
            - data: Base64-encoded binary content
            - size_bytes: Size of the encoded data
            - filename: Original filename

        Agent Workflow Example:
            # 1. Execute cell that generates plot
            result = execute_cell(path, 0, "import matplotlib.pyplot as plt\\nplt.plot([1,2,3])")
            # Output: "[PNG SAVED: assets/asset_abc123.png]"

            # 2. Retrieve asset for analysis
            asset = get_asset_content("assets/asset_abc123.png")
            # Now can pass asset['data'] to multimodal model for description
        """
        import base64
        from src.security import validate_path

        # Normalize path separators
        asset_path = asset_path.replace("\\", "/")

        # Security: Extract just the filename if full path provided
        # Allows "assets/file.png" or just "file.png"
        path_parts = asset_path.split("/")
        if len(path_parts) > 1 and path_parts[0] == "assets":
            filename = path_parts[-1]
        else:
            filename = path_parts[-1]

        # Build full path relative to current working directory
        # Assets are always stored in assets/ subdirectory
        assets_dir = Path("assets").resolve()

        # Security check: Use validate_path to prevent path traversal
        try:
            full_path = validate_path(filename, assets_dir)
        except PermissionError as e:
            return json.dumps(
                {
                    "error": "Security violation: Path traversal attempt blocked",
                    "requested_path": asset_path,
                    "details": str(e),
                }
            )

        # Check if file exists
        if not full_path.exists():
            return json.dumps(
                {
                    "error": f"Asset not found: {asset_path}",
                    "checked_path": str(full_path),
                    "hint": "Ensure the cell has been executed and produced output. Check execution status.",
                }
            )

        # Determine MIME type from extension
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".pdf": "application/pdf",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        suffix = full_path.suffix.lower()
        mime_type = mime_map.get(suffix, "application/octet-stream")

        # Read and encode
        try:
            with open(full_path, "rb") as f:
                raw_bytes = f.read()
                data = base64.b64encode(raw_bytes).decode("utf-8")

            return json.dumps(
                {
                    "mime_type": mime_type,
                    "data": data,
                    "size_bytes": len(raw_bytes),
                    "encoded_size": len(data),
                    "filename": filename,
                    "full_path": str(full_path),
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps(
                {
                    "error": f"Failed to read asset: {str(e)}",
                    "asset_path": str(full_path),
                }
            )

    @mcp.tool()
    def prune_unused_assets(notebook_path: str, dry_run: bool = False):
        """
        [GIT-SAFE] Delete asset files not referenced in notebook.
        Implements "Reference Counting GC" for both image assets and text offload files.

        Scans notebook for asset references (images and text_*.txt files),
        deletes orphaned files. Automatically runs on kernel stop to maintain Git hygiene.
        Safe to run periodically to clean up after cell deletions.

        Args:
            notebook_path: Path to notebook file
            dry_run: If True, only report what would be deleted

        Returns:
            JSON with deleted/kept files and size freed

        Example:
            # Check what would be deleted
            prune_unused_assets("analysis.ipynb", dry_run=True)
            # Actually delete (also auto-runs on kernel stop)
            prune_unused_assets("analysis.ipynb")
        """
        from src.asset_manager import prune_unused_assets as _prune_assets

        result = _prune_assets(notebook_path, dry_run)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def get_assets_summary(notebook_path: str):
        """
        [GIT-SAFE] Get summary of asset usage for a notebook.

        Returns counts and sizes of assets (total, referenced, orphaned).
        Useful to understand storage impact before/after cleanup.

        Args:
            notebook_path: Path to notebook file

        Returns:
            JSON with asset statistics

        Example:
            get_assets_summary("analysis.ipynb")
            # Shows: 50 total assets, 30 referenced, 20 orphaned
        """
        from src.asset_manager import get_assets_summary as _get_summary

        result = _get_summary(notebook_path)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def prune_assets(notebook_path: str = None, aggressive: bool = False):
        """
        Aggressively prune assets to reduce disk usage.

        Args:
            notebook_path: Optional path to a specific notebook. If None, scans all notebooks
            aggressive: If True, performs LRU pruning until under quota (default quotas: 400MB)

        Returns:
            JSON summary of action taken
        """
        from src.asset_manager import prune_unused_assets as _prune_assets
        from src.utils import check_asset_limits
        from pathlib import Path

        reports = []

        if notebook_path:
            assets_dir = Path(notebook_path).resolve().parent / "assets"
            if not assets_dir.exists():
                return json.dumps({"message": f"No assets directory at {assets_dir}"}, indent=2)

            # Dry run first when not aggressive
            if not aggressive:
                result = _prune_assets(notebook_path, dry_run=True)
                return json.dumps(result, indent=2)

            # Aggressive: call check_asset_limits with 400MB
            check_asset_limits(assets_dir, max_size_bytes=400 * 1024 * 1024)
            result = _prune_assets(notebook_path, dry_run=False)
            reports.append({"notebook": notebook_path, "result": result})
        else:
            # Scan repository for assets/ directories
            root = Path('.').resolve()
            for assets_dir in root.rglob('assets'):
                if assets_dir.is_dir():
                    # Best-effort: apply quota to each assets dir
                    try:
                        check_asset_limits(assets_dir, max_size_bytes=400 * 1024 * 1024)
                        # No-op: let prune_unused_assets determine orphaned files
                        nb_candidate = assets_dir.parent / (assets_dir.parent.name + '.ipynb')
                        result = _prune_assets(str(nb_candidate), dry_run=False)
                        reports.append({"notebook": str(nb_candidate), "result": result})
                    except Exception as e:
                        reports.append({"assets_dir": str(assets_dir), "error": str(e)})

        return json.dumps(reports, indent=2)
