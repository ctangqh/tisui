from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RuntimeInfo(BaseModel):
    status: str = "ok"
    paths: dict[str, str | list[str]]
    shared: dict[str, str | int | bool]
    core: dict[str, str | int | bool]


class PromptPayload(BaseModel):
    prompt_key: str = Field(description="Prompt name exported from core")
    locale: str = Field(description="Resolved prompt locale")
    content: str = Field(description="Prompt content")


class ImagePublishRequest(BaseModel):
    image_base64: str = Field(description="Raw base64 string or data URL")
    mime_type: str = Field(default="image/png", description="Image MIME type")
    frame_id: str | None = Field(default=None, description="Optional frame identifier")
    width: int | None = Field(default=None, description="Optional frame width")
    height: int | None = Field(default=None, description="Optional frame height")


class ImageFramePayload(BaseModel):
    type: Literal["image.frame"] = "image.frame"
    frame_id: str = Field(description="Server generated or caller supplied frame id")
    mime_type: str = Field(description="Image MIME type")
    image_url: str = Field(description="Data URL used by playground for direct rendering")
    width: int | None = Field(default=None, description="Optional frame width")
    height: int | None = Field(default=None, description="Optional frame height")
    sent_at: str = Field(description="Server send timestamp")


class WsConnectedPayload(BaseModel):
    type: Literal["connected"] = "connected"
    channel: str = "playground.image"
    client_id: str = Field(description="Connection identifier")
    client_count: int = Field(description="Current active connection count")


class ImageSizePayload(BaseModel):
    width: int = Field(description="Image width")
    height: int = Field(description="Image height")


class LocatorElementsRequest(BaseModel):
    original_image_size: ImageSizePayload | None = Field(
        default=None,
        description="Original image size, optional when start_coordinate is [0, 0]",
    )
    image: str = Field(description="Cropped image base64 string or data URL")
    start_coordinate: list[int] = Field(
        min_length=2,
        max_length=2,
        description="Crop image start coordinate on original image, [x, y]",
    )


class PipelineDebugRequest(BaseModel):
    image: str = Field(description="Full image base64 string or data URL")
    action_text: str = Field(description="User action description, e.g. '点击搜索按钮'")
