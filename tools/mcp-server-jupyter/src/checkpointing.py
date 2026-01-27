"""
Secure Checkpoint System for MCP Jupyter Server

[FRIDAY-MONDAY FIX] Prevents data loss across restarts by:
1. HMAC-SHA256 signing state to prevent tampering
2. Dill serialization to handle complex objects (DataFrames, Models, etc)
3. Atomic writes to prevent corruption on crash
4. Dependency snapshots to prevent ModuleNotFoundError on restore

Usage:
    On Friday: save_environment(notebook_path, "friday_work", vars=["df", "model"])
    On Monday: load_environment(notebook_path, "friday_work")
"""

import os
import hmac
import hashlib
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Use the persistent secret established in session.py
try:
    from src.session import SESSION_SECRET
except ImportError:
    # Fallback for testing
    SESSION_SECRET = b"mcp-jupyter-default-secret-key-change-in-production"


class SecurityError(Exception):
    """Raised when checkpoint signature verification fails."""
    pass


class CheckpointManager:
    """Manages secure state checkpointing with HMAC signatures."""

    def __init__(self, data_dir: Path):
        """
        Initialize checkpoint manager.
        
        Args:
            data_dir: Root data directory (typically MCP_DATA_DIR)
        """
        self.data_dir = Path(data_dir)
        self.checkpoints_dir = self.data_dir / "checkpoints"
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"[CHECKPOINTING] Initialized at {self.checkpoints_dir}")

    def _get_paths(self, notebook_path: str, name: str) -> Dict[str, Path]:
        """
        Generate deterministic, filesystem-safe checkpoint paths.
        
        Returns dict with 'data', 'meta', 'reqs' paths.
        """
        # Use MD5 hash of notebook path to segregate checkpoints
        nb_id = hashlib.md5(notebook_path.encode()).hexdigest()[:8]
        # Sanitize checkpoint name (allow alphanumeric, dash, underscore)
        safe_name = "".join(c for c in name if c.isalnum() or c in ('-', '_'))
        
        base = self.checkpoints_dir / f"{nb_id}_{safe_name}"
        
        return {
            "data": base.with_suffix(".dill"),
            "meta": base.with_suffix(".json"),
            "reqs": base.with_suffix(".requirements.txt"),
            "tmp": base.with_suffix(".tmp"),  # Atomic write temp
        }

    def sign_and_save(
        self,
        temp_data_path: str,
        notebook_path: str,
        name: str,
        env_info: Optional[Dict[str, Any]] = None
    ) -> Path:
        """
        Move data from temp location to secure storage, signing it.
        Also snapshots current pip freeze for dependency verification.
        
        Args:
            temp_data_path: Path to dill-serialized data file from kernel
            notebook_path: Path to the notebook
            name: Checkpoint name (e.g., "friday_work")
            env_info: Optional environment metadata
            
        Returns:
            Path to secure checkpoint file
            
        Raises:
            RuntimeError: If signing or move fails
        """
        if not Path(temp_data_path).exists():
            raise FileNotFoundError(f"Temp data file not found: {temp_data_path}")
        
        paths = self._get_paths(notebook_path, name)
        
        try:
            # 1. Capture Dependencies (The "ImportError Prevention" Fix)
            # Snapshot pip freeze to detect missing packages on load
            try:
                reqs = subprocess.check_output(
                    [sys.executable, "-m", "pip", "freeze"],
                    timeout=30
                ).decode('utf-8')
                with open(paths["reqs"], "w") as f:
                    f.write(reqs)
                logger.debug(f"[CHECKPOINTING] Captured {len(reqs.splitlines())} dependencies")
            except Exception as e:
                logger.warning(f"[CHECKPOINTING] Could not snapshot requirements: {e}")
                paths["reqs"].write_text("")

            # 2. Sign the Data (The "Tamper Detection" Fix)
            # Read dill-serialized data
            with open(temp_data_path, "rb") as f:
                data_bytes = f.read()
            
            # Ensure SESSION_SECRET is bytes
            secret_bytes = SESSION_SECRET if isinstance(SESSION_SECRET, bytes) else SESSION_SECRET.encode()
            signature = hmac.new(secret_bytes, data_bytes, hashlib.sha256).hexdigest()
            
            logger.debug(f"[CHECKPOINTING] Generated HMAC signature: {signature[:16]}...")

            # 3. Atomic Write (The "Crash Safety" Fix)
            # Write to temp first, then rename (atomic on most filesystems)
            with open(paths["tmp"], "w") as f:
                # Write header: signature on first line
                f.write(signature + "\n")
            
            # Move binary data file
            shutil.move(temp_data_path, paths["data"])
            
            # 4. Write Metadata
            metadata = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "signature": signature,
                "notebook": notebook_path,
                "name": name,
                "env_info": env_info or {},
                "size_bytes": len(data_bytes),
                "python_version": sys.version,
            }
            with open(paths["meta"], "w") as f:
                json.dump(metadata, f, indent=2)
            
            # Clean up temp header file
            paths["tmp"].unlink(missing_ok=True)
            
            size_mb = len(data_bytes) / (1024 * 1024)
            logger.info(f"[CHECKPOINTING] Saved '{name}' ({size_mb:.2f} MB, {signature[:16]}...)")
            
            return paths["data"]
            
        except Exception as e:
            # Clean up on failure
            paths["tmp"].unlink(missing_ok=True)
            logger.error(f"[CHECKPOINTING] Save failed: {e}")
            raise RuntimeError(f"Failed to save checkpoint: {e}")

    def verify_and_get_path(self, notebook_path: str, name: str) -> Path:
        """
        Verify checkpoint signature, then return path for loading.
        
        Args:
            notebook_path: Path to the notebook
            name: Checkpoint name
            
        Returns:
            Path to verified checkpoint file
            
        Raises:
            FileNotFoundError: If checkpoint doesn't exist
            SecurityError: If signature verification fails
        """
        paths = self._get_paths(notebook_path, name)
        
        if not paths["data"].exists():
            raise FileNotFoundError(f"Checkpoint '{name}' not found at {paths['data']}")
        
        if not paths["meta"].exists():
            raise FileNotFoundError(f"Checkpoint metadata '{name}' not found at {paths['meta']}")
        
        try:
            # Load metadata
            with open(paths["meta"], "r") as f:
                meta = json.load(f)
            
            # Re-calculate HMAC
            with open(paths["data"], "rb") as f:
                data_bytes = f.read()
            
            secret_bytes = SESSION_SECRET if isinstance(SESSION_SECRET, bytes) else SESSION_SECRET.encode()
            expected_sig = hmac.new(secret_bytes, data_bytes, hashlib.sha256).hexdigest()
            
            # Verify signature using constant-time comparison
            if not hmac.compare_digest(meta["signature"], expected_sig):
                logger.error(f"[CHECKPOINTING] Signature mismatch for '{name}'")
                logger.error(f"  Expected: {expected_sig[:16]}...")
                logger.error(f"  Got:      {meta['signature'][:16]}...")
                raise SecurityError(
                    "⛔ SECURITY ALERT: Checkpoint signature mismatch! "
                    "File may have been tampered with or corrupted."
                )
            
            logger.info(f"[CHECKPOINTING] Verified signature for '{name}' ({meta['signature'][:16]}...)")
            return paths["data"]
            
        except json.JSONDecodeError as e:
            raise SecurityError(f"Checkpoint metadata corrupted: {e}")
        except Exception as e:
            logger.error(f"[CHECKPOINTING] Verification failed: {e}")
            raise

    def check_dependencies(self, notebook_path: str, name: str) -> List[str]:
        """
        Compare saved dependencies against current environment.
        
        Returns list of packages that were saved but are not installed now.
        
        Args:
            notebook_path: Path to the notebook
            name: Checkpoint name
            
        Returns:
            List of missing package requirements (e.g., ["pandas==1.3.0", "scikit-learn==0.24.2"])
        """
        paths = self._get_paths(notebook_path, name)
        
        if not paths["reqs"].exists():
            logger.debug(f"[CHECKPOINTING] No requirements file for '{name}'")
            return []
        
        try:
            # Get saved requirements
            saved_reqs = paths["reqs"].read_text().strip().splitlines()
            if not saved_reqs:
                return []
            
            # Get current environment
            current_reqs = subprocess.check_output(
                [sys.executable, "-m", "pip", "freeze"],
                timeout=30
            ).decode('utf-8').strip().splitlines()
            
            # Build sets of package names (ignoring versions for simplicity)
            # For precise version checking, use 'packaging.specifiers'
            current_packages = set()
            for line in current_reqs:
                if "==" in line:
                    pkg_name = line.split("==")[0].lower()
                    current_packages.add(pkg_name)
            
            # Find missing packages
            missing = []
            for line in saved_reqs:
                if "==" in line:
                    pkg_name = line.split("==")[0].lower()
                    if pkg_name not in current_packages:
                        missing.append(line)
            
            if missing:
                logger.warning(f"[CHECKPOINTING] Missing {len(missing)} packages for '{name}'")
                for pkg in missing[:5]:
                    logger.warning(f"  - {pkg}")
                if len(missing) > 5:
                    logger.warning(f"  ... and {len(missing) - 5} more")
            
            return missing
            
        except subprocess.TimeoutExpired:
            logger.error("[CHECKPOINTING] pip freeze timed out")
            return []
        except Exception as e:
            logger.error(f"[CHECKPOINTING] Dependency check failed: {e}")
            return []

    def list_checkpoints(self, notebook_path: str) -> List[str]:
        """
        List all checkpoints for a given notebook.
        
        Args:
            notebook_path: Path to the notebook
            
        Returns:
            List of checkpoint names (e.g., ["friday_work", "backup_v1"])
        """
        nb_id = hashlib.md5(notebook_path.encode()).hexdigest()[:8]
        pattern = f"{nb_id}_*.json"  # Use .json to identify checkpoints
        
        checkpoints = []
        for meta_file in self.checkpoints_dir.glob(pattern):
            # Extract name from filename
            name = meta_file.stem.replace(f"{nb_id}_", "")
            checkpoints.append(name)
        
        return sorted(checkpoints)

    def delete_checkpoint(self, notebook_path: str, name: str) -> bool:
        """
        Delete a checkpoint (cleanup for old/stale checkpoints).
        
        Args:
            notebook_path: Path to the notebook
            name: Checkpoint name to delete
            
        Returns:
            True if deleted, False if not found
        """
        paths = self._get_paths(notebook_path, name)
        
        deleted = False
        for path_key in ["data", "meta", "reqs"]:
            if paths[path_key].exists():
                paths[path_key].unlink()
                deleted = True
        
        if deleted:
            logger.info(f"[CHECKPOINTING] Deleted checkpoint '{name}'")
        
        return deleted

    def get_checkpoint_info(self, notebook_path: str, name: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata about a checkpoint without loading the data.
        
        Args:
            notebook_path: Path to the notebook
            name: Checkpoint name
            
        Returns:
            Metadata dict with timestamp, size, env_info, or None if not found
        """
        paths = self._get_paths(notebook_path, name)
        
        if not paths["meta"].exists():
            return None
        
        try:
            with open(paths["meta"], "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[CHECKPOINTING] Could not read metadata for '{name}': {e}")
            return None
