"""
DAG (Directed Acyclic Graph) Execution Engine

Analyzes variable dependencies between cells to enable smart re-execution.
Only re-runs cells that depend on changed variables, avoiding wasteful computation.

Example:
    Cell 0: x = load_data()      # 30 seconds
    Cell 1: y = expensive(x)      # 10 minutes!
    Cell 2: plot(y)               # 1 second
    Cell 3: z = other_data()      # Independent
    Cell 4: summary(z)            # Uses z only
    
    If Cell 0 changes (x modified):
        Traditional: Re-run 0, 1, 2, 3, 4 (10+ minutes)
        DAG-aware: Re-run 0, 1, 2 only (10 minutes)
        Skips: 3, 4 (don't use x)
"""

import ast
from typing import Dict, List, Set, Union
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class CellDependencies:
    """Tracks what a cell defines and what it uses."""

    cell_index: int
    defines: Set[str]  # Variables this cell assigns to
    uses: Set[str]  # Variables this cell reads
    source: str  # Cell source code


class VariableVisitor(ast.NodeVisitor):
    """AST visitor to extract variable definitions and usages."""

    def __init__(self):
        self.defines: Set[str] = set()
        self.uses: Set[str] = set()
        self._in_assignment = False

    def visit_Name(self, node):
        """Track variable references."""
        if isinstance(node.ctx, ast.Store):
            # Variable being assigned to
            self.defines.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            # Variable being read
            self.uses.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        """Handle attribute access (e.g., df.columns)."""
        # For df.columns, track 'df' as used
        if isinstance(node.value, ast.Name):
            self.uses.add(node.value.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        """Track function definitions."""
        self.defines.add(node.name)
        # Don't traverse into function body (local scope)
        # But do track decorators and default args
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)

    def visit_ClassDef(self, node):
        """Track class definitions."""
        self.defines.add(node.name)
        # Similar to functions, don't traverse body


def analyze_cell(source: str, cell_index: int) -> CellDependencies:
    """
    Parse a cell's source code and extract dependencies.

    Args:
        source: Python source code
        cell_index: Cell position in notebook

    Returns:
        CellDependencies with defines/uses sets
    """
    try:
        tree = ast.parse(source)
        visitor = VariableVisitor()
        visitor.visit(tree)

        # Remove built-ins and imports from 'uses'
        # (they don't create cell dependencies)
        builtins = {
            "print",
            "len",
            "range",
            "str",
            "int",
            "float",
            "list",
            "dict",
            "set",
            "tuple",
            "abs",
            "sum",
            "max",
            "min",
        }

        uses_filtered = visitor.uses - visitor.defines - builtins

        return CellDependencies(
            cell_index=cell_index,
            defines=visitor.defines,
            uses=uses_filtered,
            source=source,
        )
    except SyntaxError as e:
        logger.warning(f"Syntax error in cell {cell_index}: {e}")
        # Return empty dependencies for cells with syntax errors
        return CellDependencies(
            cell_index=cell_index, defines=set(), uses=set(), source=source
        )


def build_dependency_graph(cells: List[CellDependencies]) -> Dict[int, Set[int]]:
    """
    Build a directed graph of cell dependencies.

    Returns:
        Dict mapping cell_index -> set of cells it depends on

    Example:
        {
            0: set(),        # Cell 0 depends on nothing
            1: {0},          # Cell 1 depends on cell 0
            2: {1},          # Cell 2 depends on cell 1
            3: set(),        # Cell 3 is independent
            4: {3}           # Cell 4 depends on cell 3
        }
    """
    graph: Dict[int, Set[int]] = {cell.cell_index: set() for cell in cells}

    # Build variable -> defining cell mapping
    var_source: Dict[str, int] = {}
    for cell in cells:
        for var in cell.defines:
            var_source[var] = cell.cell_index

    # For each cell, find which cells it depends on
    for cell in cells:
        for var in cell.uses:
            if var in var_source:
                source_cell = var_source[var]
                if source_cell != cell.cell_index:  # Don't depend on self
                    graph[cell.cell_index].add(source_cell)

    return graph


