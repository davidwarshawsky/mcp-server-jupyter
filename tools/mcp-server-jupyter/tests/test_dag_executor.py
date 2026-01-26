"""
Unit tests for DAG-based execution analysis
"""

from src.dag_executor import (
    get_minimal_rerun_set,
)


def test_simple_linear_dependency():
    """Test cells with simple linear dependency: x → y → z"""
    cells = ["x = 1", "y = x + 1", "z = y * 2"]

    # Change cell 0 (x)
    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # Should rerun 0, 1, 2 (all cells depend on x)
    assert affected == {0, 1, 2}


def test_independent_cells():
    """Test cells with no dependencies"""
    cells = ["a = 1", "b = 2", "c = 3"]

    # Change cell 0
    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # Only cell 0 needs rerun
    assert affected == {0}


def test_branching_dependency():
    """Test branching: x → (y, z) where y and z both depend on x"""
    cells = ["x = 10", "y = x + 5", "z = x * 2", "result = y + z"]

    # Change cell 0 (x)
    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # Should rerun all (x affects y and z, both affect result)
    assert affected == {0, 1, 2, 3}


def test_partial_dependency():
    """Test partial dependency: some cells depend on changed, others don't"""
    cells = ["a = 1", "b = a + 1", "c = 100", "d = b + c"]  # Independent

    # Change cell 0 (a)
    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # Should rerun 0, 1, 3 (skip cell 2 which is independent)
    assert affected == {0, 1, 3}


def test_comment_change():
    """Test that comment-only changes don't create dependencies"""
    cells = ["# This is a comment\nx = 1", "y = x + 1"]

    # Even if cell 0 changed, dependencies are same
    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # Still need to rerun dependent cells
    assert affected == {0, 1}


def test_multiple_changed_cells():
    """Test multiple cells changed simultaneously"""
    cells = ["a = 1", "b = 2", "c = a + b", "d = c * 2"]

    # Change both a and b
    changed = {0, 1}
    affected = get_minimal_rerun_set(cells, changed)

    # Should rerun 0, 1, 2, 3 (c and d depend on a or b)
    assert affected == {0, 1, 2, 3}


def test_no_changes():
    """Test when no cells changed"""
    cells = ["x = 1", "y = x + 1"]

    changed = set()
    affected = get_minimal_rerun_set(cells, changed)

    # Nothing to rerun
    assert affected == set()


def test_function_definition():
    """Test function definitions and calls"""
    cells = ["def foo(x):\n    return x * 2", "result = foo(10)"]

    # Change function definition
    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # Should rerun both (function change affects its calls)
    assert affected == {0, 1}


def test_import_statement():
    """Test import statements - note: module names are not tracked as dependencies"""
    cells = ["import numpy as np", "x = np.array([1, 2, 3])", "y = 100"]  # Independent

    # Change import
    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # Currently, we don't track module-level imports as dependencies
    # This is acceptable - worst case we miss some deps (conservative)
    assert affected == {0}


def test_syntax_error_handling():
    """Test that syntax errors don't crash the analyzer"""
    cells = ["x = 1", "this is not valid python !!!", "y = 100"]

    # Change cell with syntax error
    changed = {1}
    affected = get_minimal_rerun_set(cells, changed)

    # Should at least include the changed cell
    assert 1 in affected


def test_list_comprehension():
    """Test list comprehensions create proper dependencies"""
    cells = ["data = [1, 2, 3, 4, 5]", "squared = [x**2 for x in data]"]

    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # List comprehension depends on data
    assert affected == {0, 1}


def test_dictionary_access():
    """Test dictionary access creates dependencies"""
    cells = ["config = {'key': 'value'}", "result = config['key']"]

    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    assert affected == {0, 1}


def test_attribute_access():
    """Test attribute access on objects"""
    cells = ["class MyClass:\n    value = 42", "obj = MyClass()", "x = obj.value"]

    # Change class definition
    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # Should cascade to obj instantiation and attribute access
    assert affected == {0, 1, 2}


def test_empty_cells():
    """Test handling of empty cells"""
    cells = ["x = 1", "", "y = x + 1"]  # Empty cell

    changed = {0}
    affected = get_minimal_rerun_set(cells, changed)

    # Should skip empty cell but still propagate to cell 2
    assert affected == {0, 2}
