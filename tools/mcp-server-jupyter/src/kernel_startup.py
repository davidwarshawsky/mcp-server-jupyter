"""
Kernel Startup Code
===================

This module contains the Python code injected into newly started Jupyter kernels.
It configures autoreload, visualization backends, error handlers, and inspection helpers.

By extracting this code to a dedicated file:
1. The startup logic can be linted and tested independently
2. Changes to startup behavior are easier to track
3. The main session.py file is cleaner
4. Security audits of injected code are more transparent
"""

# [SECURITY] Safe Inspection Helper
INSPECT_HELPER_CODE = """
def _mcp_inspect(var_name):
    import builtins
    import sys

    def sanitize_preview(text):
        # [DAY 22 FIX] Remove obvious prompt-injection phrases from data previews
        if not isinstance(text, str):
            return text
        dangerous = ["Ignore previous", "System prompt", "You are", "<SYSTEM>"]
        for d in dangerous:
            text = text.replace(d, "[REDACTED_PATTERN]")
        return text
    
    # Safe lookup: Check locals then globals
    # Note: In ipykernel, user variables are in globals()
    ns = globals()
    if var_name not in ns:
        return f"Variable '{var_name}' not found."
    
    obj = ns[var_name]
    
    try:
        t_name = type(obj).__name__
        output = [f"### Type: {t_name}"]
        
        # Check for pandas/numpy without importing if not already imported
        is_pd_df = 'pandas' in sys.modules and isinstance(obj, sys.modules['pandas'].DataFrame)
        is_pd_series = 'pandas' in sys.modules and isinstance(obj, sys.modules['pandas'].Series)
        is_numpy = 'numpy' in sys.modules and hasattr(obj, 'shape') and hasattr(obj, 'dtype')
        
        # Safe Primitives
        if isinstance(obj, (int, float, bool, str, bytes, type(None))):
             output.append(f"- Value: {str(obj)[:500]}")

        elif is_pd_df:
            output.append(f"- Shape: {obj.shape}")
            n_cols = len(obj.columns)
            
            # [DUH FIX #5] Smart schema for wide DataFrames
            if n_cols <= 50:
                output.append(f"- Columns: {list(obj.columns)}")
            else:
                # Wide DataFrame - show summary instead of all 5000 columns
                output.append(f"- Columns: ({n_cols} total - too many to list)")
                output.append(f"  First 10: {list(obj.columns[:10])}")
                output.append(f"  Last 10: {list(obj.columns[-10:])}")
                # Group by dtype for quick overview
                dtype_counts = obj.dtypes.value_counts().to_dict()
                output.append(f"  By dtype: {dict(dtype_counts)}")
                output.append("  💡 Use search_dataframe_columns(df_name, 'pattern') to find specific columns")
            
            output.append("\\n#### Head (3 rows):")
            # For wide DFs, only show first 10 columns in preview
            preview_df = obj.head(3)
            if n_cols > 10:
                preview_df = preview_df.iloc[:, :10]
                output.append(f"(Showing first 10 of {n_cols} columns)")
            try:
                import io
                md_buf = io.StringIO()
                preview_df.to_markdown(buf=md_buf, index=False)
                output.append(md_buf.getvalue())
            except:
                output.append(str(preview_df))
            
        elif is_pd_series:
            output.append(f"- Length: {len(obj)}")
            output.append(f"- Dtype: {obj.dtype}")
            output.append("\\n#### Head (5 elements):")
            output.append(str(obj.head(5)))
        
        elif is_numpy:
            output.append(f"- Shape: {obj.shape}")
            output.append(f"- Dtype: {obj.dtype}")
            if obj.size > 0 and obj.size <= 10:
                output.append(f"- Values:\\n{str(obj)}")
            elif obj.size > 10:
                output.append(f"- Sample (first 5 elements):\\n{str(obj.flat[:5])}")
        
        elif isinstance(obj, (list, tuple)):
            output.append(f"- Length: {len(obj)}")
            if len(obj) > 0 and len(obj) <= 5:
                output.append(f"- Elements:\\n{str(obj)}")
            elif len(obj) > 5:
                output.append(f"- First 5 elements:\\n{str(obj[:5])}")
        
        elif isinstance(obj, dict):
            output.append(f"- Keys: {list(obj.keys())[:10]}")
            if len(obj) > 10:
                output.append(f"  (showing first 10 of {len(obj)} keys)")
        
        elif hasattr(obj, '__dict__'):
            output.append(f"- Attributes: {list(vars(obj).keys())[:10]}")
        
        return sanitize_preview("\\n".join(output))
    except Exception as e:
        return f"Error inspecting {var_name}: {str(e)}"

def _mcp_search_columns(df_name, pattern):
    '''
    [DUH FIX #5] Search DataFrame columns by regex pattern.
    
    For wide DataFrames (5000+ columns like genomics data),
    this lets the agent find specific columns without hallucinating.
    '''
    import sys
    import re
    
    ns = globals()
    if df_name not in ns:
        return f"DataFrame '{df_name}' not found."
    
    df = ns[df_name]
    
    if 'pandas' not in sys.modules:
        return "pandas not available"
    
    pd = sys.modules['pandas']
    if not isinstance(df, pd.DataFrame):
        return f"'{df_name}' is not a DataFrame (type: {type(df).__name__})"
    
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        matches = [col for col in df.columns if regex.search(str(col))]
        
        if not matches:
            return f"No columns matching '{pattern}' in {df_name} ({len(df.columns)} columns)"
        
        result = [f"### Columns matching '{pattern}' in {df_name}"]
        result.append(f"Found {len(matches)} matches:")
        
        # Show matches with their dtype
        for col in matches[:50]:  # Limit to 50 results
            dtype = str(df[col].dtype)
            result.append(f"- `{col}` ({dtype})")
        
        if len(matches) > 50:
            result.append(f"... and {len(matches) - 50} more")
        
        return "\\n".join(result)
    except Exception as e:
        return f"Error searching columns: {str(e)}"
"""

