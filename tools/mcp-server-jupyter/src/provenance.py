"""
Provenance Management for Git-Safe Execution Tracking

Stores cell execution metadata in .mcp/provenance.json sidecar file
instead of polluting notebook JSON with volatile data.
"""

import json
import os
from pathlib import Path
from typing import Dict, Set, Optional, Any
import tempfile


class ProvenanceManager:
    """
    Manages cell execution provenance in external sidecar file.
    
    Key design:
    - Metadata stored in .mcp/provenance.json (not in notebook JSON)
    - Keyed by Cell ID (stable across notebook edits)
    - Atomic writes to prevent corruption
    - Garbage collection for deleted cells
    """
    
    def __init__(self, notebook_path: str):
        """
        Initialize provenance manager for given notebook.
        
        Args:
            notebook_path: Path to the notebook file
        """
        self.notebook_path = Path(notebook_path)
        self.sidecar_dir = self.notebook_path.parent / ".mcp"
        self.sidecar_path = self.sidecar_dir / "provenance.json"
        
        # Ensure .mcp directory exists
        self.sidecar_dir.mkdir(exist_ok=True)
    
    def _load_sidecar(self) -> Dict[str, Dict[str, Any]]:
        """
        Load provenance data from sidecar file.
        
        Returns:
            Dict mapping Cell ID -> metadata dict
        """
        if not self.sidecar_path.exists():
            return {}
        
        try:
            with open(self.sidecar_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # Corrupted or unreadable - start fresh
            return {}
    
    def _save_sidecar(self, data: Dict[str, Dict[str, Any]]) -> None:
        """
        Save provenance data atomically to sidecar file.
        
        Args:
            data: Dict mapping Cell ID -> metadata dict
        """
        # Atomic write using temp file + os.replace()
        temp_fd, temp_path = tempfile.mkstemp(
            dir=self.sidecar_dir,
            prefix=".provenance.",
            suffix=".tmp"
        )
        
        try:
            # Write to temp file
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, sort_keys=True)
            
            # Atomic rename
            os.replace(temp_path, str(self.sidecar_path))
            
        except Exception:
            # Clean up temp file on any error
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass
            raise
    
    def save_execution(self, cell_id: str, metadata: Dict[str, Any]) -> None:
        """
        Save execution metadata for a cell.
        
        Args:
            cell_id: Cell ID (stable UUID)
            metadata: Execution metadata dict (timestamp, env info, etc.)
        """
        data = self._load_sidecar()
        data[cell_id] = metadata
        self._save_sidecar(data)
    
    def get_execution(self, cell_id: str) -> Optional[Dict[str, Any]]:
        """
        Get execution metadata for a cell.
        
        Args:
            cell_id: Cell ID
        
        Returns:
            Metadata dict if found, None otherwise
        """
        data = self._load_sidecar()
        return data.get(cell_id)
    
    def delete_execution(self, cell_id: str) -> bool:
        """
        Delete execution metadata for a cell.
        
        Args:
            cell_id: Cell ID
        
        Returns:
            True if deleted, False if not found
        """
        data = self._load_sidecar()
        if cell_id in data:
            del data[cell_id]
            self._save_sidecar(data)
            return True
        return False
    
    def garbage_collect(self, valid_cell_ids: Set[str]) -> int:
        """
        Remove provenance entries for deleted cells.
        
        Should be called periodically (e.g., in get_notebook_outline)
        to clean up orphaned metadata.
        
        Args:
            valid_cell_ids: Set of Cell IDs currently in notebook
        
        Returns:
            Number of entries removed
        """
        data = self._load_sidecar()
        original_count = len(data)
        
        # Keep only entries for cells that still exist
        data = {cid: meta for cid, meta in data.items() if cid in valid_cell_ids}
        
        if len(data) < original_count:
            self._save_sidecar(data)
        
        return original_count - len(data)
    
    def get_all_entries(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all provenance entries.
        
        Returns:
            Dict mapping Cell ID -> metadata
        """
        return self._load_sidecar()
    
    def clear_all(self) -> None:
        """
        Clear all provenance entries.
        
        Useful for testing or manual cleanup.
        """
        self._save_sidecar({})
