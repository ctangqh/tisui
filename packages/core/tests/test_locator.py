import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image as PILImage

from tisui.shared.config import settings

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ACTION_TEXT = "搜索 pymidscene "
LOCATOR_TIMEOUT_SECONDS = 360
TEST_CASES = [
    ("google", "google.png", "google_elements.json"),
    ("google_resized_500", "google_resized_500.jpg", "google_resized_500_elements.json"),
]


def _load_google_image(image_path: Path) -> dict:
    image_bytes = image_path.read_bytes()
    with PILImage.open(image_path) as image:
        return {
            "height": image.height,
            "width": image.width,
            "image_format": str(image.format or "PNG").upper(),
            "byte_size": len(image_bytes),
            "image_bytes": image_bytes,
            "zoom_ratio": 1.0,
        }


def _write_locator_payload(payload: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def _run_locator_with_timeout(
    *,
    image_path: Path,
    zoom_ratio: float,
    action_text: str,
    original_image_path: Path | None,
    timeout_seconds: int,
) -> dict:
    runner = """
import json
import sys
from pathlib import Path
from PIL import Image as PILImage

sys.path.insert(0, "src")

from tisui.agent.locator import locator

def load_image(path: Path) -> dict:
    image_bytes = path.read_bytes()
    with PILImage.open(path) as image:
        return {
            "height": image.height,
            "width": image.width,
            "image_format": str(image.format or "PNG").upper(),
            "byte_size": len(image_bytes),
            "image_bytes": image_bytes,
            "zoom_ratio": 1.0,
        }

image_path = Path(sys.argv[1])
zoom_ratio = float(sys.argv[2])
action_text = sys.argv[3]
original_image_arg = sys.argv[4] if len(sys.argv) > 4 else ""
original_image_path = Path(original_image_arg) if original_image_arg else None

image = load_image(image_path)
image["zoom_ratio"] = zoom_ratio
original_image = load_image(original_image_path) if original_image_path else None

result = locator(
    image=image,
    raw_absolute_coord=[0, 0],
    action_text=action_text,
    original_image=original_image,
)
print(json.dumps(result, ensure_ascii=False))
"""

    args = [
        sys.executable,
        "-c",
        runner,
        str(image_path),
        str(float(zoom_ratio)),
        str(action_text),
        str(original_image_path or ""),
    ]
    try:
        completed = subprocess.run(
            args,
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        return {"elements": [], "errors": [f"timeout_after_{timeout_seconds}s"]}
    except Exception as exc:
        return {"elements": [], "errors": [f"locator_error: {exc}"]}

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        errors = [f"locator_error: returncode_{completed.returncode}"]
        if stderr:
            errors.append(stderr[:1500])
        if stdout:
            errors.append(stdout[:1500])
        return {"elements": [], "errors": errors}

    raw = (completed.stdout or "").strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"elements": [], "errors": ["locator_error: invalid_result"]}
    except Exception as exc:
        return {"elements": [], "errors": [f"locator_error: invalid_json: {exc}", raw[:1500]]}

def _run_case(case_name: str, image_filename: str, output_filename: str, *, vision_api_key: str, timeout_seconds: int) -> None:
    image_path = Path(__file__).parent / "input" / image_filename
    output_path = Path(__file__).parent / "output" / output_filename
    original_image_path = None
    zoom_ratio = 1.0
    if case_name == "google":
        zoom_ratio = 1.0
        original_image_path = image_path
    elif case_name == "google_resized_500":
        original_image_path = Path(__file__).parent / "input" / "google.png"
        image = _load_google_image(image_path)
        original_image = _load_google_image(original_image_path)
        if int(original_image.get("width") or 0) > 0 and int(original_image.get("height") or 0) > 0 and int(image.get("width") or 0) > 0 and int(image.get("height") or 0) > 0:
            width_ratio = float(image.get("width") or 0) / float(original_image.get("width") or 1)
            height_ratio = float(image.get("height") or 0) / float(original_image.get("height") or 1)
            if abs(width_ratio - height_ratio) <= 0.01:
                zoom_ratio = width_ratio
            else:
                zoom_ratio = (width_ratio + height_ratio) / 2.0

    if not vision_api_key:
        _write_locator_payload(
            {"elements": [], "errors": ["VISION_API_KEY/LLM_API_KEY 未配置，无法调用大模型"]},
            output_path,
        )
        return

    result = _run_locator_with_timeout(
        image_path=image_path,
        zoom_ratio=zoom_ratio,
        action_text=ACTION_TEXT,
        original_image_path=original_image_path,
        timeout_seconds=timeout_seconds,
    )
    _write_locator_payload(result, output_path)


def test_locator_outputs():
    vision_api_key = str(settings.vision_config.api_key or "").strip()
    timeout_seconds = max(
        LOCATOR_TIMEOUT_SECONDS,
        int(settings.vision_config.timeout or 60) * (int(settings.vision_config.max_retries or 3) + 1) + 60,
    )
    for case_name, image_filename, output_filename in TEST_CASES:
        _run_case(case_name, image_filename, output_filename, vision_api_key=vision_api_key, timeout_seconds=timeout_seconds)
