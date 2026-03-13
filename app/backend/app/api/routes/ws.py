"""
WebSocket routes — real-time chat streaming.
"""
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.chat_service import ChatService

router = APIRouter()


@router.websocket("/chat/{session_id}")
async def ws_chat(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time chat.

    Client sends:
      {"type": "user_message", "text": "...", "user_id": "..."}

    Server streams back:
      {"type": "agent_activity", "agent": "...", "status": "working", "task": "..."}
      {"type": "partial_result", "text": "..."}
      {"type": "message", "role": "assistant", "content": "...", "session_id": "..."}
      {"type": "error", "detail": "..."}
    """
    await websocket.accept()
    chat_service = ChatService()

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            if data.get("type") != "user_message":
                continue

            text = data.get("text", "").strip()
            user_id = data.get("user_id", "anonymous")

            if not text:
                continue

            # Stream events back to client
            async for event in chat_service.process_message_stream(
                session_id=session_id,
                message=text,
                user_id=user_id,
            ):
                await websocket.send_text(json.dumps(event))

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_text(json.dumps({"type": "error", "detail": str(exc)}))
        except Exception:
            pass
