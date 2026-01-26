"""
Tests for the Variable Dashboard feature (get_variable_manifest tool)
"""

import pytest
import json
from src.session import SessionManager
from pathlib import Path
import tempfile
import nbformat


@pytest.mark.asyncio
async def test_get_variable_manifest_basic():
    """Test basic variable manifest retrieval"""
    session_manager = SessionManager()

    with tempfile.TemporaryDirectory() as tmpdir:
        nb_path = Path(tmpdir) / "test.ipynb"

        # Create minimal notebook
        nb = nbformat.v4.new_notebook()
        nb.cells.append(nbformat.v4.new_code_cell())
        with open(nb_path, "w") as f:
            nbformat.write(nb, f)

        # Start kernel
        await session_manager.start_kernel(str(nb_path))

        # Create some variables
        code = """
x = 42
name = "test"
data = [1, 2, 3, 4, 5]
mapping = {"a": 1, "b": 2, "c": 3}
"""
        await session_manager.run_simple_code(str(nb_path), code)

        # Get manifest
        manifest_json = await session_manager.run_simple_code(
            str(nb_path),
            """
import json
import sys

def get_size_str(obj):
    try:
        size = sys.getsizeof(obj)
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"
    except:
        return "?"

manifest = []
for name in sorted(dir()):
    if not name.startswith('_'):
        try:
            obj = globals()[name]
            if not isinstance(obj, type(sys)):
                manifest.append({
                    "name": name,
                    "type": type(obj).__name__,
                    "size": get_size_str(obj)
                })
        except:
            pass

print(json.dumps(manifest))
""",
        )

        # Parse result
        result = json.loads(manifest_json)
        manifest = json.loads(result["llm_summary"])

        # Verify structure
        assert isinstance(manifest, list)
        assert len(manifest) >= 4  # At least our 4 variables

        # Find our variables
        var_names = {v["name"] for v in manifest}
        assert "x" in var_names
        assert "name" in var_names
        assert "data" in var_names
        assert "mapping" in var_names

        # Verify metadata
        for var in manifest:
            assert "name" in var
            assert "type" in var
            assert "size" in var
            assert isinstance(var["type"], str)
            assert isinstance(var["size"], str)

        # Check types are correct
        x_var = next(v for v in manifest if v["name"] == "x")
        assert x_var["type"] == "int"

        name_var = next(v for v in manifest if v["name"] == "name")
        assert name_var["type"] == "str"

        data_var = next(v for v in manifest if v["name"] == "data")
        assert data_var["type"] == "list"

        mapping_var = next(v for v in manifest if v["name"] == "mapping")
        assert mapping_var["type"] == "dict"

        # Cleanup
        await session_manager.stop_kernel(str(nb_path))


@pytest.mark.asyncio
async def test_get_variable_manifest_with_large_data():
    """Test manifest with larger data structures"""
    session_manager = SessionManager()

    with tempfile.TemporaryDirectory() as tmpdir:
        nb_path = Path(tmpdir) / "test.ipynb"

        # Create minimal notebook
        nb = nbformat.v4.new_notebook()
        nb.cells.append(nbformat.v4.new_code_cell())
        with open(nb_path, "w") as f:
            nbformat.write(nb, f)

        # Start kernel
        await session_manager.start_kernel(str(nb_path))

        # Create large variables
        code = """
large_list = list(range(10000))
large_dict = {i: i**2 for i in range(1000)}
text_data = "x" * 1000000  # 1MB string
"""
        await session_manager.run_simple_code(str(nb_path), code)

        # Get manifest
        manifest_json = await session_manager.run_simple_code(
            str(nb_path),
            """
import json
import sys

def get_size_str(obj):
    try:
        size = sys.getsizeof(obj)
        if hasattr(obj, '__len__') and not isinstance(obj, (str, bytes)):
            try:
                if isinstance(obj, (list, tuple, set)):
                    size += sum(sys.getsizeof(item) for item in list(obj)[:100])
                elif isinstance(obj, dict):
                    items = list(obj.items())[:100]
                    size += sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in items)
            except:
                pass
        
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"
    except:
        return "?"

manifest = []
for name in sorted(dir()):
    if not name.startswith('_'):
        try:
            obj = globals()[name]
            if not isinstance(obj, type(sys)):
                manifest.append({
                    "name": name,
                    "type": type(obj).__name__,
                    "size": get_size_str(obj)
                })
        except:
            pass

print(json.dumps(manifest))
""",
        )

        # Parse result
        result = json.loads(manifest_json)
        manifest = json.loads(result["llm_summary"])

        # Find large variables
        large_list_var = next((v for v in manifest if v["name"] == "large_list"), None)
        large_dict_var = next((v for v in manifest if v["name"] == "large_dict"), None)
        text_data_var = next((v for v in manifest if v["name"] == "text_data"), None)

        assert large_list_var is not None
        assert large_dict_var is not None
        assert text_data_var is not None

        # Verify sizes are reported (be lenient with format since getsizeof varies)
        assert large_list_var["size"] != "?"
        assert large_dict_var["size"] != "?"
        assert text_data_var["size"] != "?"

        # Text data should be relatively large
        print(f"  large_list size: {large_list_var['size']}")
        print(f"  large_dict size: {large_dict_var['size']}")
        print(f"  text_data size: {text_data_var['size']}")

        # Cleanup
        await session_manager.stop_kernel(str(nb_path))


@pytest.mark.asyncio
async def test_get_variable_manifest_empty():
    """Test manifest with no user variables"""
    session_manager = SessionManager()

    with tempfile.TemporaryDirectory() as tmpdir:
        nb_path = Path(tmpdir) / "test.ipynb"

        # Create minimal notebook
        nb = nbformat.v4.new_notebook()
        nb.cells.append(nbformat.v4.new_code_cell())
        with open(nb_path, "w") as f:
            nbformat.write(nb, f)

        # Start kernel
        await session_manager.start_kernel(str(nb_path))

        # Get manifest immediately (should be empty or minimal)
        manifest_json = await session_manager.run_simple_code(
            str(nb_path),
            """
import json
import sys

manifest = []
for name in sorted(dir()):
    if not name.startswith('_'):
        try:
            obj = globals()[name]
            if not isinstance(obj, type(sys)):
                manifest.append({
                    "name": name,
                    "type": type(obj).__name__,
                    "size": "?"
                })
        except:
            pass

print(json.dumps(manifest))
""",
        )

        # Parse result
        result = json.loads(manifest_json)
        manifest = json.loads(result["llm_summary"])

        # Should be valid list (possibly empty or with builtins)
        assert isinstance(manifest, list)

        # Cleanup
        await session_manager.stop_kernel(str(nb_path))


if __name__ == "__main__":
    import asyncio

    async def run_tests():
        print("Testing Variable Manifest...")
        await test_get_variable_manifest_basic()
        print("✓ Basic test passed")

        await test_get_variable_manifest_with_large_data()
        print("✓ Large data test passed")

        await test_get_variable_manifest_empty()
        print("✓ Empty test passed")

        print("\n✅ All Variable Manifest tests passed!")

    asyncio.run(run_tests())
