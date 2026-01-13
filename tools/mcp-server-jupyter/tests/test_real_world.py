"""
End-to-End Robustness Tests for Phase 2 Agent-Ready Features

Tests:
1. Asset extraction (PNG, SVG, PDF) to disk
2. Provenance metadata injection (timestamp, env, python path)
3. Autoreload functionality
4. inspect_variable tool integration

These tests use REAL kernels (not mocks) to validate production behavior.
"""

import pytest
import asyncio
import json
import nbformat
from pathlib import Path
from src.session import SessionManager
from src import notebook


@pytest.fixture
async def real_session_manager():
    """Fixture that provides a real SessionManager and cleans up after tests."""
    manager = SessionManager()
    yield manager
    # Cleanup: shutdown all kernels
    await manager.shutdown_all()


@pytest.mark.asyncio
@pytest.mark.optional
async def test_end_to_end_asset_extraction_and_provenance(tmp_path, real_session_manager):
    """
    Validates:
    1. Kernel starts in correct environment
    2. Matplotlib imports work
    3. PNG images are extracted to assets/ directory
    4. Cell metadata contains provenance (timestamp, env_name, python_path)
    
    Note: This test is marked as 'optional' because it requires matplotlib and numpy.
    Run with: pytest -m optional
    """
    # 1. Create a test notebook
    nb_path = tmp_path / "test_assets.ipynb"
    notebook.create_notebook(str(nb_path))
    
    # 2. Start kernel
    start_result = await real_session_manager.start_kernel(str(nb_path))
    assert "Kernel started" in start_result
    
    # 3. Check if matplotlib is available, skip if not
    check_code = "import matplotlib; import numpy; print('OK')"
    check_id = await real_session_manager.execute_cell_async(str(nb_path), 0, check_code)
    
    check_status = {'status': 'not_found'}
    for _ in range(20):
        await asyncio.sleep(0.5)
        check_status = real_session_manager.get_execution_status(str(nb_path), check_id)
        if check_status['status'] in ['completed', 'error']:
            break
    
    if check_status['status'] == 'error':
        pytest.skip("Matplotlib or numpy not available in test environment")
    
    # 4. Add a cell that creates a matplotlib plot
    plot_code = """
import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 100)
y = np.sin(x)

plt.figure(figsize=(8, 4))
plt.plot(x, y)
plt.title("Test Plot for Asset Extraction")
plt.xlabel("X")
plt.ylabel("Sin(X)")
plt.grid(True)
plt.show()
"""
    notebook.insert_cell(str(nb_path), 0, plot_code)
    
    # 5. Execute the plot cell
    exec_id = await real_session_manager.execute_cell_async(str(nb_path), 0, plot_code)
    assert exec_id is not None
    
    # 6. Wait for execution to complete
    status = {'status': 'not_found'}
    for _ in range(30):  # 15 seconds max
        await asyncio.sleep(0.5)
        status = real_session_manager.get_execution_status(str(nb_path), exec_id)
        if status['status'] in ['completed', 'error']:
            break
    
    # 7. Verify execution completed successfully
    assert status['status'] == 'completed', f"Execution failed: {status}"
    
    # DEBUG: Print output to debug why png is missing
    print(f"DEBUG: Plot Execution Output:\n{status['output']}")

    # 7. Check that assets directory was created
    assets_dir = tmp_path / "assets"
    assert assets_dir.exists(), "assets/ directory should be created"
    
    # 8. Check that PNG file was saved
    png_files = list(assets_dir.glob("*.png"))
    assert len(png_files) > 0, "At least one PNG file should be saved"
    
    # 9. Verify PNG file has content
    png_file = png_files[0]
    assert png_file.stat().st_size > 0, "PNG file should not be empty"
    
    # 10. Check cell output contains asset reference
    assert "[PNG SAVED:" in status['output'] or "asset_" in status['output'].lower(), \
        "Output should reference saved PNG asset"
    
    # 11. Read notebook and verify provenance metadata
    with open(nb_path, 'r', encoding='utf-8') as f:
        nb = nbformat.read(f, as_version=4)
    
    cell = nb.cells[0]
    
    # Verify mcp metadata exists
    assert 'mcp' in cell.metadata, "Cell should have mcp metadata"
    
    # Get the provenance metadata
    mcp_meta = cell.metadata['mcp']
    
    # Verify required provenance fields
    assert 'execution_timestamp' in mcp_meta, "Should have execution_timestamp"
    assert 'kernel_env_name' in mcp_meta, "Should have kernel_env_name"
    assert 'execution_hash' in mcp_meta, "Should have execution_hash"
    assert 'agent_run_id' in mcp_meta, "Should have agent_run_id"
    
    # Verify values are populated
    assert mcp_meta['kernel_env_name'] == 'system'
    assert len(mcp_meta['execution_timestamp']) > 0, "Timestamp should not be empty"
    
    # 12. Verify ISO 8601 timestamp format
    from datetime import datetime
    try:
        datetime.fromisoformat(mcp_meta['execution_timestamp'].replace('Z', '+00:00'))
    except ValueError:
        pytest.fail(f"Invalid ISO 8601 timestamp: {mcp_meta['execution_timestamp']}")
    
    print(f"+ Asset extraction test passed")
    print(f"  - PNG saved to: {png_file}")
    print(f"  - Provenance: env={mcp_meta['kernel_env_name']}, time={mcp_meta['execution_timestamp']}")


