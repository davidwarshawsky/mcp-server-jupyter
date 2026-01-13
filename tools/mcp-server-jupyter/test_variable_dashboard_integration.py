"""
Test script to verify Variable Dashboard integration
"""
import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from session import SessionManager


async def test_variable_dashboard():
    """Test Variable Dashboard with get_variable_manifest"""
    print("=" * 60)
    print("Testing Variable Dashboard Integration")
    print("=" * 60)
    
    test_notebook = "/tmp/test_var_dashboard.ipynb"
    
    # Create simple notebook
    import nbformat
    nb = nbformat.v4.new_notebook()
    nb.cells = [
        nbformat.v4.new_code_cell("x = 42"),
        nbformat.v4.new_code_cell("message = 'Hello World'"),
        nbformat.v4.new_code_cell("data = [1, 2, 3, 4, 5]"),
    ]
    
    with open(test_notebook, 'w') as f:
        nbformat.write(nb, f)
    
    session_manager = SessionManager()
    
    try:
        # Start kernel
        print("\n1. Starting kernel...")
        await session_manager.start_kernel(test_notebook)
        print("✓ Kernel started")
        
        # Give kernel a moment to fully initialize
        await asyncio.sleep(1.0)
        
        # Verify kernel is in sessions
        from pathlib import Path
        resolved_path = str(Path(test_notebook).resolve())
        print(f"   Test notebook path: {test_notebook}")
        print(f"   Resolved path: {resolved_path}")
        print(f"   Sessions keys: {list(session_manager.sessions.keys())}")
        
        if resolved_path not in session_manager.sessions:
            print(f"❌ Kernel not found in sessions!")
            return
        
        # Execute cells to create variables
        print("\n2. Executing cells to create variables...")
        for i in range(3):
            task_id = await session_manager.execute_cell_async(test_notebook, i, nb.cells[i].source)
            
            # Wait for completion
            while True:
                status = session_manager.get_execution_status(test_notebook, task_id)
                if status["status"] in ["completed", "error"]:
                    break
                await asyncio.sleep(0.1)
            
            print(f"   ✓ Cell {i} executed")
        
        # Get variable manifest
        print("\n3. Getting variable manifest...")
        
        # Call run_simple_code directly instead of going through FastMCP tool
        import json
        manifest_code = """
import sys
import json
import types

def _is_user_var(name, val):
    if name.startswith('_') or name in ('In','Out','get_ipython','exit','quit'):
        return False
    mod = getattr(val, '__module__', None)
    if mod == 'builtins':
        return False
    if isinstance(val, types.ModuleType):
        return False
    if isinstance(val, types.FunctionType) or isinstance(val, type):
        return False
    return True

def _inspect_var():
    result = []
    user_ns = globals()
    for name, val in user_ns.items():
        if not _is_user_var(name, val):
            continue
        try:
            size_bytes = sys.getsizeof(val)
            if size_bytes >= 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            elif size_bytes >= 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes} B"
            result.append({
                "name": name,
                "type": type(val).__name__,
                "size": size_str
            })
        except Exception:
            pass
    return result

print(json.dumps(_inspect_var(), separators=(",", ":")))
"""
        
        manifest_json = await session_manager.run_simple_code(test_notebook, manifest_code)
        print(f"Raw result: {repr(manifest_json[:200] if len(manifest_json) > 200 else manifest_json)}")
        
        if manifest_json.startswith("Error"):
            print(f"❌ Error from get_variable_manifest: {manifest_json}")
            return
        
        # Parse the llm_summary wrapper
        try:
            wrapper = json.loads(manifest_json)
            # Extract the JSON array from llm_summary
            llm = wrapper.get('llm_summary', '')
            manifest = []
            try:
                # First try: direct parse of llm_summary
                manifest = json.loads(llm)
            except Exception:
                # Fallback: extract JSON array between first '[' and last ']'
                import re
                m = re.search(r"\[[\s\S]*\]", llm)
                if m:
                    manifest = json.loads(m.group(0))
                else:
                    # As a last resort, if raw_outputs has a small text/plain echo, try to parse it
                    if isinstance(wrapper.get('raw_outputs'), list) and wrapper['raw_outputs']:
                        for ro in wrapper['raw_outputs']:
                            tp = ro.get('text') or (ro.get('data') or {}).get('text/plain')
                            if isinstance(tp, str) and tp.strip().startswith('['):
                                try:
                                    manifest = json.loads(tp)
                                    break
                                except Exception:
                                    pass
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse JSON: {e}")
            print(f"   Raw output: {manifest_json[:500]}")
            return
        
        print(f"\nVariable Manifest ({len(manifest)} variables):")
        print("-" * 60)
        for var in manifest:
            print(f"  {var['name']:<15} {var['type']:<20} {var['size']}")
        print("-" * 60)
        
        # Verify expected variables exist
        var_names = {v['name'] for v in manifest}
        expected = {'x', 'message', 'data'}
        
        if expected.issubset(var_names):
            print("\n✅ All expected variables found!")
        else:
            missing = expected - var_names
            print(f"\n⚠ Missing variables: {missing}")
        
        # Test with empty kernel
        print("\n4. Testing with fresh kernel (no variables)...")
        test_notebook2 = "/tmp/test_var_dashboard_empty.ipynb"
        nb2 = nbformat.v4.new_notebook()
        with open(test_notebook2, 'w') as f:
            nbformat.write(nb2, f)
        
        await session_manager.start_kernel(test_notebook2)
        await asyncio.sleep(1.0)  # Give kernel time to initialize
        
        manifest2_json = await session_manager.run_simple_code(test_notebook2, manifest_code)
        wrapper2 = json.loads(manifest2_json)
        manifest2 = json.loads(wrapper2.get('llm_summary', '[]'))
        print(f"Empty kernel manifest: {len(manifest2)} variables")
        
        if len(manifest2) == 0:
            print("✅ Empty kernel handled correctly!")
        else:
            print(f"⚠ Unexpected variables in empty kernel: {[v['name'] for v in manifest2]}")
        
        # Cleanup
        await session_manager.stop_kernel(test_notebook)
        await session_manager.stop_kernel(test_notebook2)
        os.remove(test_notebook)
        os.remove(test_notebook2)
        
        print("\n" + "=" * 60)
        print("✅ Variable Dashboard Test Complete!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Cleanup on error
        try:
            await session_manager.stop_kernel(test_notebook)
            os.remove(test_notebook)
        except:
            pass


if __name__ == "__main__":
    asyncio.run(test_variable_dashboard())
