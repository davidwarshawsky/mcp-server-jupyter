#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick manual test for Cell ID-based tools.
"""
import sys
import json
from pathlib import Path
import os

# Fix Windows console encoding
if os.name == 'nt':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent))

from src.notebook import create_notebook, get_notebook_outline
from src.cell_id_manager import edit_cell_by_id, delete_cell_by_id, insert_cell_by_id

def test_cell_id_tools():
    """Test Cell ID operations"""
    test_file = Path("test_cell_ids.ipynb")
    
    # Cleanup if exists
    if test_file.exists():
        test_file.unlink()
    
    print("1. Creating notebook...")
    # Use the notebook module directly to bypass JSON parsing
    from src.notebook import create_notebook as _create_notebook
    _create_notebook(str(test_file), initial_cells=[
        {"type": "code", "content": "x = 1"},
        {"type": "code", "content": "y = 2"},
        {"type": "code", "content": "z = 3"}
    ])
    
    print("2. Getting outline (should auto-migrate to include Cell IDs)...")
    outline = get_notebook_outline(str(test_file))  # Returns list directly
    print(f"   Found {len(outline)} cells")
    for idx, cell in enumerate(outline):
        print(f"   Cell {idx}: ID={cell['id'][:8]}... source={cell['source_preview']}")
    
    print("\n3. Testing edit_cell_by_id...")
    cell_id_1 = outline[1]['id']
    result = edit_cell_by_id(str(test_file), cell_id_1, "y = 200  # EDITED", expected_index=1)
    print(f"   {result}")
    
    # Verify edit worked
    outline2 = get_notebook_outline(str(test_file))
    assert outline2[1]['source_preview'] == "y = 200  # EDITED", "Edit failed"
    assert outline2[1]['id'] == cell_id_1, "Cell ID changed!"
    print("   ✓ Edit successful, Cell ID stable")
    
    print("\n4. Testing insert_cell_by_id...")
    result = insert_cell_by_id(str(test_file), after_cell_id=cell_id_1, content="a = 100  # INSERTED", cell_type="code")
    print(f"   {result}")
    
    # Verify insert worked
    outline3 = get_notebook_outline(str(test_file))
    assert len(outline3) == 4, f"Expected 4 cells, got {len(outline3)}"
    assert outline3[2]['source_preview'] == "a = 100  # INSERTED", "Insert failed"
    print("   ✓ Insert successful")
    
    print("\n5. Testing delete_cell_by_id...")
    cell_id_2 = outline3[2]['id']  # The inserted cell
    result = delete_cell_by_id(str(test_file), cell_id_2, expected_index=2)
    print(f"   {result}")
    
    # Verify delete worked
    outline4 = get_notebook_outline(str(test_file))
    assert len(outline4) == 3, f"Expected 3 cells, got {len(outline4)}"
    print("   ✓ Delete successful")
    
    print("\n6. Testing StaleStateError detection...")
    try:
        # Try to edit cell at wrong index
        edit_cell_by_id(str(test_file), cell_id_1, "SHOULD FAIL", expected_index=999)
        print("   ✗ ERROR: Should have raised StaleStateError!")
    except Exception as e:
        if "StaleStateError" in str(type(e).__name__):
            print(f"   ✓ StaleStateError raised correctly: {e}")
        else:
            print(f"   ✗ Wrong exception type: {type(e).__name__}")
    
    print("\n✅ All Cell ID tools working correctly!")
    
    # Cleanup
    test_file.unlink()

if __name__ == "__main__":
    test_cell_id_tools()
