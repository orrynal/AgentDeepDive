"""Chat session management for AgentDeepDive Interactive Terminal."""

import json
import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
import structlog
from src.config import settings

logger = structlog.get_logger()

# We save chat history inside the workspace folder under .chat_history
HISTORY_DIR = Path(os.getcwd()) / ".chat_history"

class ChatSession:
    """Manages the message history, token budgeting, and disk persistence of a chat session."""

    def __init__(self, model: str | None = None, tenant_id: str = "00000000-0000-0000-0000-000000000000", max_context_tokens: int = 100000):
        self.session_id = f"session-{uuid4().hex[:8]}"
        self.model = model or settings.default_model
        self.tenant_id = tenant_id
        self.max_context_tokens = max_context_tokens
        self.started_at = datetime.now(timezone.utc)
        self.messages: list[dict] = []
        
        # Add default system prompt
        self.messages.append({
            "role": "system",
            "content": (
                "You are a premium AI agent, "
                "integrated into the AgentDeepDive multi-agent orchestration platform. "
                "You have access to a rich set of system commands and tools. When executing code "
                "or interacting with the workspace, explain your reasoning clearly and keep "
                "your tone professional, helpful, and concise."
            )
        })

    def add_user_message(self, content: str):
        """Append a user message to the conversation."""
        self.messages.append({"role": "user", "content": content})
        self.truncate_context()

    def add_assistant_message(self, content: str):
        """Append an assistant response to the conversation."""
        self.messages.append({"role": "assistant", "content": content})
        self.truncate_context()

    def add_tool_result(self, tool_call_id: str, tool_name: str, content: str):
        """Append a tool call execution result to the conversation."""
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": content
        })
        self.truncate_context()

    def add_raw_message(self, msg: dict):
        """Directly append a message dict (useful for tool calls request delta)."""
        self.messages.append(msg)

    def clear(self):
        """Reset the conversation context, keeping only the system prompt."""
        system_msg = self.messages[0] if self.messages and self.messages[0]["role"] == "system" else None
        self.messages = []
        if system_msg:
            self.messages.append(system_msg)
        else:
            self.__init__(model=self.model, tenant_id=self.tenant_id, max_context_tokens=self.max_context_tokens)

    def estimate_tokens(self) -> int:
        """Estimate the total token count of the current message chain."""
        total = 0
        for msg in self.messages:
            content = msg.get("content") or ""
            if isinstance(content, list):
                # Handle complex content blocks if any
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total += len(part["text"]) // 4
            else:
                total += len(str(content)) // 4
            
            # Add cost for tool calls metadata
            if msg.get("tool_calls"):
                total += len(str(msg["tool_calls"])) // 4
        return total

    def truncate_context(self):
        """Truncate oldest messages (excluding system/role instructions) if estimated tokens exceed budget."""
        while self.estimate_tokens() > self.max_context_tokens:
            # Count non-system messages
            non_system_count = sum(1 for m in self.messages if m.get("role") != "system")
            if non_system_count <= 1:
                # Keep at least the latest user/assistant message so the active turn is not lost
                break

            # Find the oldest non-system message to discard
            discard_idx = -1
            for i in range(len(self.messages)):
                if self.messages[i].get("role") != "system":
                    discard_idx = i
                    break

            if discard_idx != -1:
                self.messages.pop(discard_idx)
            else:
                break

    def save_to_disk(self, filename: str | None = None) -> Path:
        """Save the session message history to a local JSON file."""
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        file_name = filename or f"{self.session_id}.json"
        if not file_name.endswith(".json"):
            file_name += ".json"
        
        filepath = HISTORY_DIR / file_name
        data = {
            "session_id": self.session_id,
            "model": self.model,
            "tenant_id": self.tenant_id,
            "started_at": self.started_at.isoformat(),
            "messages": self.messages
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return filepath

    def load_from_disk(self, filepath: Path) -> bool:
        """Load session messages and state from a saved JSON file."""
        if not filepath.exists():
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.session_id = data.get("session_id", self.session_id)
            self.model = data.get("model", self.model)
            self.tenant_id = data.get("tenant_id", self.tenant_id)
            if "started_at" in data:
                self.started_at = datetime.fromisoformat(data["started_at"])
            self.messages = data.get("messages", [])
            return True
        except Exception as e:
            logger.error("Failed to load chat session from disk", error=str(e), path=str(filepath))
            return False