def compute_affected_cells(
    changed_cell: int, changed_variables: Set[str], cells: List[CellDependencies]
) -> Set[int]:
    """
    Compute which cells need re-execution after a change.

    Args:
        changed_cell: Index of modified cell
        changed_variables: Variables that were redefined
        cells: All cell dependencies

    Returns:
        Set of cell indices that must be re-executed
    """
    # Start with the changed cell itself
    affected = {changed_cell}

    # Build variable ownership map
    var_to_cell = {}
    for cell in cells:
        for var in cell.defines:
            var_to_cell[var] = cell.cell_index

    # Track which variables have been modified by cascade
    dirty_vars = set(changed_variables)

    # BFS to find downstream dependencies
    queue = [changed_cell]
    visited = {changed_cell}

    while queue:
        current = queue.pop(0)
        current_cell = cells[current]

        # When a cell is rerun, all its outputs become dirty
        dirty_vars.update(current_cell.defines)

        # Find cells that use any dirty variables
        for cell in cells[current + 1 :]:  # Only look forward (execution order matters)
            if cell.cell_index in visited:
                continue

            # Does this cell use any dirty variables?
            if dirty_vars & cell.uses:
                affected.add(cell.cell_index)
                visited.add(cell.cell_index)
                queue.append(cell.cell_index)

    return affected


def get_minimal_rerun_set(
    notebook_cells: Union[List[str], List[Dict]],
    changed_cell_indices: Union[int, Set[int]],
) -> Set[int]:
    """
    Main entry point: Get minimal set of cells to re-run.

    Args:
        notebook_cells: List of code strings OR dicts with 'source' and 'cell_type' keys
        changed_cell_indices: Which cell(s) were modified (int or Set[int])

    Returns:
        Set of cell indices that should be re-executed
    """
    # Normalize changed_cell_indices to set
    if isinstance(changed_cell_indices, int):
        changed_cells = {changed_cell_indices}
    else:
        changed_cells = set(changed_cell_indices)

    if not changed_cells:
        return set()

    # Extract code cells and build dependencies
    dependencies = []

    for i, cell in enumerate(notebook_cells):
        # Handle both string arrays and cell objects
        if isinstance(cell, str):
            source = cell
        elif isinstance(cell, dict):
            if cell.get("cell_type") != "code":
                continue
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
        else:
            logger.warning(f"Unknown cell type at index {i}: {type(cell)}")
            continue

        dependencies.append(analyze_cell(source, i))

    # Build dependency graph
    build_dependency_graph(dependencies)

    # Compute all affected cells
    affected = set()
    for changed_idx in changed_cells:
        if changed_idx < len(dependencies):
            changed_dep = dependencies[changed_idx]
            newly_affected = compute_affected_cells(
                changed_idx, changed_dep.defines, dependencies
            )
            affected.update(newly_affected)
        else:
            logger.warning(f"Invalid cell index: {changed_idx}")
            # Fallback: rerun from changed index to end
            affected.update(range(changed_idx, len(notebook_cells)))

    logger.info(
        f"Smart sync: {len(changed_cells)} cell(s) changed. "
        f"Re-running {len(affected)} cells instead of full sync"
    )

    return affected


# Example usage for testing
if __name__ == "__main__":
    # Test case
    test_cells = [
        {"cell_type": "code", "source": "x = load_data()"},
        {"cell_type": "code", "source": "y = expensive_computation(x)"},
        {"cell_type": "code", "source": "plot(y)"},
        {"cell_type": "code", "source": "z = other_data()"},
        {"cell_type": "code", "source": "summary(z)"},
    ]

    # If cell 0 changes (x redefined)
    affected = get_minimal_rerun_set(test_cells, 0)
    print(f"Cells to rerun: {affected}")  # Should be {0, 1, 2} (skips 3, 4)

    # If cell 3 changes (z redefined)
    affected = get_minimal_rerun_set(test_cells, 3)
    print(f"Cells to rerun: {affected}")  # Should be {3, 4} (skips 0, 1, 2)