# [DS UX FIX] %%duckdb and %%sql Magic Commands
# Data scientists prefer writing SQL directly, not wrapped in Python strings
DUCKDB_MAGIC_CODE = """
# [DS UX] Register %%duckdb and %%sql magics for native SQL syntax
try:
    from IPython.core.magic import register_cell_magic
    from IPython import get_ipython
    import sys
    
    @register_cell_magic
    def duckdb(line, cell):
        '''
        Run SQL queries on DataFrames using DuckDB.
        
        Usage:
            %%duckdb
            SELECT * FROM df_sales WHERE revenue > 1000
        
        All DataFrames in the namespace are automatically available as tables.
        Results are returned as a DataFrame.
        '''
        try:
            import duckdb
        except ImportError:
            print("❌ DuckDB not installed. Run: pip install duckdb")
            return None
        
        # Get IPython instance
        shell = get_ipython()
        if not shell:
            print("❌ IPython not found.")
            return None

        # Get all DataFrames from user namespace
        ns = shell.user_ns
        dataframes = {}
        
        # Check for pandas DataFrames robustly
        for name, obj in ns.items():
            if name.startswith('_'):
                continue
            t_name = type(obj).__name__
            if t_name == 'DataFrame':
                # Double check it's actually a pandas DF
                if hasattr(obj, 'to_markdown') and hasattr(obj, 'columns'):
                    dataframes[name] = obj
        
        if not dataframes:
            print("⚠️ No DataFrames found in namespace. Load data first.")
            return None
        
        # Execute SQL with DataFrames registered as tables
        try:
            conn = duckdb.connect(':memory:')
            for name, df in dataframes.items():
                conn.register(name, df)
            
            result = conn.execute(cell).fetchdf()
            conn.close()
            
            # Returning the result allows it to be displayed and captured
            return result
        except Exception as e:
            print(f"❌ SQL Error: {e}")
            return None
    
    # Alias %%sql to %%duckdb for familiarity
    @register_cell_magic
    def sql(line, cell):
        '''Alias for %%duckdb magic.'''
        return duckdb(line, cell)
    
    print("✅ SQL magics loaded: Use %%duckdb or %%sql to query DataFrames")
    
except Exception as e:
    # Silently fail if IPython magic registration fails
    pass
"""

