import asyncio
import importlib

from fastapi.testclient import TestClient

from server.app import app
from server.schemas import ImageFramePayload


app_module = importlib.import_module("server.app")
client = TestClient(app)
ONE_PIXEL_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4"
    "//8/AAX+Av5B8slRAAAAAElFTkSuQmCC"
)


def test_healthz() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_runtime_endpoint_uses_core_and_shared() -> None:
    response = client.get("/api/v1/runtime")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["shared"]["model_timeout"] >= 0
    assert payload["core"]["bbox_prompt_loaded"] is True
    assert payload["paths"]["core_src_root"].endswith("packages\\core\\src\\core")
    assert payload["paths"]["shared_src_root"].endswith("packages\\shared\\src")


def test_bbox_prompt_endpoint_returns_prompt_content() -> None:
    response = client.get("/api/v1/playground/prompts/bbox")

    assert response.status_code == 200
    payload = response.json()

    assert payload["prompt_key"] == "bbox"
    assert payload["locale"] == "zh-CN"
    assert "bbox" in payload["content"].lower()


def test_current_preprocess_endpoint_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module,
        "get_current_preprocess_payload",
        lambda: {
            "stage": "regions_identify",
            "image": {
                "image_hash": "frame-1",
                "image_url": f"data:image/png;base64,{ONE_PIXEL_PNG_BASE64}",
                "image_variant": "raw",
                "width": 1,
                "height": 1,
                "raw_width": 1,
                "raw_height": 1,
                "resized_width": 1,
                "resized_height": 1,
                "resize_max_side": 500,
                "source_file_name": "playground.png",
            },
            "regions": [],
            "page_anchors": [],
            "target_hint": None,
            "config": {},
            "matrix": {
                "nine_matrix": {},
                "refer_line_matrix": {},
            },
            "context": {},
            "errors": [],
        },
    )

    response = client.get("/api/v1/playground/current/preprocess")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "regions_identify"
    assert payload["image"]["source_file_name"] == "playground.png"
    assert payload["image"]["image_url"].startswith("data:image/png;base64,")


def test_current_preprocess_endpoint_returns_404_without_image(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "get_current_preprocess_payload", lambda: None)

    response = client.get("/api/v1/playground/current/preprocess")

    assert response.status_code == 404
    assert response.json() == {"detail": "当前没有可预处理的图片"}


