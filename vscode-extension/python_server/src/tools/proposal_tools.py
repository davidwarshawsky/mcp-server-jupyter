"""
Proposal tools for MCP Jupyter Server.

Provides an edit proposal workflow for safe cell editing that 
avoids direct disk writes and prevents conflicts with editor buffers.
"""
import json
import datetime
from typing import Optional
from collections import deque

from src.config import load_and_validate_settings
from src.observability import get_logger

settings = load_and_validate_settings()

logger = get_logger(__name__)

# Persistence for proposals (12-Factor compliant)
PROPOSAL_STORE_FILE = settings.get_data_dir() / "proposals.json"

PROPOSAL_HISTORY = deque(maxlen=1000)  # Keep only the most recent 1000 proposals


def load_proposals():
    """Load proposals from disk to survive server restarts."""
    if PROPOSAL_STORE_FILE.exists():
        try:
            with open(PROPOSAL_STORE_FILE, 'r') as f:
                data = json.load(f)
                # Load history keys in insertion order if present
                for k in data.get('_history', []):
                    PROPOSAL_HISTORY.append(k)
                return data.get('store', {})
        except Exception as e:
            logger.error(f"Failed to load proposals: {e}")
    return {}


def save_proposals():
    """Save proposals to disk along with history to survive restarts."""
    try:
        PROPOSAL_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROPOSAL_STORE_FILE, 'w') as f:
            json.dump({'store': PROPOSAL_STORE, '_history': list(PROPOSAL_HISTORY)}, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save proposals: {e}")


def cleanup_old_proposals(max_age_hours: int = 24):
    """[ROUND 2 AUDIT] Remove proposals older than max_age_hours to prevent unbounded disk growth."""
    import time
    now = time.time()
    removed = []
    
    for proposal_id in list(PROPOSAL_STORE.keys()):
        proposal = PROPOSAL_STORE[proposal_id]
        timestamp = proposal.get('timestamp', 0)
        if now - timestamp > max_age_hours * 3600:
            PROPOSAL_STORE.pop(proposal_id)
            try:
                PROPOSAL_HISTORY.remove(proposal_id)
            except ValueError:
                pass
            removed.append(proposal_id)
    
    if removed:
        logger.info(f"[CLEANUP] Removed {len(removed)} old proposals")
        save_proposals()
    
    return len(removed)


# Store for agent proposals to support feedback loop
# Key: proposal_id, Value: dict with status, result, timestamp
PROPOSAL_STORE = load_proposals()


def save_proposal(proposal_id: str, data: dict):
    """Insert a proposal and evict oldest if over cap."""
    if proposal_id in PROPOSAL_STORE:
        PROPOSAL_STORE[proposal_id].update(data)
        # Move to most recent in history: remove and append
        try:
            PROPOSAL_HISTORY.remove(proposal_id)
        except ValueError:
            pass
        PROPOSAL_HISTORY.append(proposal_id)
    else:
        maxlen = PROPOSAL_HISTORY.maxlen or 1000
        if len(PROPOSAL_HISTORY) >= maxlen:
            # Evict oldest
            oldest = PROPOSAL_HISTORY.popleft()
            PROPOSAL_STORE.pop(oldest, None)
        PROPOSAL_STORE[proposal_id] = data
        PROPOSAL_HISTORY.append(proposal_id)
    # Persist to disk in best-effort manner
    try:
        save_proposals()
    except Exception:
        pass


def register_proposal_tools(mcp):
    """Register proposal workflow tools with the MCP server."""
    
    @mcp.tool()
    def propose_edit(notebook_path: str, index: int, new_content: str):
        """
        Propose an edit to a cell. 
        This avoids writing to disk directly, preventing conflicts with the editor buffer.
        The Agent should use this instead of 'edit_cell'.
        """
        import uuid
        proposal_id = str(uuid.uuid4())
        
        # Construct proposal
        proposal = {
            "id": proposal_id,
            "action": "edit_cell",
            "notebook_path": notebook_path,
            "index": index,
            "new_content": new_content,
            "timestamp": str(datetime.datetime.now())
        }

        # Persist the proposal with bounded history
        try:
            save_proposal(proposal_id, proposal)
        except Exception:
            logger.warning("Failed to persist proposal")
        
        # We return a specific structure that the Client (mcpClient.ts) listens for.
        # By convention, if the tool result contains this structure, the client
        # will trigger a WorkspaceEdit.
        
        return json.dumps({
            "status": "proposal_created", 
            "proposal_id": proposal_id,
            "proposal": proposal,
            "message": "Edit proposed. Client must apply changes.",
            # SIGNAL PROTOCOL
            "_mcp_action": "apply_edit" 
        })

    @mcp.tool()
    def notify_edit_result(notebook_path: str, proposal_id: str, status: str, message: Optional[str] = None):
        """
        Callback for the client to report the result of a proposed edit.
        status: 'accepted' | 'rejected' | 'failed'
        """
        logger.info(f"Edit result for {notebook_path} (ID: {proposal_id}): {status} - {message}")
        
        # Store result for agent to retrieve (bounded)
        timestamp = str(datetime.datetime.now())
        if proposal_id:
            try:
                existing = PROPOSAL_STORE.get(proposal_id, {})
                existing.update({
                    "status": status,
                    "message": message,
                    "updated_at": timestamp
                })
                save_proposal(proposal_id, existing)
            except Exception:
                PROPOSAL_STORE[proposal_id] = {
                    "status": status,
                    "message": message,
                    "updated_at": timestamp
                }
            # Persist latest state
            try:
                save_proposal(proposal_id, PROPOSAL_STORE[proposal_id])
            except Exception:
                # Best-effort persistence
                save_proposals()
        
        return json.dumps({
            "status": "ack",
            "proposal_id": proposal_id,
            "timestamp": timestamp
        })

    @mcp.tool()
    def get_proposal_status(proposal_id: str):
        """
        Check the status of a specific proposal.
        Returns: 'pending', 'accepted', 'rejected', 'failed', or 'unknown'.
        """
        if proposal_id in PROPOSAL_STORE:
            return json.dumps(PROPOSAL_STORE[proposal_id])
        return json.dumps({"status": "unknown"})