# Main startup code template
KERNEL_STARTUP_TEMPLATE = """
import sys
import os
import json
import traceback
from IPython import get_ipython

# [DAY 23 FIX] Environment Variable Masking: Patch only __repr__ and __str__ on the existing os.environ class
try:
    def _safe_environ_repr(self):
        try:
            secure_dict = {}
            sensitive_keys = {'KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'AUTH'}
            for k, v in dict(self).items():
                if any(s in k.upper() for s in sensitive_keys):
                    secure_dict[k] = '***REDACTED***'
                else:
                    secure_dict[k] = v
            return str(secure_dict)
        except Exception:
            return repr(dict(self))

    def _safe_environ_str(self):
        return _safe_environ_repr(self)

    try:
        # Only patch the string representations; do not alter underlying mapping type
        os.environ.__class__.__repr__ = _safe_environ_repr
        os.environ.__class__.__str__ = _safe_environ_str
    except Exception:
        # Best-effort only; don't fail kernel startup if this isn't possible
        pass
except Exception:
    pass

# [PHASE 2: Autoreload Magic]
# Automatically reload modules when they change (saves kernel restarts during dev)
try:
    get_ipython().run_line_magic('load_ext', 'autoreload')
    get_ipython().run_line_magic('autoreload', '2')
except Exception:
    pass

# [STDIN ENABLED] MCP handles input() requests via stdin channel
# Interactive input is now supported via MCP notifications

# [SECURITY] Safe Inspection Helper
{INSPECT_HELPER_CODE}

# [DS UX] SQL Magic Commands
{DUCKDB_MAGIC_CODE}

# [PHASE 4: Smart Error Recovery]
# Inject a custom exception handler to provide context-aware error reports
def _mcp_handler(shell, etype, value, tb, tb_offset=None, **kwargs):
    # Print standard traceback
    if hasattr(sys, 'last_type'):
        del sys.last_type
    if hasattr(sys, 'last_value'):
        del sys.last_value
    if hasattr(sys, 'last_traceback'):
        del sys.last_traceback
        
    traceback.print_exception(etype, value, tb)
    
    # Generate sidecar JSON
    try:
        error_context = {{
            "error": str(value),
            "type": etype.__name__,
            "suggestion": "Check your inputs."
        }}
        sidecar_msg = f"\\n__MCP_ERROR_CONTEXT_START__\\n{{json.dumps(error_context)}}\\n__MCP_ERROR_CONTEXT_END__\\n"
        sys.stderr.write(sidecar_msg)
        sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"Error in MCP Handler: {{e}}\\n")
        sys.stderr.flush()

try:
    get_ipython().set_custom_exc((Exception,), _mcp_handler)
except Exception:
    pass

# [PHASE 3.3] Visualization Rendering
# We no longer force static backends globally.
# Agents should set renderers to PNG/SVG at the start of their session if needed.
# Humans can enjoy interactive plots (HTML/JS).
try:
    import matplotlib
    # matplotlib.use('Agg')  # [DISABLED] Allow interactive backends
    try:
        get_ipython().run_line_magic('matplotlib', 'inline')
    except:
        pass
except ImportError:
    pass

# Plotly: Default to interactive (HTML). Agent should set os.environ['PLOTLY_RENDERER'] = 'png' if needed.
try:
    import plotly
    # os.environ['PLOTLY_RENDERER'] = 'png' # [DISABLED]
except ImportError:
    pass

# Bokeh: Default to interactive. Agent should set os.environ['BOKEH_OUTPUT_BACKEND'] = 'svg' if needed.
try:
    import bokeh
    # os.environ['BOKEH_OUTPUT_BACKEND'] = 'svg' # [DISABLED]
except ImportError:
    pass
"""


def get_startup_code() -> str:
    """
    Returns minimal startup code for clean kernel initialization.
    
    Following the "Don't Touch My Bootloader" philosophy, we only inject
    essential autoreload functionality and nothing else.
    """
    return ""
