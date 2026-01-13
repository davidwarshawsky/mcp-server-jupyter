import base64
import hashlib
import re
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Any, Optional

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
    Normalizes line endings to prevent Windows/Unix mismatch.
    """
    # Normalize line endings to prevent Windows/Unix mismatch
    normalized = cell_source.replace('\r\n', '\n').strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

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
        
        soup = BeautifulSoup(html, 'lxml')
        table = soup.find('table')
        if not table:
            return None
        
        # Extract all rows (both thead and tbody)
        rows = table.find_all('tr')
        if len(rows) > 10:  # Too many rows
            return None
        
        markdown_lines = []
        for i, row in enumerate(rows):
            # Get all cells (th or td)
            cells = row.find_all(['th', 'td'])
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
        return None  # Parsing failed, fall back to default behavior

def sanitize_outputs(outputs: List[Any], asset_dir: str) -> str:
    """
    Processes raw notebook outputs for LLM consumption AND Human visualization.
    Implements "Asset-Based Output Storage" to prevent VS Code crashes and context overflow.
    
    Large text outputs (>2KB or >50 lines) are offloaded to assets/text_{hash}.txt,
    with preview stubs sent to VS Code/Agent.
    
    Returns:
        JSON String containing:
        - llm_summary: Text/Markdown optimized for the Agent (truncated, images as paths)
        - raw_outputs: List of dicts with original data/metadata for VS Code to render (Plotly, etc.)
    """
    import json
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
        'application/pdf': (4, 'pdf', True),   # (priority, extension, is_binary)
        'image/svg+xml': (3, 'svg', False),
        'image/png': (2, 'png', True),
        'image/jpeg': (1, 'jpeg', True),
    }

    # [SECRET REDACTION] Regex to catch common API keys
    # Catches sk-..., AWS, Google keys.
    SECRET_PATTERNS = [
        r'sk-[a-zA-Z0-9]{20,}',  # OpenAI looking keys
        r'AKIA[0-9A-Z]{16}',     # AWS Access Key
        r'AIza[0-9A-Za-z-_]{35}', # Google Cloud API Key
    ]

    def _redact_text(text: str) -> str:
        for pattern in SECRET_PATTERNS:
            text = re.sub(pattern, '[REDACTED_SECRET]', text)
        return text
    
    def _make_preview(text: str, max_lines: int) -> str:
        """Create a preview of text by showing first and last lines."""
        lines = text.split('\n')
        if len(lines) <= max_lines:
            return text
        
        preview_lines = max_lines // 2
        head = '\n'.join(lines[:preview_lines])
        tail = '\n'.join(lines[-preview_lines:])
        return f"{head}\n... [{len(lines) - max_lines} lines omitted] ...\n{tail}"
    
    def _offload_text_to_asset(raw_text: str, asset_dir: str, max_inline_chars: int, max_inline_lines: int) -> tuple:
        """
        Offload large text to asset file and return (stub_text, asset_path, metadata).
        Returns (None, None, None) if text is small enough to keep inline.
        """
        if len(raw_text) <= max_inline_chars and raw_text.count('\n') <= max_inline_lines:
            return None, None, None
        
        # 1. Save to Asset
        content_hash = hashlib.md5(raw_text.encode()).hexdigest()
        asset_filename = f"text_{content_hash}.txt"
        asset_path = Path(asset_dir) / asset_filename
        
        with open(asset_path, 'w', encoding='utf-8') as f:
            f.write(raw_text)
        
        # 2. Create Preview Stub
        preview = _make_preview(raw_text, max_inline_lines)
        line_count = raw_text.count('\n') + 1
        size_kb = len(raw_text) / 1024
        
        stub_msg = f"\n\n>>> FULL OUTPUT ({size_kb:.1f}KB, {line_count} lines) SAVED TO: {asset_filename} <<<"
        stub_text = preview + stub_msg
        
        # 3. Create Metadata
        metadata = {
            "mcp_asset": {
                "path": str(asset_path).replace("\\", "/"),
                "type": "text/plain",
                "size_bytes": len(raw_text),
                "line_count": line_count
            }
        }
        
        return stub_text, asset_path, metadata
    
    for out in outputs:
        # Normalize to dict
        if hasattr(out, 'to_dict'):
            out_dict = out.to_dict()
        elif isinstance(out, dict):
            out_dict = out
        else:
            # Fallback for objects that behave like dicts but might not be
            out_dict = out.__dict__ if hasattr(out, '__dict__') else {}
            
        output_type = out_dict.get('output_type', '')
        data = out_dict.get('data', {})
        metadata = out_dict.get('metadata', {})
        
        # --- 1. Build Raw Outputs for VS Code (Rich Visualization) ---
        # We need to map NBFormat types to what VS Code expects
        # NotebookOutput in TS expects { output_type, data, metadata, text, ... }
        clean_raw = {
            "output_type": output_type,
            "metadata": metadata
        }
        
        if output_type == 'stream':
            clean_raw["name"] = out_dict.get('name', 'stdout')
            clean_raw["text"] = out_dict.get('text', '')
        elif output_type == 'error':
            clean_raw["ename"] = out_dict.get('ename', '')
            clean_raw["evalue"] = out_dict.get('evalue', '')
            clean_raw["traceback"] = out_dict.get('traceback', [])
        elif output_type in ['execute_result', 'display_data']:
            clean_raw["data"] = data
            clean_raw["execution_count"] = out_dict.get('execution_count')
            
        raw_outputs.append(clean_raw)
        
        # --- 2. Build LLM Summary (Text Only + Asset Paths) ---
        
        # Handle Binary Assets (Images, PDFs) with Priority
        if output_type in ['display_data', 'execute_result']:
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
                try:
                    if is_binary:
                        # Decode base64 binary data
                        asset_bytes = base64.b64decode(content)
                        fname = f"asset_{hashlib.md5(asset_bytes).hexdigest()[:12]}.{ext}"
                        save_path = Path(asset_dir) / fname
                        with open(save_path, "wb") as f:
                            f.write(asset_bytes)
                    else:
                        # SVG is text-based
                        content_bytes = content.encode('utf-8') if isinstance(content, str) else content
                        fname = f"asset_{hashlib.md5(content_bytes).hexdigest()[:12]}.{ext}"
                        save_path = Path(asset_dir) / fname
                        with open(save_path, "w", encoding='utf-8') as f:
                            f.write(content if isinstance(content, str) else content.decode('utf-8'))
                    
                    # Report to LLM with forward slashes for cross-platform compatibility
                    report_path = str(save_path).replace("\\", "/")
                    llm_summary.append(f"[{ext.upper()} SAVED: {report_path}]")
                except Exception as e:
                    llm_summary.append(f"[Error saving {ext.upper()}: {str(e)}]")
                
        # Handle Text (execute_result) with Asset Offloading
        if 'text/plain' in data:
            text = data['text/plain']
            # [SECRET REDACTION]
            text = _redact_text(text)
            
            # Check if text should be offloaded
            stub_text, asset_path, asset_metadata = _offload_text_to_asset(
                text, asset_dir, MAX_INLINE_CHARS, MAX_INLINE_LINES
            )
            
            if stub_text:
                # Text was offloaded - update both raw output and LLM summary
                data['text/plain'] = stub_text
                out_dict['metadata'].update(asset_metadata)
                clean_raw['metadata'].update(asset_metadata)
                llm_summary.append(stub_text)
            else:
                # Text is small enough to keep inline
                llm_summary.append(text)
        
        # Handle HTML (often pandas DataFrames)
        if 'text/html' in data:
            html = data['text/html']
            # [SECRET REDACTION] (Less likely in HTML but good hygiene)
            html = _redact_text(html)
            
            # Check for Plotly/Bokeh interactive charts
            is_plotly = 'plotly' in html.lower() or 'plotly.js' in html.lower()
            is_bokeh = 'bokeh' in html.lower() or 'bkroot' in html.lower()
            
            if is_plotly or is_bokeh:
                # Chart detected
                chart_type = 'Plotly' if is_plotly else 'Bokeh'
                llm_summary.append(f"[{chart_type} Chart - Interactive View available in VS Code]")
            elif '<table' in html.lower():
                # IMPROVEMENT: Show small tables inline, hide large ones
                # Limits: 10 rows × 10 columns to prevent context bloat
                if len(html) < 3000:  # Small HTML, worth trying to convert
                    markdown_table = _convert_small_html_table_to_markdown(html)
                    if markdown_table:
                        llm_summary.append("[Data Preview]:\n" + markdown_table)
                    else:
                        # Table too large or parsing failed
                        llm_summary.append("[HTML Table detected - Use inspect_variable() to view DataFrame]")
                else:
                    # Large HTML table
                    llm_summary.append("[Large HTML Table detected - Use inspect_variable() to view DataFrame]")
            else:
                # Non-table, non-chart HTML: strip tags and truncate
                clean_text = re.sub('<[^<]+?>', ' ', html)
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                if len(clean_text) > 1500:
                    clean_text = clean_text[:750] + "... [TRUNCATED]"
                llm_summary.append(f"[HTML Content]: {clean_text}")

        # Handle Stream Text (stdout/stderr) with Asset Offloading
        if output_type == 'stream':
            text = out_dict.get('text', '')
            # Strip ANSI escape codes
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            text = ansi_escape.sub('', text)
            
            # [SECRET REDACTION]
            text = _redact_text(text)
            
            # Check if text should be offloaded
            stub_text, asset_path, asset_metadata = _offload_text_to_asset(
                text, asset_dir, MAX_INLINE_CHARS, MAX_INLINE_LINES
            )
            
            if stub_text:
                # Text was offloaded - update both raw output and LLM summary
                out_dict['text'] = stub_text
                if 'metadata' not in out_dict:
                    out_dict['metadata'] = {}
                out_dict['metadata'].update(asset_metadata)
                clean_raw['text'] = stub_text
                clean_raw['metadata'].update(asset_metadata)
                llm_summary.append(stub_text)
            else:
                # Text is small enough to keep inline
                llm_summary.append(text)
            
        # Handle Errors
        if output_type == 'error':
            ename = out_dict.get('ename', '')
            evalue = out_dict.get('evalue', '')
            traceback = out_dict.get('traceback', [])
            
            # Strip ANSI from traceback
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_traceback = [ansi_escape.sub('', line) for line in traceback]
            
            # [SECRET REDACTION]
            clean_traceback = [_redact_text(line) for line in clean_traceback]

            
            # Build clean error message
            error_msg = f"Error: {ename}: {evalue}"
            if clean_traceback:
                error_msg += "\n" + "\n".join(clean_traceback[-10:])  # Last 10 lines of traceback
            llm_summary.append(error_msg)

    # Return structured data for both LLM (summary) and VS Code (rich output)
    return json.dumps({
        "llm_summary": "\n".join(llm_summary),
        "raw_outputs": raw_outputs
    })

def get_project_root(start_path: Path) -> Path:
    """
    Finds the project root by looking for common markers (.git, pyproject.toml).
    Walks up from start_path.
    """
    current = start_path.resolve()
    for _ in range(10): # Limit traversing depth
        if (current / ".git").exists() or \
           (current / "pyproject.toml").exists() or \
           (current / "requirements.txt").exists() or \
           (current / ".devcontainer").exists() or \
           (current / ".env").exists():
            return current
        
        parent = current.parent
        if parent == current: # Reached filesystem root
            break
        current = parent
    
    return start_path # Fallback to start path if no root marker found


