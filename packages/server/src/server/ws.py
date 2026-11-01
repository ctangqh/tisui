from __future__ import annotations


import datetime
try:
    # Python 3.11+
    UTC = datetime.UTC
except AttributeError:
    # Python 3.10
    UTC = datetime.timezone.utc

from uuid import uuid4

from fastapi import WebSocket

from .schemas import ImageFramePayload, ImagePublishRequest


def build_image_frame(request: ImagePublishRequest) -> ImageFramePayload:
    normalized_mime_type = request.mime_type.strip() or "image/png"
    image_value = request.image_base64.strip()
    if image_value.startswith("data:"):
        image_url = image_value
    else:
        image_url = f"data:{normalized_mime_type};base64,{image_value}"

    return ImageFramePayload(
        frame_id=request.frame_id or str(uuid4()),
        mime_type=normalized_mime_type,
        image_url=image_url,
        width=request.width,
        height=request.height,
        sent_at=datetime.now(UTC).isoformat(),
    )


class PlaygroundImageHub:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._current_frame: ImageFramePayload | None = None

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> str:
        await websocket.accept()
        client_id = str(uuid4())
        self._connections[client_id] = websocket
        return client_id

    def disconnect(self, client_id: str) -> None:
        self._connections.pop(client_id, None)

    @property
    def current_frame(self) -> ImageFramePayload | None:
        return self._current_frame

    def set_current_frame(self, frame: ImageFramePayload | None) -> None:
        self._current_frame = frame

    async def broadcast_frame(self, frame: ImageFramePayload) -> int:
        self._current_frame = frame
        delivered_count = 0
        stale_client_ids: list[str] = []
        payload = frame.model_dump(mode="json")

        for client_id, websocket in self._connections.items():
            try:
                await websocket.send_json(payload)
                delivered_count += 1
            except Exception:
                stale_client_ids.append(client_id)

        for client_id in stale_client_ids:
            self.disconnect(client_id)

        return delivered_count


playground_image_hub = PlaygroundImageHub()
