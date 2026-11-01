from __future__ import annotations

import base64
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from PIL import Image


def normalize_image_mime_type(mime_type: str) -> str:
    normalized = (mime_type or "image/png").strip().lower()
    if normalized == "image/jpg":
        return "image/jpeg"
    return normalized


@dataclass
class UnifiedImage:
    data: bytes
    mime_type: str
    width: int
    height: int
    source: str = "inline"
    file_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        mime_type: str = "image/png",
        source: str = "inline",
        file_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "UnifiedImage":
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
        return cls(
            data=data,
            mime_type=normalize_image_mime_type(mime_type),
            width=width,
            height=height,
            source=source,
            file_name=file_name,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_base64(
        cls,
        data: str,
        mime_type: str = "image/png",
        source: str = "inline",
        file_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "UnifiedImage":
        raw = (data or "").strip()
        resolved_mime_type = normalize_image_mime_type(mime_type)
        if raw.startswith("data:") and ";base64," in raw:
            header, raw = raw.split(";base64,", 1)
            resolved_mime_type = normalize_image_mime_type(header[5:])
        return cls.from_bytes(
            base64.b64decode(raw),
            mime_type=resolved_mime_type,
            source=source,
            file_name=file_name,
            metadata=metadata,
        )

    @property
    def byte_size(self) -> int:
        return len(self.data)

    def to_base64(self) -> str:
        return base64.b64encode(self.data).decode("utf-8")

    def to_data_url(self) -> str:
        encoded = self.to_base64()
        return f"data:{self.mime_type};base64,{encoded}"

    def convert_to_format(
        self, target_mime_type: str, quality: int = 85
    ) -> "UnifiedImage":
        """将图片转换为指定格式 (MIME type: image/webp, image/jpeg, image/png 等)"""
        target_mime_type = normalize_image_mime_type(target_mime_type)
        
        if target_mime_type == self.mime_type:
            return self
        
        # PIL 格式名称映射
        format_map = {
            "image/png": "PNG",
            "image/jpeg": "JPEG",
            "image/webp": "WEBP",
        }
        target_format = format_map.get(target_mime_type)
        if not target_format:
            raise ValueError(f"不支持的目标图片格式: {target_mime_type}")
        
        # 转换
        with Image.open(BytesIO(self.data)) as img:
            img.load()
            # 处理需要 RGB 的格式
            if target_mime_type in ("image/jpeg", "image/webp") and img.mode != "RGB":
                img = img.convert("RGB")
            
            output_buffer = BytesIO()
            
            if target_format == "JPEG":
                img.save(output_buffer, format="JPEG", quality=quality, optimize=True)
            elif target_format == "WEBP":
                img.save(output_buffer, format="WEBP", quality=quality, optimize=True, lossless=False)
            else:
                img.save(output_buffer, format="PNG", optimize=True)
        
        output_data = output_buffer.getvalue()
        
        return UnifiedImage(
            data=output_data,
            mime_type=target_mime_type,
            width=self.width,
            height=self.height,
            source=self.source,
            file_name=self.file_name,
            metadata=dict(self.metadata),
        )
    
    def convert_to_best_format(
        self, supported_formats: list[str], preferred_order: list[str], quality: int = 85
    ) -> "UnifiedImage":
        """优先使用 supported_formats 中最优先的格式，回退到当前格式"""
        for fmt in preferred_order:
            if fmt in supported_formats:
                try:
                    return self.convert_to_format(fmt, quality=quality)
                except Exception:
                    continue
        return self


@dataclass
class ModelCapabilities:
    supports_text: bool = True
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_system_prompt: bool = True
    supports_tool_calling: bool = False
    # 视觉模型支持的图片格式 (MIME types)
    supported_image_formats: list[str] = field(
        default_factory=lambda: ["image/png", "image/jpeg", "image/webp"]
    )
    # 推荐的优先格式 (会先尝试使用这些格式)
    preferred_image_formats: list[str] = field(
        default_factory=lambda: ["image/jpeg", "image/png"]
    )


__all__ = [
    "UnifiedImage",
    "ModelCapabilities",
    "normalize_image_mime_type",
]
