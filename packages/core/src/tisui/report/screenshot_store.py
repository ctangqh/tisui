"""关键截图落盘与去重。

同一运行内相同像素的截图只写一次 (按内容 sha256 去重), 文件名即 screenshot_id。
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class ScreenshotStore:
    """把截图字节落盘到 screenshots/ 并返回稳定 id (内容去重)。"""

    def __init__(self, screenshots_dir: Path) -> None:
        self._dir = Path(screenshots_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._by_hash: dict[str, str] = {}

    def save(self, image: bytes, *, ext: str = "png") -> str:
        """写入截图, 返回 screenshot_id; 内容相同则复用已写文件。"""
        digest = hashlib.sha256(image).hexdigest()[:16]
        existing = self._by_hash.get(digest)
        if existing is not None:
            return existing
        screenshot_id = digest
        path = self._dir / f"{screenshot_id}.{ext}"
        if not path.exists():
            path.write_bytes(image)
        self._by_hash[digest] = screenshot_id
        return screenshot_id


__all__ = ["ScreenshotStore"]
