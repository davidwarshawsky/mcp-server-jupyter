"""
Persistence Layer (P0 FIX: State Amnesia)

SQLite-backed job queue and asset lease manager.
Ensures that if the container crashes, queued tasks and asset references survive.

This module replaces the volatile asyncio.Queue with a durable, disk-backed queue
that provides:
1. Task Durability: If the server dies, pending tasks are restored on restart
2. Asset Leasing: Assets have explicit "last seen" timestamps; only delete if expired AND unreferenced
3. ACID Semantics: All changes are committed to disk immediately
"""

import sqlite3
import json
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class PersistenceManager:
    """
    SQLite-backed job queue and state manager.
    Prevents data loss on process crash.
    
    Features:
    - PENDING tasks survive server restarts
    - Assets tracked with "lease" times (renewal on notebook save/update)
    - ACID transactions ensure no partial writes
    """

    def __init__(self, db_path: Path):
        """Initialize or open the persistence database.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"[PERSISTENCE] Initialized SQLite at {self.db_path}")

    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for reliability
            
            # Execution Queue Table
            # Tracks all submitted cell executions (pending, running, completed)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_queue (
                    task_id TEXT PRIMARY KEY,
                    notebook_path TEXT NOT NULL,
                    cell_index INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'completed', 'failed')),
                    created_at TIMESTAMP NOT NULL,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    execution_count INTEGER,
                    outputs_json TEXT,
                    retries INTEGER DEFAULT 0
                )
            """)
            
            # Asset Leases Table
            # Tracks which assets are "alive" and when they were last referenced
            # Only delete assets if lease has expired AND they're not in the notebook
            conn.execute("""
                CREATE TABLE IF NOT EXISTS asset_leases (
                    asset_path TEXT PRIMARY KEY,
                    notebook_path TEXT NOT NULL,
                    last_seen TIMESTAMP NOT NULL,
                    lease_expires TIMESTAMP NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
            """)
            
            # Indexes for fast queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_eq_notebook ON execution_queue(notebook_path, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_eq_status ON execution_queue(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_al_notebook ON asset_leases(notebook_path)")
            
            conn.commit()

    def enqueue_execution(
        self,
        notebook_path: str,
        cell_index: int,
        code: str,
        task_id: Optional[str] = None,
    ) -> str:
        """
        Persist a pending execution task to disk.
        
        [STATE AMNESIA FIX] This ensures that if the server crashes before
        the task is processed, it will be restored from the database on restart.
        
        Args:
            notebook_path: Path to the notebook
            cell_index: Index of the cell
            code: Code to execute
            task_id: Optional task ID (generated if not provided)
            
        Returns:
            The task ID (newly generated or provided)
        """
        if not task_id:
            task_id = str(uuid.uuid4())
        
        now = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO execution_queue 
                (task_id, notebook_path, cell_index, code, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (task_id, notebook_path, cell_index, code, now),
            )
            conn.commit()
        
        logger.debug(f"[PERSISTENCE] Enqueued task {task_id} for {notebook_path}:{cell_index}")
        return task_id

    def get_pending_tasks(self, notebook_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve all pending tasks, optionally filtered by notebook.
        
        [STATE AMNESIA FIX] On server startup, call this with notebook_path=None
        to retrieve ALL pending tasks from ALL notebooks and resume execution.
        
        Args:
            notebook_path: Optional notebook path to filter by
            
        Returns:
            List of task dicts (task_id, notebook_path, cell_index, code, etc.)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            if notebook_path:
                cursor = conn.execute(
                    """
                    SELECT * FROM execution_queue 
                    WHERE notebook_path = ? AND status = 'pending' 
                    ORDER BY created_at ASC
                    """,
                    (notebook_path,),
                )
            else:
                # Return ALL pending tasks across all notebooks (for startup recovery)
                cursor = conn.execute(
                    """
                    SELECT * FROM execution_queue 
                    WHERE status = 'pending' 
                    ORDER BY created_at ASC
                    """,
                )
            
            return [dict(row) for row in cursor.fetchall()]

    def mark_task_running(self, task_id: str):
        """Mark a task as currently running."""
        now = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE execution_queue SET status = 'running', started_at = ? WHERE task_id = ?",
                (now, task_id),
            )
            conn.commit()

    def mark_task_complete(self, task_id: str, outputs_json: Optional[str] = None, execution_count: Optional[int] = None):
        """
        [OUTPUT REHYDRATION] Mark a task as completed and optionally save outputs.
        
        Args:
            task_id: The execution task ID
            outputs_json: JSON-serialized cell outputs (from Jupyter kernel)
            execution_count: The execution count from the kernel
        """
        now = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            if outputs_json is not None or execution_count is not None:
                # Update with outputs and execution count
                update_clause = "UPDATE execution_queue SET status = 'completed', completed_at = ?"
                params = [now, task_id]
                
                if outputs_json is not None:
                    update_clause += ", outputs_json = ?"
                    params.insert(1, outputs_json)
                
                if execution_count is not None:
                    update_clause += ", execution_count = ?"
                    params.insert(1 if outputs_json is None else 2, execution_count)
                
                update_clause += " WHERE task_id = ?"
                conn.execute(update_clause, params)
            else:
                # Backwards compatible: just mark complete
                conn.execute(
                    "UPDATE execution_queue SET status = 'completed', completed_at = ? WHERE task_id = ?",
                    (now, task_id),
                )
            conn.commit()

    def mark_task_failed(self, task_id: str, error: str):
        """Mark a task as failed with an error message."""
        now = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE execution_queue SET status = 'failed', error_message = ?, completed_at = ? WHERE task_id = ?",
                (error, now, task_id),
            )
            conn.commit()

    def renew_asset_lease(
        self,
        asset_path: str,
        notebook_path: str,
        lease_duration_hours: int = 24,
    ):
        """
        Renew or create an asset lease.
        
        [ZOMBIE GC FIX] When the client saves the notebook (or a cell generates
        a new asset), renew the lease. Assets are only deleted if:
        1. Lease has expired (default 24 hours), AND
        2. Asset is not referenced in the notebook
        
        Args:
            asset_path: Path to the asset file
            notebook_path: Notebook that references it
            lease_duration_hours: How long to keep the asset (default 24h)
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=lease_duration_hours)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO asset_leases 
                (asset_path, notebook_path, last_seen, lease_expires, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (asset_path, notebook_path, now.isoformat(), expires.isoformat(), now.isoformat()),
            )
            conn.commit()
        
        logger.debug(f"[PERSISTENCE] Renewed asset lease: {asset_path}")

    def renew_lease(
        self,
        asset_path: str,
        notebook_path: str,
        ttl_hours: int = 24,
    ):
        """Alias for renew_asset_lease() for API compatibility."""
        return self.renew_asset_lease(asset_path, notebook_path, ttl_hours)

    def get_expired_assets(self) -> List[str]:
        """
        Get list of assets whose leases have expired.
        
        [ZOMBIE GC FIX] Only call prune_unused_assets() for these assets.
        Assets with valid leases are NEVER deleted, even if not in the notebook.
        
        Returns:
            List of asset paths with expired leases
        """
        now = datetime.now(timezone.utc).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT asset_path FROM asset_leases WHERE lease_expires < ?",
                (now,),
            )
            return [row[0] for row in cursor.fetchall()]

    def delete_expired_asset_lease(self, asset_path: str):
        """Remove an asset lease entry after deletion."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM asset_leases WHERE asset_path = ?", (asset_path,))
            conn.commit()

    def get_task_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific task by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM execution_queue WHERE task_id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def cleanup_completed_tasks(self, age_hours: int = 24):
        """
        Delete completed tasks older than age_hours.
        
        Call this periodically to keep the DB from growing indefinitely.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM execution_queue WHERE status = 'completed' AND completed_at < ?",
                (cutoff.isoformat(),),
            )
            conn.commit()

    def get_stats(self) -> Dict[str, int]:
        """Get database statistics (pending tasks, completed, etc.)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            stats = {}
            for status in ['pending', 'running', 'completed', 'failed']:
                cursor = conn.execute(
                    "SELECT COUNT(*) as count FROM execution_queue WHERE status = ?",
                    (status,),
                )
                stats[status] = cursor.fetchone()['count']
            
            cursor = conn.execute("SELECT COUNT(*) as count FROM asset_leases")
            stats['active_leases'] = cursor.fetchone()['count']
            
            return stats