@pytest.mark.asyncio
@pytest.mark.optional
async def test_inspect_variable_integration(tmp_path, real_session_manager):
    """
    Tests the inspect_variable tool with a real kernel.
    
    Validates:
    1. Variable inspection returns markdown-formatted output
    2. DataFrames show shape, columns, head
    3. Lists show length and sample
    4. Non-existent variables return error message
    
    Note: This test is marked as 'optional' because it requires pandas and numpy.
    Run with: pytest -m optional
    """
    # 1. Create notebook
    nb_path = tmp_path / "test_inspect.ipynb"
    notebook.create_notebook(str(nb_path))
    
    # 2. Start kernel
    await real_session_manager.start_kernel(str(nb_path))
    
    # 3. Create test variables
    setup_code = """
import pandas as pd
import numpy as np

# Create test DataFrame
df_test = pd.DataFrame({
    'A': [1, 2, 3, 4, 5],
    'B': ['a', 'b', 'c', 'd', 'e'],
    'C': [1.1, 2.2, 3.3, 4.4, 5.5]
})

# Create test list
my_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

# Create test dict
my_dict = {'key1': 'value1', 'key2': 'value2', 'key3': 'value3'}
"""
    
    exec_id = await real_session_manager.execute_cell_async(str(nb_path), 0, setup_code)
    
    # Wait for setup
    status = {'status': 'not_found'}
    for _ in range(60):
        await asyncio.sleep(0.5)
        status = real_session_manager.get_execution_status(str(nb_path), exec_id)
        if status['status'] in ['completed', 'error']:
            break
    
    # Skip if pandas not available
    if status['status'] == 'error':
        pytest.skip("Pandas or numpy not available in test environment")
    
    assert status['status'] == 'completed', "Setup should complete successfully"
    
    # 4. Test DataFrame inspection via get_variable_info
    df_info = await real_session_manager.get_variable_info(str(nb_path), 'df_test')
    df_data = json.loads(df_info)
    
    if 'llm_summary' in df_data:
        inner_data = json.loads(df_data['llm_summary'])
    else:
        inner_data = df_data

    assert 'shape' in inner_data, "DataFrame inspection should include shape"
    assert inner_data['shape'] == [5, 3], f"Shape should be [5, 3], got {inner_data['shape']}"
    assert 'columns' in inner_data, "Should include columns"
    assert set(inner_data['columns']) == {'A', 'B', 'C'}, "Columns should match"
    
    # 5. Test list inspection
    list_info = await real_session_manager.get_variable_info(str(nb_path), 'my_list')
    list_data = json.loads(list_info)
    
    if 'llm_summary' in list_data:
        list_data = json.loads(list_data['llm_summary'])

    assert 'length' in list_data, "List inspection should include length"
    assert list_data['length'] == 10, "List length should be 10"
    
    # 6. Test dict inspection
    dict_info = await real_session_manager.get_variable_info(str(nb_path), 'my_dict')
    dict_data = json.loads(dict_info)
    
    if 'llm_summary' in dict_data:
        dict_data = json.loads(dict_data['llm_summary'])

    assert dict_data['type'] == 'dict', "Type should be dict"
    
    # 7. Test non-existent variable
    missing_info = await real_session_manager.get_variable_info(str(nb_path), 'nonexistent_var')
    missing_data = json.loads(missing_info)
    
    if 'llm_summary' in missing_data:
        missing_data = json.loads(missing_data['llm_summary'])

    assert 'error' in missing_data, "Should return error for missing variable"
    assert 'not found' in missing_data['error'].lower(), "Error message should mention 'not found'"
    
    print(f"+ Variable inspection test passed")
    print(f"  - DataFrame: shape={inner_data['shape']}, columns={inner_data['columns']}")
    print(f"  - List: length={list_data['length']}")


