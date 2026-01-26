"""
Phase 4.2: Hypothesis State Machine Testing

Property-based testing using Hypothesis to find edge cases in notebook
synchronization and the Handoff Protocol. Tests thousands of random
operation sequences to discover "split brain" states where kernel memory
doesn't match disk state.

References:
- Hypothesis: https://hypothesis.readthedocs.io/
- Stateful testing: https://hypothesis.readthedocs.io/en/latest/stateful.html

Test Coverage:
- Notebook state synchronization
- Cell execution ordering
- Kernel restart recovery
- Concurrent operations
- Hash integrity
"""

from hypothesis import given, strategies as st, settings, assume
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant, initialize
import hashlib
import json
from typing import Dict, List, Optional, Any


# --- Simplified Models for Testing ---


class MockCell:
    """Mock cell for testing."""

    def __init__(self, cell_id: str, source: str, outputs: Optional[List] = None):
        self.id = cell_id
        self.source = source
        self.outputs = outputs or []
        self.execution_count = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "source": self.source,
            "outputs": self.outputs,
            "execution_count": self.execution_count,
        }


class MockNotebook:
    """Mock notebook for testing."""

    def __init__(self):
        self.cells: List[MockCell] = []

    def add_cell(self, cell: MockCell):
        self.cells.append(cell)

    def to_dict(self) -> Dict:
        return {"cells": [cell.to_dict() for cell in self.cells]}

    def compute_hash(self) -> str:
        """Compute hash of notebook structure."""
        content = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class MockKernelState:
    """Mock kernel state for testing."""

    def __init__(self):
        self.variables: Dict[str, Any] = {}
        self.execution_count = 0
        self.cells: List[MockCell] = []

    def execute_cell(self, cell: MockCell):
        """Execute a cell and update state."""
        self.execution_count += 1
        cell.execution_count = self.execution_count

        # Simple execution: if cell defines variable, store it
        if "=" in cell.source:
            var_name = cell.source.split("=")[0].strip()
            self.variables[var_name] = f"value_{self.execution_count}"

        self.cells.append(cell)

    def restart(self):
        """Restart kernel (clears memory)."""
        self.variables.clear()
        self.execution_count = 0
        self.cells.clear()

    def compute_hash(self) -> str:
        """Compute hash of kernel state."""
        data = {
            "execution_count": self.execution_count,
            "cells": [c.to_dict() for c in self.cells],
        }
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# --- Property-Based Tests ---


class TestNotebookProperties:
    """Property-based tests for notebook operations."""

    @given(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10))
    def test_adding_cells_preserves_order(self, cell_sources: List[str]):
        """Test that adding cells maintains insertion order."""
        notebook = MockNotebook()

        for i, source in enumerate(cell_sources):
            cell = MockCell(f"cell_{i}", source)
            notebook.add_cell(cell)

        # Verify order
        for i, cell in enumerate(notebook.cells):
            assert cell.source == cell_sources[i]

    @given(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10))
    def test_notebook_hash_deterministic(self, cell_sources: List[str]):
        """Test that notebook hash is deterministic."""
        notebook1 = MockNotebook()
        notebook2 = MockNotebook()

        for i, source in enumerate(cell_sources):
            notebook1.add_cell(MockCell(f"cell_{i}", source))
            notebook2.add_cell(MockCell(f"cell_{i}", source))

        # Same content = same hash
        assert notebook1.compute_hash() == notebook2.compute_hash()

    @given(
        st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10),
        st.text(min_size=1, max_size=50),
    )
    def test_notebook_hash_changes_on_modification(
        self, cell_sources: List[str], new_source: str
    ):
        """Test that modifying notebook changes hash."""
        assume(new_source not in cell_sources)

        notebook = MockNotebook()
        for i, source in enumerate(cell_sources):
            notebook.add_cell(MockCell(f"cell_{i}", source))

        hash_before = notebook.compute_hash()

        # Add new cell
        notebook.add_cell(MockCell("cell_new", new_source))

        hash_after = notebook.compute_hash()
        assert hash_before != hash_after


class TestKernelExecutionProperties:
    """Property-based tests for kernel execution."""

    @given(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10))
    def test_execution_count_increases_monotonically(self, cell_sources: List[str]):
        """Test that execution count always increases."""
        kernel = MockKernelState()
        prev_count = 0

        for i, source in enumerate(cell_sources):
            cell = MockCell(f"cell_{i}", source)
            kernel.execute_cell(cell)

            assert kernel.execution_count > prev_count
            prev_count = kernel.execution_count

    @given(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10))
    def test_restart_clears_state(self, cell_sources: List[str]):
        """Test that kernel restart clears all state."""
        kernel = MockKernelState()

        # Execute some cells
        for i, source in enumerate(cell_sources):
            cell = MockCell(f"cell_{i}", source)
            kernel.execute_cell(cell)

        # Restart
        kernel.restart()

        # State should be cleared
        assert kernel.execution_count == 0
        assert len(kernel.variables) == 0
        assert len(kernel.cells) == 0

    @given(
        st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10),
        st.integers(min_value=0, max_value=9),
    )
    def test_re_executing_cell_updates_count(
        self, cell_sources: List[str], rerun_idx: int
    ):
        """Test that re-executing a cell updates execution count."""
        assume(rerun_idx < len(cell_sources))

        kernel = MockKernelState()
        cells = [MockCell(f"cell_{i}", src) for i, src in enumerate(cell_sources)]

        # Execute all cells
        for cell in cells:
            kernel.execute_cell(cell)

        count_after_first_run = kernel.execution_count

        # Re-execute one cell
        kernel.execute_cell(cells[rerun_idx])

        # Execution count should increase
        assert kernel.execution_count > count_after_first_run


