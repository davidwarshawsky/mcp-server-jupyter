import base64
import hashlib
import re
from pathlib import Path
from typing import List, Any, Optional

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
    Processes raw notebook outputs for LLM consumption.
    
    Key Features:
    - Saves binary assets (PDF, SVG, PNG, JPEG) to disk to prevent context bloat
    - Priority handling: PDF > SVG > PNG > JPEG (saves highest priority only per output)
    - Hash-based deduplication: asset_{hash}.{ext} prevents duplicates
    - ANSI escape stripping: Removes color codes for LLM readability
    - HTML table detection: Replaces with indicator to use inspect_variable
    - Truncation: Text > 1500 chars gets truncated with indicator
    
    Args:
        outputs: Raw NBFormat outputs from cell execution
        asset_dir: Directory to save extracted binary assets
        
    Returns:
        Clean text summary suitable for LLM context
        
    Side Effects:
        Creates asset_dir if doesn't exist
        Writes binary files (PNG, JPEG, SVG, PDF) to disk
    """
    llm_summary = []
    Path(asset_dir).mkdir(parents=True, exist_ok=True)
    
    # Auto-gitignore assets/ to prevent pollution (Git-awareness)
    from src.asset_manager import ensure_assets_gitignored
    try:
        ensure_assets_gitignored(asset_dir)
    except Exception:
        pass  # Best effort - don't fail if gitignore update fails
    
    # Asset priority: PDF > SVG > PNG > JPEG (higher number = higher priority)
    ASSET_PRIORITY = {
        'application/pdf': (4, 'pdf', True),   # (priority, extension, is_binary)
        'image/svg+xml': (3, 'svg', False),
        'image/png': (2, 'png', True),
        'image/jpeg': (1, 'jpeg', True),
    }
    
    for out in outputs:
        # Access data safely whether it's an object or dict
        output_type = out.get('output_type') if isinstance(out, dict) else getattr(out, 'output_type', '')
        data = out.get('data', {}) if isinstance(out, dict) else getattr(out, 'data', {})
        
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
                
        # Handle Text (execute_result)
        if 'text/plain' in data:
            text = data['text/plain']
            # Truncate long output
            if len(text) > 1500:
                text = text[:750] + "\n... [TRUNCATED - Use inspect_variable() for full output] ...\n" + text[-500:]
            llm_summary.append(text)
        
        # Handle HTML (often pandas DataFrames)
        if 'text/html' in data:
            html = data['text/html']
            
            # Check for Plotly/Bokeh interactive charts
            is_plotly = 'plotly' in html.lower() or 'plotly.js' in html.lower()
            is_bokeh = 'bokeh' in html.lower() or 'bkroot' in html.lower()
            
            if is_plotly or is_bokeh:
                # Chart detected but not rendered as image (kaleido/selenium missing)
                chart_type = 'Plotly' if is_plotly else 'Bokeh'
                hint = f"[{chart_type} chart detected but not rendered as static image. "
                
                if is_plotly:
                    hint += "Install 'kaleido' in the kernel environment to enable PNG export: "
                    hint += "`pip install kaleido` or `conda install -c conda-forge python-kaleido`]"
                else:
                    hint += "Install 'selenium' and 'pillow' in the kernel environment to enable PNG export: "
                    hint += "`pip install selenium pillow`]"
                
                llm_summary.append(hint)
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

        # Handle Stream Text (stdout/stderr)
        if output_type == 'stream':
            text = out.get('text', '') if isinstance(out, dict) else getattr(out, 'text', '')
            # Strip ANSI escape codes (color codes from IPython)
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            text = ansi_escape.sub('', text)
            
            # Truncate long stream output
            if len(text) > 1500:
                text = text[:750] + "\n... [TRUNCATED] ...\n" + text[-500:]
            llm_summary.append(text)
            
        # Handle Errors
        if output_type == 'error':
            ename = out.get('ename', '') if isinstance(out, dict) else getattr(out, 'ename', '')
            evalue = out.get('evalue', '') if isinstance(out, dict) else getattr(out, 'evalue', '')
            traceback = out.get('traceback', []) if isinstance(out, dict) else getattr(out, 'traceback', [])
            
            # Strip ANSI from traceback
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_traceback = [ansi_escape.sub('', line) for line in traceback]
            
            # Build clean error message
            error_msg = f"Error: {ename}: {evalue}"
            if clean_traceback:
                error_msg += "\n" + "\n".join(clean_traceback[-10:])  # Last 10 lines of traceback
            llm_summary.append(error_msg)

    if not llm_summary:
        return ""
            
    return "\n".join(llm_summary)
