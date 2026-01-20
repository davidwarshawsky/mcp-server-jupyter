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
            output.append(f"- Columns: {list(obj.columns)}")
            output.append("\\n#### Head (3 rows):")
            # to_markdown requires tabulate, fallback to string if fails
            try:
                import io
                md_buf = io.StringIO()
                obj.head(3).to_markdown(buf=md_buf, index=False)
                output.append(md_buf.getvalue())
            except:
                output.append(str(obj.head(3)))
            
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
        
        return "\\n".join(output)
    except Exception as e:
        return f"Error inspecting {var_name}: {str(e)}"
"""

# Main startup code template
KERNEL_STARTUP_TEMPLATE = """
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

# [PHASE 3.3] Force static rendering for interactive visualization libraries
# This allows AI agents to "see" plots that would otherwise be JavaScript-based
import os
try:
    import matplotlib
    matplotlib.use('Agg')  # Headless backend for matplotlib
    # Inline backend is still useful for png display
    try:
        get_ipython().run_line_magic('matplotlib', 'inline')
    except:
        pass
except ImportError:
    pass  # matplotlib not installed, skip

# Force Plotly to render as static PNG
# NOTE: Requires kaleido installed in kernel environment: pip install kaleido
try:
    import plotly
    try:
        import kaleido
        os.environ['PLOTLY_RENDERER'] = 'png'
    except ImportError:
        # Kaleido not installed - Plotly will fall back to HTML output
        # which will be sanitized to text by the asset extraction pipeline
        pass
except ImportError:
    pass  # plotly not installed, skip

# Force Bokeh to use static SVG backend
try:
    import bokeh
    os.environ['BOKEH_OUTPUT_BACKEND'] = 'svg'
except ImportError:
    pass  # bokeh not installed, skip
"""


def get_startup_code() -> str:
    """
    Returns the complete startup code to inject into a new kernel.
    
    Returns:
        str: Python code to execute in the kernel
    """
    return KERNEL_STARTUP_TEMPLATE.format(INSPECT_HELPER_CODE=INSPECT_HELPER_CODE)
