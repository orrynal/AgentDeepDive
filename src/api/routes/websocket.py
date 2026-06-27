import asyncio
from typing import Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
import structlog
import uuid
from sqlalchemy import select

from src.core.agent.pool import agent_bus
from src.core.auth.security import decode_jwt_token
from src.database import async_session
from src.core.auth.models import UserModel
from src.config import settings

logger = structlog.get_logger()
router = APIRouter()


async def authenticate_websocket(websocket: WebSocket) -> bool:
    """Authenticate WebSocket connection using query parameters, headers, or JWT token.
    If settings.api_key is not configured, authentication is bypassed for local/offline use.
    """
    if not settings.api_key:
        return True

    token = None
    
    # 1. Try to get token/api_key from query params (most common for browser WebSocket)
    token = websocket.query_params.get("token") or websocket.query_params.get("api_key")
    
    # 2. Try to get from headers
    if not token:
        token = websocket.headers.get("x-api-key")
    if not token:
        auth_header = websocket.headers.get("authorization")
        if auth_header:
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:]
            else:
                token = auth_header

    if not token:
        return False

    # 3. Check if token matches settings.api_key
    if token == settings.api_key:
        return True

    # 4. Try to decode as JWT
    payload = decode_jwt_token(token)
    if payload:
        user_id_str = payload.get("user_id")
        if user_id_str:
            try:
                user_uuid = uuid.UUID(user_id_str)
                async with async_session() as session:
                    result = await session.execute(select(UserModel).where(UserModel.id == user_uuid))
                    user = result.scalar_one_or_none()
                    if user:
                        return True
            except Exception:
                pass
                
    return False



@router.websocket("/ws")
async def websocket_events_stream(websocket: WebSocket):
    """Exposes a single WebSocket endpoint streaming all real-time events.

    Listens to Redis Pub/Sub channels (dag_updates, approval_updates, recovery)
    and relays them to the connected frontend client.
    """
    is_authenticated = await authenticate_websocket(websocket)
    if not is_authenticated:
        logger.warning("Rejected unauthorized WebSocket connection attempt")
        raise HTTPException(status_code=403, detail="Unauthorized WebSocket connection")

    await websocket.accept()
    logger.info("WebUI Cockpit WebSocket client connected")

    # Queue to safely transfer messages received in Redis callback to websocket send loop
    send_queue: asyncio.Queue = asyncio.Queue()

    # Define async callbacks for each Redis Pub/Sub channel we subscribe to
    async def handle_dag_update(msg: dict):
        await send_queue.put({"event_type": "dag_update", "data": msg.get("payload")})

    async def handle_approval_update(msg: dict):
        await send_queue.put({"event_type": "approval_update", "data": msg.get("payload")})

    async def handle_recovery(msg: dict):
        await send_queue.put({"event_type": "recovery", "data": msg.get("payload")})

    async def handle_terminal_update(msg: dict):
        await send_queue.put({"event_type": "terminal_update", "data": msg.get("payload")})

    # Subscribe to relevant channels
    await agent_bus.subscribe("dag_updates", handle_dag_update)
    await agent_bus.subscribe("approval_updates", handle_approval_update)
    await agent_bus.subscribe("recovery", handle_recovery)
    await agent_bus.subscribe("terminal_updates", handle_terminal_update)

    async def send_loop():
        """Saves messages from queue and writes them over the websocket connection."""
        try:
            while True:
                msg = await send_queue.get()
                await websocket.send_json(msg)
                send_queue.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error sending WebSocket message in loop", error=str(e))

    # Start helper loop to serialize and send messages
    send_task = asyncio.create_task(send_loop())

    try:
        # Keep client connection alive
        while True:
            # We can also receive commands from the frontend if needed
            # For now, just wait for text or ping/pong heartbeats
            data = await websocket.receive_text()
            # If front-end sends a ping, reply pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info("WebUI Cockpit WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket connection encountered an error", error=str(e))
    finally:
        # Cleanup subscriptions and running tasks
        send_task.cancel()
        try:
            await send_task
        except asyncio.CancelledError:
            pass

        await agent_bus.unsubscribe("dag_updates", handle_dag_update)
        await agent_bus.unsubscribe("approval_updates", handle_approval_update)
        await agent_bus.unsubscribe("recovery", handle_recovery)
        await agent_bus.unsubscribe("terminal_updates", handle_terminal_update)