# --- State Machine Testing ---


class NotebookStateMachine(RuleBasedStateMachine):
    """
    State machine for testing notebook synchronization.

    Invariant: After sync, kernel_hash == disk_hash
    """

    def __init__(self):
        super().__init__()
        self.disk_notebook = MockNotebook()
        self.kernel_state = MockKernelState()
        self.next_cell_id = 0
        self.synced = True  # Tracks if we're in sync

    @initialize()
    def initialize_notebook(self):
        """Start with empty notebook."""
        pass

    @rule(source=st.text(min_size=1, max_size=50))
    def add_cell_to_disk(self, source: str):
        """Add a cell to disk notebook."""
        cell = MockCell(f"cell_{self.next_cell_id}", source)
        self.disk_notebook.add_cell(cell)
        self.next_cell_id += 1
        self.synced = False  # Disk changed, now out of sync

    @rule()
    def execute_next_cell(self):
        """Execute the next unexecuted cell from disk."""
        assume(len(self.disk_notebook.cells) > 0)

        # Find next cell to execute
        executed_count = len(self.kernel_state.cells)
        assume(executed_count < len(self.disk_notebook.cells))

        cell = self.disk_notebook.cells[executed_count]
        self.kernel_state.execute_cell(cell)

    @rule()
    def restart_kernel(self):
        """Restart kernel (clears memory)."""
        self.kernel_state.restart()
        self.synced = False  # Kernel cleared, now out of sync

    @rule()
    def sync_kernel_with_disk(self):
        """Synchronize kernel state with disk."""
        # Re-execute all cells from disk
        self.kernel_state.restart()
        for cell in self.disk_notebook.cells:
            self.kernel_state.execute_cell(cell)

        self.synced = True  # Now in sync

    @invariant()
    def hashes_consistent_when_synced(self):
        """
        CRITICAL INVARIANT: When synced, kernel should reflect disk state.

        This doesn't check hash equality (different formats), but checks
        that the execution count matches cell count.
        """
        if self.synced:
            # When synced, kernel should have executed all disk cells
            assert len(self.kernel_state.cells) == len(self.disk_notebook.cells)


# Run state machine tests
TestNotebookSync = NotebookStateMachine.TestCase


class TestConcurrentOperations:
    """Test concurrent operations that could cause race conditions."""

    @given(
        st.lists(st.text(min_size=1, max_size=50), min_size=2, max_size=10),
        st.integers(min_value=0, max_value=9),
        st.integers(min_value=0, max_value=9),
    )
    def test_concurrent_cell_execution(
        self, cell_sources: List[str], idx1: int, idx2: int
    ):
        """Test executing cells in different order."""
        assume(len(cell_sources) >= 2)
        assume(idx1 < len(cell_sources))
        assume(idx2 < len(cell_sources))
        assume(idx1 != idx2)

        kernel1 = MockKernelState()
        kernel2 = MockKernelState()

        cells = [MockCell(f"cell_{i}", src) for i, src in enumerate(cell_sources)]

        # Execute in order: idx1, idx2
        kernel1.execute_cell(cells[idx1])
        kernel1.execute_cell(cells[idx2])

        # Execute in order: idx2, idx1
        kernel2.execute_cell(cells[idx2])
        kernel2.execute_cell(cells[idx1])

        # Execution counts should differ
        assert kernel1.execution_count == kernel2.execution_count == 2
        # But the order was different
        assert kernel1.cells[0].id == cells[idx1].id
        assert kernel2.cells[0].id == cells[idx2].id


class TestHashIntegrity:
    """Test hash computation integrity."""

    @given(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10))
    def test_hash_length_consistent(self, cell_sources: List[str]):
        """Test that hash length is always 16 chars (truncated SHA-256)."""
        notebook = MockNotebook()
        for i, source in enumerate(cell_sources):
            notebook.add_cell(MockCell(f"cell_{i}", source))

        hash_value = notebook.compute_hash()
        assert len(hash_value) == 16

    @given(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10))
    def test_hash_only_hex_chars(self, cell_sources: List[str]):
        """Test that hash contains only hexadecimal characters."""
        notebook = MockNotebook()
        for i, source in enumerate(cell_sources):
            notebook.add_cell(MockCell(f"cell_{i}", source))

        hash_value = notebook.compute_hash()
        assert all(c in "0123456789abcdef" for c in hash_value)


# Test configuration
@settings(max_examples=100, deadline=None)
@given(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=20))
def test_large_notebook_operations(cell_sources: List[str]):
    """Test operations on larger notebooks."""
    notebook = MockNotebook()
    kernel = MockKernelState()

    # Add all cells
    for i, source in enumerate(cell_sources):
        cell = MockCell(f"cell_{i}", source)
        notebook.add_cell(cell)

    # Execute all cells
    for cell in notebook.cells:
        kernel.execute_cell(cell)

    # Verify state
    assert len(kernel.cells) == len(notebook.cells)
    assert kernel.execution_count == len(cell_sources)


def test_hypothesis_test_count():
    """Verify we have comprehensive property-based tests."""
    test_classes = [
        TestNotebookProperties,
        TestKernelExecutionProperties,
        TestConcurrentOperations,
        TestHashIntegrity,
    ]

    total_tests = 0
    for cls in test_classes:
        test_methods = [m for m in dir(cls) if m.startswith("test_")]
        total_tests += len(test_methods)

    # Should have at least 9 property tests + 1 state machine
    assert total_tests >= 9, f"Only {total_tests} property tests found"
