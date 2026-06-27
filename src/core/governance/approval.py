"""Approval Manager for human-in-the-loop verification.

Handles registering pending approvals, polling for approval/rejection signals,
and updating Node status color to orange during wait periods.
"""

import asyncio
import json
import time
import difflib
from pathlib import Path
from typing import Any
from uuid import uuid4
import redis.asyncio as aioredis
import structlog

from src.config import settings

logger = structlog.get_logger()

PENDING_LIST_KEY = "agentdeep:approvals:pending"
APPROVAL_KEY_PREFIX = "agentdeep:approvals:"

import hmac
import hashlib

def generate_approval_signature(approval_id: str, action: str, secret: str) -> str:
    msg = f"{approval_id}:{action}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:16]


def generate_tool_diff(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Generate a clean unified diff for file editing tools."""
    # 1. Identify target file path
    target_file = arguments.get("TargetFile") or arguments.get("AbsolutePath") or arguments.get("target_file")
    if not target_file:
        return None
        
    path = Path(target_file)
    # Check if the tool creates a new file or overwrites it completely
    is_new = not path.is_file()
    
    new_content = arguments.get("CodeContent") or arguments.get("content") or ""
    
    if is_new:
        if not new_content:
            return None
        # Return diff for a new file
        return f"--- /dev/null\n+++ b/{path.name}\n@@ -0,0 +1,{len(new_content.splitlines())} @@\n" + "\n".join(f"+{line}" for line in new_content.splitlines())

    try:
        # Read old content
        with open(path, "r", encoding="utf-8") as f:
            old_lines = f.readlines()
    except Exception:
        return None

    new_lines = []
    # 2. Extract new content based on tool type
    if tool_name in ("write_to_file", "write_file") or arguments.get("Overwrite"):
        new_lines = [l + "\n" if not l.endswith("\n") else l for l in new_content.splitlines()]
    elif tool_name in ("replace_file_content", "replace_content"):
        target_content = arguments.get("TargetContent") or arguments.get("targetContent")
        replacement_content = arguments.get("ReplacementContent") or arguments.get("replacementContent")
        if target_content is None or replacement_content is None:
            return None
            
        old_full = "".join(old_lines)
        if target_content in old_full:
            new_full = old_full.replace(target_content, replacement_content, 1)
            new_lines = [l + "\n" if not l.endswith("\n") else l for l in new_full.splitlines()]
        else:
            return None
    elif tool_name in ("multi_replace_file_content", "multi_replace"):
        chunks = arguments.get("ReplacementChunks") or arguments.get("replacement_chunks") or []
        if not chunks:
            return None
        old_full = "".join(old_lines)
        new_full = old_full
        for chunk in chunks:
            tc = chunk.get("TargetContent") or chunk.get("targetContent")
            rc = chunk.get("ReplacementContent") or chunk.get("replacementContent")
            if tc and rc and tc in new_full:
                new_full = new_full.replace(tc, rc, 1)
        new_lines = [l + "\n" if not l.endswith("\n") else l for l in new_full.splitlines()]
    else:
        return None

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path.name}",
        tofile=f"b/{path.name}",
        lineterm=""
    )
    return "\n".join(diff)


class ApprovalManager:
    """Manages L3 human-in-the-loop approval workflows."""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or settings.redis_url
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            from src.core.redis_pool import get_async_redis_client
            self._redis = get_async_redis_client()
        return self._redis

    async def request_approval(
        self,
        task_id: str,
        agent_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        priority: int = 50,
        tenant_id: str = "00000000-0000-0000-0000-000000000000",
        task_description: str | None = None,
    ) -> str:
        """Register a pending approval request and return the approval_id."""
        r = await self._get_redis()
        approval_id = f"appr-{uuid4().hex[:8]}"
        
        # Calculate diff if editing files
        diff_content = generate_tool_diff(tool_name, arguments)

        # Get active workspace details
        from src.core.workspace.manager import workspace_manager
        import os
        workspace_path = workspace_manager.active_workspace
        project_name = os.path.basename(workspace_path) if workspace_path else None

        payload = {
            "approval_id": approval_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "priority": priority,
            "status": "pending",
            "created_at": time.time(),
            "diff": diff_content,
            "tenant_id": tenant_id,
            "task_description": task_description,
            "workspace_path": workspace_path,
            "project_name": project_name,
            "approve_token": generate_approval_signature(approval_id, "approve", settings.jwt_secret),
            "reject_token": generate_approval_signature(approval_id, "reject", settings.jwt_secret),
        }

        # Save approval details
        await r.set(f"{APPROVAL_KEY_PREFIX}{approval_id}", json.dumps(payload, ensure_ascii=False))
        # Add to pending list
        await r.lpush(PENDING_LIST_KEY, approval_id)

        # Publish approval update to message bus
        from src.core.agent.pool import agent_bus
        asyncio.create_task(
            agent_bus.publish(
                topic="approval_updates",
                sender_id="approval_manager",
                payload=payload
            )
        )

        # Send Telegram notification if configured
        if settings.telegram_bot_token and settings.telegram_chat_id:
            asyncio.create_task(self._send_telegram_notification(payload))
            
        # Send Slack notification if configured
        if settings.slack_webhook_url:
            asyncio.create_task(self._send_slack_notification(payload))
            
        # Send Feishu notification if configured
        if settings.feishu_webhook_url:
            asyncio.create_task(self._send_feishu_notification(payload))
            
        # Send DingTalk notification if configured
        if settings.dingtalk_webhook_url:
            asyncio.create_task(self._send_dingtalk_notification(payload))

        # Send Discord notification if configured
        if settings.discord_bot_token and settings.discord_channel_id:
            asyncio.create_task(self._send_discord_notification(payload))

        # Send WeChat notification if configured
        if (settings.wechat_corp_id and settings.wechat_corp_secret and settings.wechat_agent_id) or settings.wechat_webhook_url:
            asyncio.create_task(self._send_wechat_notification(payload))

        # Send QQ notification if configured
        if settings.qq_bot_appid and settings.qq_bot_token and settings.qq_channel_id:
            asyncio.create_task(self._send_qq_notification(payload))

        # Send Twitter notification if configured
        if settings.twitter_bearer_token and settings.twitter_admin_userid:
            asyncio.create_task(self._send_twitter_notification(payload))

        # Send WhatsApp notification if configured
        if settings.whatsapp_token and settings.whatsapp_phone_id and settings.whatsapp_admin_phone:
            asyncio.create_task(self._send_whatsapp_notification(payload))

        logger.info(
            "Human approval requested (L3)",
            approval_id=approval_id,
            task_id=task_id,
            tool=tool_name,
        )
        return approval_id

    async def _send_telegram_notification(self, payload: dict):
        """Asynchronously send approval request notification to Telegram chat using HTML format."""
        from src.core.governance.notifications import send_telegram_notification
        await send_telegram_notification(payload)

    async def _send_slack_notification(self, payload: dict):
        """Asynchronously send approval request notification to Slack Webhook using Block Kit."""
        from src.core.governance.notifications import send_slack_notification
        await send_slack_notification(payload)

    async def _send_feishu_notification(self, payload: dict):
        """Asynchronously send approval request notification to Feishu/Lark Webhook using Interactive Cards."""
        from src.core.governance.notifications import send_feishu_notification
        await send_feishu_notification(payload)

    async def _send_dingtalk_notification(self, payload: dict):
        """Asynchronously send approval request notification to DingTalk Webhook using ActionCards."""
        from src.core.governance.notifications import send_dingtalk_notification
        await send_dingtalk_notification(payload)

    async def _send_discord_notification(self, payload: dict):
        """Asynchronously send approval request notification to Discord Channel."""
        from src.core.governance.notifications import send_discord_notification
        await send_discord_notification(payload)

    async def _send_wechat_notification(self, payload: dict):
        """Asynchronously send approval request notification to WeChat/企业微信."""
        from src.core.governance.notifications import send_wechat_notification
        await send_wechat_notification(payload)

    async def _send_qq_notification(self, payload: dict):
        """Asynchronously send approval request notification to QQ Channel."""
        from src.core.governance.notifications import send_qq_notification
        await send_qq_notification(payload)

    async def _send_twitter_notification(self, payload: dict):
        """Asynchronously send approval request notification to X / Twitter DM."""
        from src.core.governance.notifications import send_twitter_notification
        await send_twitter_notification(payload)

    async def _send_whatsapp_notification(self, payload: dict):
        """Asynchronously send approval request notification to WhatsApp."""
        from src.core.governance.notifications import send_whatsapp_notification
        await send_whatsapp_notification(payload)


    async def wait_for_approval(self, approval_id: str, timeout: float = 300.0) -> bool:
        """Poll Redis until approval is granted or rejected.

        Returns True if approved, False if rejected or timeout.
        """
        r = await self._get_redis()
        start_time = time.time()

        logger.info("Agent waiting for human approval signal", approval_id=approval_id)

        while time.time() - start_time < timeout:
            data_str = await r.get(f"{APPROVAL_KEY_PREFIX}{approval_id}")
            if not data_str:
                logger.warning("Approval request key not found", approval_id=approval_id)
                return False

            payload = json.loads(data_str)
            status = payload.get("status")

            if status == "approved":
                logger.info("Human approval GRANTED", approval_id=approval_id)
                return True
            elif status == "rejected":
                logger.info("Human approval REJECTED", approval_id=approval_id)
                return False

            await asyncio.sleep(1.0)

        logger.warning("Human approval request TIMEOUT", approval_id=approval_id)
        # Auto-reject on timeout
        await self.reject(approval_id)
        return False

    async def approve(self, approval_id: str, arguments: dict | None = None):
        """Set approval status to approved."""
        r = await self._get_redis()
        key = f"{APPROVAL_KEY_PREFIX}{approval_id}"
        data_str = await r.get(key)
        if data_str:
            payload = json.loads(data_str)
            if payload.get("status") in ("approved", "rejected"):
                logger.warning("Approval request already resolved, ignoring redundant approve action", approval_id=approval_id, current_status=payload.get("status"))
                return
                
            payload["status"] = "approved"
            payload["resolved_at"] = time.time()
            if arguments is not None:
                payload["arguments"] = arguments
            await r.set(key, json.dumps(payload, ensure_ascii=False))
            await r.lrem(PENDING_LIST_KEY, 0, approval_id)
            logger.info("Set approval status to approved", approval_id=approval_id)

            # Publish approval update to message bus
            from src.core.agent.pool import agent_bus
            asyncio.create_task(
                agent_bus.publish(
                    topic="approval_updates",
                    sender_id="approval_manager",
                    payload=payload
                )
            )

    async def get_approval_arguments(self, approval_id: str) -> dict | None:
        """Get the resolved arguments for an approval."""
        r = await self._get_redis()
        data_str = await r.get(f"{APPROVAL_KEY_PREFIX}{approval_id}")
        if data_str:
            payload = json.loads(data_str)
            return payload.get("arguments")
        return None

    async def reject(self, approval_id: str):
        """Set approval status to rejected."""
        r = await self._get_redis()
        key = f"{APPROVAL_KEY_PREFIX}{approval_id}"
        data_str = await r.get(key)
        if data_str:
            payload = json.loads(data_str)
            if payload.get("status") in ("approved", "rejected"):
                logger.warning("Approval request already resolved, ignoring redundant reject action", approval_id=approval_id, current_status=payload.get("status"))
                return
                
            payload["status"] = "rejected"
            payload["resolved_at"] = time.time()
            await r.set(key, json.dumps(payload, ensure_ascii=False))
            await r.lrem(PENDING_LIST_KEY, 0, approval_id)
            logger.info("Set approval status to rejected", approval_id=approval_id)

            # Publish approval update to message bus
            from src.core.agent.pool import agent_bus
            asyncio.create_task(
                agent_bus.publish(
                    topic="approval_updates",
                    sender_id="approval_manager",
                    payload=payload
                )
            )

    async def get_pending_approvals(self) -> list[dict[str, Any]]:
        """List all pending approval requests."""
        r = await self._get_redis()
        approval_ids = await r.lrange(PENDING_LIST_KEY, 0, -1)
        results = []

        from src.core.orchestrator.persistence import load_dags_from_disk
        from src.core.workspace.manager import workspace_manager
        import os

        dags_map = {}
        try:
            dags_map = load_dags_from_disk()
        except Exception:
            pass

        for appr_id in approval_ids:
            data_str = await r.get(f"{APPROVAL_KEY_PREFIX}{appr_id}")
            if data_str:
                payload = json.loads(data_str)
                task_id = payload.get("task_id", "")
                
                # Resolve via DAG definition first
                if ":" in task_id:
                    dag_id, _ = task_id.split(":", 1)
                    dag = dags_map.get(dag_id)
                    if dag:
                        if not payload.get("workspace_path") and dag.workspace_path:
                            payload["workspace_path"] = dag.workspace_path
                        if not payload.get("project_name") and dag.project_name:
                            payload["project_name"] = dag.project_name
                
                # Fallback to active workspace settings if still missing
                if not payload.get("workspace_path") or not payload.get("project_name"):
                    active_ws = workspace_manager.active_workspace
                    if active_ws:
                        if not payload.get("workspace_path"):
                            payload["workspace_path"] = active_ws
                        if not payload.get("project_name"):
                            payload["project_name"] = os.path.basename(active_ws)

                results.append(payload)
        return results


# Global Singleton
approval_manager = ApprovalManager()
