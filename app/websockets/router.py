import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_ws
from app.core.database import get_db
from app.services.websocket_service import websocket_service

router = APIRouter()


@router.websocket("/servers/{server_id}/logs")
async def websocket_server_logs(
    websocket: WebSocket,
    server_id: int,
    token: str = Query(..., description="JWT token for authentication"),
    db: Session = Depends(get_db),
):
    """WebSocket endpoint for real-time server log streaming and status updates"""
    try:
        # Authenticate user using token
        user = await get_current_user_ws(token, db)

        # Handle WebSocket connection
        await websocket_service.handle_connection(websocket, server_id, user, db)

    except HTTPException as e:
        await websocket.close(code=1008, reason=e.detail)
    except Exception as e:
        await websocket.close(code=1011, reason=f"Internal error: {str(e)}")


@router.websocket("/servers/{server_id}/status")
async def websocket_server_status(
    websocket: WebSocket,
    server_id: int,
    token: str = Query(..., description="JWT token for authentication"),
    db: Session = Depends(get_db),
):
    """WebSocket endpoint for real-time server status updates only"""
    try:
        # Authenticate user using token
        user = await get_current_user_ws(token, db)

        # Handle WebSocket connection (status updates only)
        await websocket_service.handle_connection(websocket, server_id, user, db)

    except HTTPException as e:
        await websocket.close(code=1008, reason=e.detail)
    except Exception as e:
        await websocket.close(code=1011, reason=f"Internal error: {str(e)}")


@router.websocket("/notifications")
async def websocket_notifications(
    websocket: WebSocket,
    token: str = Query(..., description="JWT token for authentication"),
    db: Session = Depends(get_db),
):
    """WebSocket endpoint for system-wide notifications"""
    try:
        # Authenticate user using token
        user = await get_current_user_ws(token, db)

        await websocket.accept()

        # Send welcome message
        welcome_message = {
            "type": "welcome",
            "message": f"Connected to notifications as {user.username}",
            "timestamp": datetime.now().isoformat(),
        }
        await websocket.send_text(json.dumps(welcome_message))

        # Keep connection alive and handle messages
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "ping":
                    pong_message = {
                        "type": "pong",
                        "timestamp": datetime.now().isoformat(),
                    }
                    await websocket.send_text(json.dumps(pong_message))

        except Exception:
            pass

    except HTTPException as e:
        await websocket.close(code=1008, reason=e.detail)
    except Exception as e:
        await websocket.close(code=1011, reason=f"Internal error: {str(e)}")
