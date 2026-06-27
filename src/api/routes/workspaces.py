"""Workspace management routes."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from src.core.workspace.manager import workspace_manager
from src.api.security import verify_api_key

router = APIRouter()

class WorkspaceActiveRequest(BaseModel):
    path: str

class WorkspaceCreateRequest(BaseModel):
    path: str

@router.get("/workspaces", response_model=dict)
async def get_workspaces_status():
    """Get the list of workspaces and the active workspace."""
    return workspace_manager.get_status()

@router.post("/workspaces/active", response_model=dict)
async def set_active_workspace(body: WorkspaceActiveRequest):
    """Switch the current active workspace."""
    try:
        workspace_manager.set_active_workspace(body.path)
        
        # Trigger OPA policy hot-reload to sync with new workspace
        try:
            from src.core.governance.guardrails import GuardrailEngine
            GuardrailEngine()._upload_policy_to_opa()
        except Exception:
            pass
            
        return {
            "status": "ok",
            "active_workspace": workspace_manager.active_workspace,
            "workspaces": workspace_manager.workspaces
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/workspaces", response_model=dict)
async def create_workspace(body: WorkspaceCreateRequest):
    """Register and activate a new workspace path."""
    import os
    try:
        path = os.path.abspath(os.path.expanduser(body.path))
        os.makedirs(path, exist_ok=True)
        
        # Initialize .gitignore if not present
        gitignore_path = os.path.join(path, ".gitignore")
        if not os.path.exists(gitignore_path):
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write("__pycache__/\n*.pyc\n.dag_store/\nvenv/\n.env\n")
        
        # Initialize Git repo if not present
        git_dir = os.path.join(path, ".git")
        if not os.path.exists(git_dir):
            import subprocess
            try:
                subprocess.run(["git", "init", path], check=True, capture_output=True)
            except Exception as ge:
                pass # Git might not be installed or permissions issue, fail gracefully
        
        workspace_manager.set_active_workspace(path)
        
        # Trigger OPA policy hot-reload to sync with new workspace
        try:
            from src.core.governance.guardrails import GuardrailEngine
            GuardrailEngine()._upload_policy_to_opa()
        except Exception:
            pass
            
        return {
            "status": "ok",
            "active_workspace": workspace_manager.active_workspace,
            "workspaces": workspace_manager.workspaces
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
