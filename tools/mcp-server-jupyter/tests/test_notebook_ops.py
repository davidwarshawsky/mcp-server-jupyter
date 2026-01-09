import pytest
import nbformat
import os
from pathlib import Path
from src import notebook

@pytest.fixture
def dummy_notebook(tmp_path):
    d = tmp_path / "subdir"
    d.mkdir()
    nb_path = d / "test.ipynb"
    
    nb = nbformat.v4.new_notebook()
    # Cell 0
    nb.cells.append(nbformat.v4.new_code_cell("print('Cell 0')"))
    # Cell 1
    nb.cells.append(nbformat.v4.new_code_cell("print('Cell 1')"))
    # Cell 2
    nb.cells.append(nbformat.v4.new_code_cell("print('Cell 2')"))
    
    with open(nb_path, 'w') as f:
        nbformat.write(nb, f)
        
    return str(nb_path.resolve())

def test_delete_cell_negative_index(dummy_notebook):
    # Delete last cell (-1), which is "Cell 2"
    res = notebook.delete_cell(dummy_notebook, -1)
    
    # Verify
    with open(dummy_notebook, 'r') as f:
        nb = nbformat.read(f, as_version=4)
        
    assert len(nb.cells) == 2
    assert "Cell 2" not in nb.cells[-1].source
    assert "Cell 1" in nb.cells[-1].source
    assert "deleted" in res

def test_delete_cell_out_of_bounds(dummy_notebook):
    with pytest.raises(IndexError):
        notebook.delete_cell(dummy_notebook, 100)
        
    with pytest.raises(IndexError):
        notebook.delete_cell(dummy_notebook, -100)

def test_insert_cell_negative_index(dummy_notebook):
    # Insert before last cell (-1). 
    # Current: [0, 1, 2]. Insert at -1 should make it [0, 1, NEW, 2] 
    # Wait, list.insert(-1) inserts before the last element.
    notebook.insert_cell(dummy_notebook, -1, "print('New -1')")
    
    with open(dummy_notebook, 'r') as f:
        nb = nbformat.read(f, as_version=4)
        
    assert len(nb.cells) == 4
    # Check position. Python's insert(-1) inserts before the last element.
    # So if [A, B, C], insert(-1, D) -> [A, B, D, C].
    assert nb.cells[-2].source == "print('New -1')"
    assert nb.cells[-1].source == "print('Cell 2')"

def test_edit_cell_clears_output(dummy_notebook):
    path = Path(dummy_notebook)
    # 1. Add output to cell 0
    with open(path, 'r') as f:
        nb = nbformat.read(f, as_version=4)
    # Use proper nbformat object
    output = nbformat.v4.new_output('stream', name='stdout', text='Old Output')
    nb.cells[0].outputs = [output]
    nb.cells[0].execution_count = 1
    with open(path, 'w') as f:
        nbformat.write(nb, f)
        
    # 2. Edit cell
    notebook.edit_cell(dummy_notebook, 0, "print('Updated')")
    
    # 3. Verify output cleared
    with open(path, 'r') as f:
        nb = nbformat.read(f, as_version=4)
        
    assert nb.cells[0].source == "print('Updated')"
    assert nb.cells[0].outputs == []
    assert nb.cells[0].execution_count is None