def test_locator_elements_endpoint_returns_locator_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module,
        "get_locator_elements_payload",
        lambda **_: {
            "input_image": {
                "start_coordinate": [10, 20],
                "width": 100,
                "height": 80,
                "original_width": 200,
                "original_height": 160,
                "zoom_ratio": 1,
            },
            "elements": [
                {
                    "element_id": "button_1",
                    "type": "button",
                    "refine_type": "action_button",
                    "regions": {
                        "relative_bbox": [0.1, 0.2, 0.4, 0.5],
                        "absolute_bbox": [20, 40, 80, 100],
                        "action_point": [50, 70],
                        "action": "click",
                        "confidence": 0.98,
                    },
                }
            ],
            "errors": [],
        },
    )

    response = client.post(
        "/locator/elements",
        json={
            "original_image_size": {
                "width": 200,
                "height": 160,
            },
            "image": ONE_PIXEL_PNG_BASE64,
            "start_coordinate": [10, 20],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["input_image"]["start_coordinate"] == [10, 20]
    assert payload["elements"][0]["element_id"] == "button_1"
    assert payload["elements"][0]["regions"]["absolute_bbox"] == [20, 40, 80, 100]


def test_locator_elements_endpoint_accepts_missing_original_image_size_when_start_is_zero(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_locator_elements_payload(**kwargs):
        captured.update(kwargs)
        return {
            "input_image": {
                "start_coordinate": [0, 0],
                "width": 1,
                "height": 1,
                "original_width": 1,
                "original_height": 1,
                "zoom_ratio": 1,
            },
            "elements": [],
            "errors": [],
        }

    monkeypatch.setattr(app_module, "get_locator_elements_payload", fake_get_locator_elements_payload)

    response = client.post(
        "/locator/elements",
        json={
            "image": ONE_PIXEL_PNG_BASE64,
            "start_coordinate": [0, 0],
        },
    )

    assert response.status_code == 200
    assert captured["original_image_size"] is None
    assert captured["start_coordinate"] == [0, 0]


def test_locator_elements_endpoint_returns_400_without_original_image_size_when_start_is_non_zero() -> None:
    response = client.post(
        "/locator/elements",
        json={
            "image": ONE_PIXEL_PNG_BASE64,
            "start_coordinate": [10, 20],
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "original_image_size is required when start_coordinate is not [0, 0]"
    }


def test_publish_route_is_removed() -> None:
    response = client.post("/api/v1/playground/images/publish", json={})

    assert response.status_code == 404


def test_websocket_receives_current_image_frame_from_core_bridge(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module,
        "get_current_frame",
        lambda: ImageFramePayload(
            frame_id="frame-1",
            mime_type="image/png",
            image_url=f"data:image/png;base64,{ONE_PIXEL_PNG_BASE64}",
            width=1,
            height=1,
            sent_at="2026-06-21T00:00:00+00:00",
        ),
    )

    with client.websocket_connect("/ws/playground/image") as websocket:
        connected = websocket.receive_json()

        assert connected["type"] == "connected"
        assert connected["channel"] == "playground.image"
        assert connected["client_count"] >= 1

        frame = websocket.receive_json()
        assert frame["type"] == "image.frame"
        assert frame["frame_id"] == "frame-1"
        assert frame["mime_type"] == "image/png"
        assert frame["image_url"].startswith("data:image/png;base64,")


def test_websocket_ping_refreshes_current_image_frame(monkeypatch) -> None:
    frames = [
        ImageFramePayload(
            frame_id="frame-initial",
            mime_type="image/png",
            image_url=f"data:image/png;base64,{ONE_PIXEL_PNG_BASE64}",
            width=1,
            height=1,
            sent_at="2026-06-21T00:00:00+00:00",
        ),
        ImageFramePayload(
            frame_id="frame-refreshed",
            mime_type="image/png",
            image_url=f"data:image/png;base64,{ONE_PIXEL_PNG_BASE64}",
            width=1,
            height=1,
            sent_at="2026-06-21T00:00:01+00:00",
        ),
    ]

    def next_frame() -> ImageFramePayload:
        return frames.pop(0)

    monkeypatch.setattr(app_module, "get_current_frame", next_frame)

    with client.websocket_connect("/ws/playground/image") as websocket:
        websocket.receive_json()
        initial_frame = websocket.receive_json()
        assert initial_frame["frame_id"] == "frame-initial"

        websocket.send_json({"type": "ping"})

        refreshed_frame = websocket.receive_json()
        assert refreshed_frame["type"] == "image.frame"
        assert refreshed_frame["frame_id"] == "frame-refreshed"

        pong = websocket.receive_json()
        assert pong == {"type": "pong"}


def test_sync_current_frame_if_updated_skips_unchanged_frame(monkeypatch) -> None:
    current_frame = ImageFramePayload(
        frame_id="frame-same",
        mime_type="image/png",
        image_url=f"data:image/png;base64,{ONE_PIXEL_PNG_BASE64}",
        width=1,
        height=1,
        sent_at="2026-06-21T00:00:00+00:00",
    )

    app_module.playground_image_hub.set_current_frame(current_frame)
    monkeypatch.setattr(app_module, "get_current_frame", lambda: current_frame)

    delivered = asyncio.run(app_module.sync_current_frame_if_updated())

    assert delivered is False
    assert app_module.playground_image_hub.current_frame == current_frame


def test_sync_current_frame_if_updated_broadcasts_new_frame(monkeypatch) -> None:
    app_module.playground_image_hub.set_current_frame(None)
    next_frame = ImageFramePayload(
        frame_id="frame-new",
        mime_type="image/png",
        image_url=f"data:image/png;base64,{ONE_PIXEL_PNG_BASE64}",
        width=1,
        height=1,
        sent_at="2026-06-21T00:00:01+00:00",
    )
    monkeypatch.setattr(app_module, "get_current_frame", lambda: next_frame)

    delivered = asyncio.run(app_module.sync_current_frame_if_updated())

    assert delivered is True
    assert app_module.playground_image_hub.current_frame == next_frame
