"""
Sync tools for MCP Jupyter Server.

Provides state synchronization tools for detecting and resolving
out-of-sync conditions between kernel state and notebook content on disk.
"""

import json
from typing import Dict, Optional

import nbformat

from src import utils
from src.models import DetectSyncNeededArgs, SyncStateFromDiskArgs
from src.validation import validated_tool
from src.observability import get_logger

logger = get_logger(__name__)


def register_sync_tools(mcp, session_manager):
    """Register sync-related tools with the MCP server."""

    @mcp.tool()
    @validated_tool(DetectSyncNeededArgs)
    async def detect_sync_needed(
        notebook_path: str, buffer_hashes: Optional[Dict[int, str]] = None
    ):
        """
        [HANDOFF PROTOCOL] Detect if kernel state is out of sync with disk or VS Code buffer.

        **Purpose**: Before the agent starts work, check if a human has modified the notebook
        since the last agent execution.

        **How It Works**:
        1. If buffer_hashes provided (from VS Code client), use those as source of truth.
        2. Otherwise, reads notebook from disk.
        3. Calculates SHA-256 hash of each cell's content.
        4. Compares with 'execution_hash' stored in cell metadata.
        5. If hashes mismatch, sync is required.

        Args:
            notebook_path: Path to notebook
            buffer_hashes: Optional dict of {cell_index: hash} from VS Code buffer (source of truth)

        Returns:
            JSON with:
            - sync_needed: boolean
            - reason: Description of mismatch
            - changed_cells: List of cell indices that changed
        """
        from pathlib import Path

        str(Path(notebook_path).resolve())
        session = session_manager.get_session(notebook_path)

        if not session:
            return json.dumps(
                {
                    "sync_needed": True,
                    "reason": "no_active_kernel",
                    "recommendation": "Call start_kernel() first",
                }
            )

        # If buffer_hashes provided by client, use those as source of truth
        # Otherwise, read from disk (legacy behavior)
        changed_cells = []

        if buffer_hashes is not None:
            # Client-provided hashes (VS Code buffer state) - this is the source of truth
            for idx, buffer_hash in buffer_hashes.items():
                # Compare against kernel execution history
                exec_history = session.get("execution_history", {})
                kernel_hash = exec_history.get(idx)

                if not kernel_hash or buffer_hash != kernel_hash:
                    changed_cells.append(idx)
        else:
            # Legacy: Read notebook from disk
            try:
                nb = nbformat.read(notebook_path, as_version=4)
            except Exception as e:
                return json.dumps({"error": f"Failed to read notebook: {e}"})

            for idx, cell in enumerate(nb.cells):
                if cell.cell_type == "code":
                    current_hash = utils.get_cell_hash(cell.source)
                    # Check both new 'mcp' and legacy 'mcp_trace' metadata locations
                    mcp_meta = cell.metadata.get("mcp", {}) or cell.metadata.get(
                        "mcp_trace", {}
                    )
                    last_hash = mcp_meta.get("execution_hash")

                    # If no hash exists (never executed by agent) or hash mismatch (content changed)
                    if not last_hash or current_hash != last_hash:
                        changed_cells.append(idx)

        sync_needed = len(changed_cells) > 0

        return json.dumps(
            {
                "sync_needed": sync_needed,
                "reason": (
                    f"Content mismatch in {len(changed_cells)} cells"
                    if sync_needed
                    else "Content matches execution history"
                ),
                "changed_cells": changed_cells,
                "recommendation": "sync_state_from_disk" if sync_needed else "proceed",
                "sync_strategy": "full",
            },
            indent=2,
        )

    @mcp.tool()
    @validated_tool(SyncStateFromDiskArgs)
    async def sync_state_from_disk(notebook_path: str, strategy: str = "minimal_append"):
        """
        [HANDOFF PROTOCOL] Synchronize kernel state with disk after human intervention.

        Defensive default: "minimal_append" is now the default strategy. This will only
        execute cells that exist in the file but have never been executed in the kernel.
        It refuses to auto-execute cells whose content changed unless the caller explicitly
        requests a stronger strategy (e.g., "force" / "full" / "incremental").

        **When to Use**:
        - Agent resumes work after human editing session
        - Agent detects unexpected notebook structure (new cells added)
        - After switching from "Human Mode" to "Agent Mode" in VS Code extension

        **Strategy**:
        - "minimal_append" (default): Only executes cells that have never been executed in the kernel history.
        - "smart": DAG-based minimal re-execution (may rerun modified cells and dependents) — opt-in.
        - "incremental": Re-executes from first changed cell to end (linear forward sync)
        - "full": Re-executes ALL code cells from scratch (safest but slowest)

        Safety behavior: If a modified upstream cell is detected under "minimal_append",
        the tool returns an error/warning requiring explicit consent to proceed with a
        riskier strategy (e.g., call with strategy="force" or strategy="full").

        Args:
            notebook_path: Path to the notebook file
            strategy: "minimal_append" | "smart" | "incremental" | "full" | "force"

        Returns:
            JSON with:
            - cells_synced: Number of cells re-executed
            - execution_ids: List of execution IDs for tracking
            - sync_duration_estimate: Estimated time to complete (based on queue size)
            - rerun_reason: Explanation of why each cell was rerun

        Agent Workflow Example:
            # 1. Agent detects notebook changed on disk
            outline = get_notebook_outline(path)
            if len(outline['cells']) > session.last_known_cell_count:
                # 2. Minimal append will only run new cells
                result = sync_state_from_disk(path)  # minimal_append by default
                print(f"Synced {result['cells_synced']} cells (skipped {result['cells_skipped']} clean cells)")

            # 3. If content was modified, the tool will return an error recommending
            #    the agent request an explicit opt-in to rerun changed cells.
        """
        from src import dag_executor

        session = session_manager.get_session(notebook_path)
        if not session:
            return json.dumps(
                {
                    "error": "No active kernel. Call start_kernel first.",
                    "hint": "The kernel must be running to sync state.",
                }
            )

        # Read notebook from disk
        try:
            nb = nbformat.read(notebook_path, as_version=4)
        except Exception as e:
            return json.dumps(
                {
                    "error": f"Failed to read notebook from disk: {e}",
                    "notebook_path": notebook_path,
                }
            )

        exec_ids = []
        strategy_used = strategy
        rerun_reasons = {}

        if strategy == "full":
            # Full sync: rerun everything
            cells_to_run = list(range(len(nb.cells)))
            for idx in cells_to_run:
                if nb.cells[idx].cell_type == "code":
                    rerun_reasons[idx] = "full_sync_requested"

        elif strategy == "minimal_append":
            # Only execute cells that have never been executed. If any modified
            # upstream cells are detected, refuse to proceed and return a warning
            # requiring an explicit stronger strategy.
            executed_indices = session.get("executed_indices", set())
            modified_cells = []
            new_cells = []

            for idx, cell in enumerate(nb.cells):
                if cell.cell_type != "code":
                    continue
                if idx not in executed_indices:
                    new_cells.append(idx)
                    rerun_reasons[idx] = "never_executed"
                else:
                    # Check if content has changed since last execution
                    current_hash = utils.get_cell_hash(cell.source)
                    mcp_meta = cell.metadata.get("mcp", {}) or cell.metadata.get(
                        "mcp_trace", {}
                    )
                    last_hash = mcp_meta.get("execution_hash")
                    if last_hash and current_hash != last_hash:
                        modified_cells.append(idx)

            if modified_cells:
                # Defensive behaviour - surface an explicit warning instead of auto-running
                return json.dumps(
                    {
                        "error": "upstream_modified",
                        "message": (
                            f"Upstream cell(s) modified at indices {modified_cells}. Re-running them may cause side effects. "
                            "Call sync_state_from_disk(strategy='force' or 'full') to confirm."
                        ),
                        "modified_cells": modified_cells,
                        "new_cells_detected": new_cells,
                    },
                    indent=2,
                )

            cells_to_run = new_cells

        elif strategy == "smart":
            # DAG-based minimal sync

            # Find changed cells
            changed_cells = set()
            executed_indices = session.get("executed_indices", set())

            for idx, cell in enumerate(nb.cells):
                if cell.cell_type == "code":
                    # Check if never executed OR content changed
                    if idx not in executed_indices:
                        changed_cells.add(idx)
                        rerun_reasons[idx] = "never_executed"
                        continue

                    current_hash = utils.get_cell_hash(cell.source)
                    mcp_meta = cell.metadata.get("mcp", {}) or cell.metadata.get(
                        "mcp_trace", {}
                    )
                    last_hash = mcp_meta.get("execution_hash")

                    if not last_hash or current_hash != last_hash:
                        changed_cells.add(idx)
                        rerun_reasons[idx] = "content_modified"

            if changed_cells:
                # Build dependency graph and compute affected cells
                cells_source = [
                    cell.source if cell.cell_type == "code" else "" for cell in nb.cells
                ]
                try:
                    cells_to_run = dag_executor.get_minimal_rerun_set(
                        cells_source, changed_cells
                    )
                    # Mark dependent cells
                    for idx in cells_to_run:
                        if idx not in rerun_reasons:
                            rerun_reasons[idx] = "dependent_on_changed_cell"
                except Exception as e:
                    logger.warning(
                        f"DAG analysis failed, falling back to incremental sync: {e}"
                    )
                    # Fallback to incremental
                    first_changed = min(changed_cells)
                    cells_to_run = list(range(first_changed, len(nb.cells)))
                    strategy_used = "incremental_fallback"
                    for idx in cells_to_run:
                        if idx not in rerun_reasons:
                            rerun_reasons[idx] = "incremental_fallback"
            else:
                cells_to_run = []
                strategy_used = "smart_skipped_all"

        else:  # "incremental"
            # Incremental sync: find first dirty cell, rerun from there
            first_dirty_idx = -1
            executed_indices = session.get("executed_indices", set())

            for idx, cell in enumerate(nb.cells):
                if cell.cell_type == "code":
                    if idx not in executed_indices:
                        first_dirty_idx = idx
                        rerun_reasons[idx] = "never_executed"
                        break

                    current_hash = utils.get_cell_hash(cell.source)
                    mcp_meta = cell.metadata.get("mcp", {}) or cell.metadata.get(
                        "mcp_trace", {}
                    )
                    last_hash = mcp_meta.get("execution_hash")

                    if not last_hash or current_hash != last_hash:
                        first_dirty_idx = idx
                        rerun_reasons[idx] = "content_modified"
                        break

            if first_dirty_idx != -1:
                cells_to_run = list(range(first_dirty_idx, len(nb.cells)))
                for idx in cells_to_run:
                    if idx not in rerun_reasons:
                        rerun_reasons[idx] = "incremental_cascade"
            else:
                cells_to_run = []
                strategy_used = "incremental_skipped_all"

        # Execute determined cells
        queue_full = False
        for idx in cells_to_run:
            if idx < len(nb.cells) and nb.cells[idx].cell_type == "code":
                cell = nb.cells[idx]
                try:
                    exec_id = await session_manager.execute_cell_async(
                        notebook_path, idx, cell.source
                    )
                    if exec_id:
                        exec_ids.append(
                            {
                                "cell_index": idx,
                                "exec_id": exec_id,
                                "reason": rerun_reasons.get(idx, "unknown"),
                            }
                        )
                except RuntimeError:
                    # Queue is full, stop queuing more
                    queue_full = True
                    logger.warning(
                        f"[BACKPRESSURE] Queue full during sync_state_from_disk at cell {idx}"
                    )
                    break

        # Calculate metrics
        queue_size = (
            session["execution_queue"].qsize() if "execution_queue" in session else 0
        )
        estimate_seconds = len(exec_ids) * 2
        total_code_cells = sum(1 for c in nb.cells if c.cell_type == "code")
        skipped_cells = total_code_cells - len(exec_ids)

        response = {
            "status": "syncing" if not queue_full else "partial",
            "message": f"Queued {len(exec_ids)} cells for state synchronization",
            "cells_synced": len(exec_ids),
            "cells_skipped": skipped_cells,
            "total_code_cells": total_code_cells,
            "execution_ids": exec_ids,
            "queue_size": queue_size + len(exec_ids),
            "estimated_duration_seconds": estimate_seconds,
            "strategy_used": strategy_used,
            "hint": "Use get_execution_status() to monitor progress.",
        }

        if queue_full:
            response["queue_full"] = True
            response["retry_after_seconds"] = 5

        return json.dumps(response, indent=2)