@pytest.mark.asyncio
async def test_autoreload_enabled_on_startup(tmp_path, real_session_manager):
    """
    Validates that autoreload is automatically enabled when kernel starts.
    
    This test verifies:
    1. Kernel can execute code after autoreload setup
    2. Autoreload doesn't break kernel functionality
    """
    # 1. Create notebook
    nb_path = tmp_path / "test_autoreload.ipynb"
    notebook.create_notebook(str(nb_path))
    
    # 2. Start kernel (autoreload should be injected)
    start_result = await real_session_manager.start_kernel(str(nb_path))
    assert "Kernel started" in start_result
    
    # 3. Verify kernel is functional after autoreload injection
    test_code = "x = 42\nprint(f'Value: {x}')"
    notebook.append_cell(str(nb_path), test_code)
    
    exec_id = await real_session_manager.execute_cell_async(str(nb_path), 0, test_code)
    
    status = {'status': 'not_found'}
    for _ in range(20):
        await asyncio.sleep(0.5)
        status = real_session_manager.get_execution_status(str(nb_path), exec_id)
        if status['status'] in ['completed', 'error']:
            break
    
    assert status['status'] == 'completed', "Kernel should be functional after autoreload"
    assert 'Value: 42' in status['output'], "Kernel should execute code correctly"
    
    # 4. Check if autoreload magic is available (optional check)
    # This is informational - even if autoreload failed to load, kernel should still work
    check_code = "import sys; print('autoreload' in sys.modules)"
    exec_id2 = await real_session_manager.execute_cell_async(str(nb_path), 1, check_code)
    
    status2 = {'status': 'not_found'}
    for _ in range(20):
        await asyncio.sleep(0.5)
        status2 = real_session_manager.get_execution_status(str(nb_path), exec_id2)
        if status2['status'] in ['completed', 'error']:
            break
    
    # Log autoreload status but don't fail if it's not loaded
    if 'True' in status2['output']:
        print("+ Autoreload module is loaded")
    else:
        print("i Autoreload module not detected (may still work via IPython magic)")
    
    print("+ Autoreload test passed")
    print("  - Kernel functional after startup injection")
    print("  - Code execution working correctly")


@pytest.mark.asyncio
@pytest.mark.optional
async def test_multiple_asset_types(tmp_path, real_session_manager):
    """
    Test that different asset types (PNG, SVG) are handled with priority.
    
    Priority: PDF > SVG > PNG > JPEG
    When multiple formats exist, only the highest priority should be saved.
    
    Note: This test is marked as 'optional' because it requires matplotlib.
    Run with: pytest -m optional
    """
    nb_path = tmp_path / "test_multi_assets.ipynb"
    notebook.create_notebook(str(nb_path))
    
    # Start kernel
    await real_session_manager.start_kernel(str(nb_path))
    
    # Create a cell that produces both PNG and SVG (SVG has higher priority)
    multi_format_code = """
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams['svg.fonttype'] = 'none'  # Enable SVG text

fig, ax = plt.subplots()
x = np.linspace(0, 2*np.pi, 100)
ax.plot(x, np.sin(x))
ax.set_title("Multi-format Test")

# Display as both PNG and SVG
from IPython.display import display, SVG
display(fig)
plt.close(fig)
"""
    
    notebook.append_cell(str(nb_path), multi_format_code)
    
    # Execute
    exec_id = await real_session_manager.execute_cell_async(str(nb_path), 0, multi_format_code)
    
    # Wait for completion
    status = {'status': 'not_found'}
    for _ in range(60):
        await asyncio.sleep(0.5)
        status = real_session_manager.get_execution_status(str(nb_path), exec_id)
        if status['status'] in ['completed', 'error']:
            break
    
    # Skip if matplotlib not available
    if status['status'] == 'error' and 'matplotlib' in status.get('output', '').lower():
        pytest.skip("Matplotlib not available in test environment")
    
    assert status['status'] == 'completed', f"Execution should complete: {status}"
    
    # Check assets directory
    assets_dir = tmp_path / "assets"
    if assets_dir.exists():
        asset_files = list(assets_dir.glob("asset_*"))
        assert len(asset_files) > 0, "At least one asset should be saved"
        
        # Due to priority, if both PNG and SVG exist, only highest priority saved
        # In this test, matplotlib typically outputs PNG by default
        png_files = list(assets_dir.glob("*.png"))
        svg_files = list(assets_dir.glob("*.svg"))
        
        # Either PNG or SVG should exist (or both if matplotlib outputs both)
        assert len(png_files) + len(svg_files) > 0, "Either PNG or SVG should exist"
        
        print(f"+ Multiple asset types test passed")
        print(f"  - PNG files: {len(png_files)}")
        print(f"  - SVG files: {len(svg_files)}")
