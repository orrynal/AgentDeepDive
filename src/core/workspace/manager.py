import os
import json
import structlog
from src.config import settings

logger = structlog.get_logger()

# Storing metadata in application data directory
from pathlib import Path
META_PATH = str(Path.home() / ".gemini" / "antigravity" / "workspace_meta.json")

class WorkspaceManager:
    def __init__(self):
        self.meta_path = META_PATH
        self.load_metadata()

    def load_metadata(self):
        """Load global workspace metadata from disk."""
        if not os.path.exists(self.meta_path):
            self.active_workspace = ""
            self.workspaces = []
            self.save_metadata()
            return

        try:
            with open(self.meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.active_workspace = data.get("active_workspace", "")
            self.workspaces = data.get("workspaces", [])
            if self.active_workspace:
                settings.project_workspace_path = self.active_workspace
        except Exception as e:
            logger.error("Failed to load workspace metadata", error=str(e))
            self.active_workspace = ""
            self.workspaces = []

    def save_metadata(self):
        """Save global workspace metadata to disk."""
        try:
            os.makedirs(os.path.dirname(self.meta_path), exist_ok=True)
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "active_workspace": self.active_workspace,
                    "workspaces": self.workspaces
                }, f, indent=2)
        except Exception as e:
            logger.error("Failed to save workspace metadata", error=str(e))

    def set_active_workspace(self, path: str):
        """Set the active workspace, adding it to the list if new."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        
        # Security Path Validation / Access Control (Issue 16)
        forbidden_roots = ["/etc", "/bin", "/usr", "/var", "/sys", "/proc", "/dev", "/boot", "/lib", "/lib64", "/tmp"]  # nosec B108
        for forbidden in forbidden_roots:
            if abs_path == forbidden or abs_path.startswith(forbidden + "/"):
                raise ValueError(f"Access Denied: Path '{abs_path}' is inside a forbidden system directory.")
        
        home_path = os.path.expanduser("~")
        current_project_root = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
        
        is_under_home = abs_path.startswith(home_path + "/") or abs_path == home_path
        is_under_project = abs_path.startswith(current_project_root + "/") or abs_path == current_project_root
        
        if not (is_under_home or is_under_project):
            raise ValueError(f"Access Denied: Path '{abs_path}' must be located within the user's home directory or the project workspace.")

        self.active_workspace = abs_path
        if abs_path not in self.workspaces:
            self.workspaces.append(abs_path)
        
        # Apply runtime settings update
        settings.project_workspace_path = abs_path
        
        self.save_metadata()
        logger.info("Workspace activated", path=abs_path)

    def get_status(self):
        """Get the current workspace status."""
        return {
            "active_workspace": self.active_workspace,
            "workspaces": self.workspaces
        }

workspace_manager = WorkspaceManager()
