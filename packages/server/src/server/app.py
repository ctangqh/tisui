from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .adapt.core_bridge import (
    get_bbox_prompt,
    get_current_frame,
    get_current_preprocess_payload,
    get_locator_elements_payload,
)
from .playground.locator import router as playground_locator_router
from .schemas import (
    PromptPayload,
    RuntimeInfo,
    WsConnectedPayload,
)
from .ws import playground_image_hub


from tisui.shared.config import ROOT_CONFIG_YAML_PATH, settings
from tisui.shared.logger import logger
FRAME_SYNC_INTERVAL_SECONDS = 1.0
current_frame_monitor_task: asyncio.Task[None] | None = None


# =============================================================================
# 运行模式检测: dev(monorepo 源码运行) vs prod(dist 目录运行)
# =============================================================================

def _detect_runtime_mode() -> str:
    """
    通过检查 app.py 同级是否存在 static/index.html 判定运行模式:
      - prod: dist/app/static/index.html 存在 (构建产物)
      - dev:  不存在 (monorepo 开发环境, 前端由 vite dev server 提供)
    """
    app_static_index = Path(__file__).resolve().parent / "static" / "index.html"
    return "prod" if app_static_index.exists() else "dev"


RUNTIME_MODE = _detect_runtime_mode()


def _build_cors_origins() -> list[str]:
    """
    dev 模式下 vite dev server 使用独立端口(5173/4173), 需要 CORS。
    prod 模式下前端由 server 同源托管, 不需要 CORS。
    """
    if RUNTIME_MODE == "prod":
        return []
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ]


app = FastAPI(
    title="Tisui Server",
    version="0.1.0",
    description="Backend service for Tisui playground.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(playground_locator_router)


async def sync_current_frame_if_updated() -> bool:
    refreshed_frame = get_current_frame()
    previous_frame = playground_image_hub.current_frame

    if refreshed_frame is None:
        return False

    if previous_frame is not None and previous_frame.frame_id == refreshed_frame.frame_id:
        return False

    await playground_image_hub.broadcast_frame(refreshed_frame)
    return True


async def monitor_current_frame() -> None:
    while True:
        try:
            await sync_current_frame_if_updated()
        except Exception:
            # Keep the monitor alive even if a single frame read fails.
            pass
        await asyncio.sleep(FRAME_SYNC_INTERVAL_SECONDS)


@app.on_event("startup")
async def start_current_frame_monitor() -> None:
    global current_frame_monitor_task
    if current_frame_monitor_task is None or current_frame_monitor_task.done():
        current_frame_monitor_task = asyncio.create_task(monitor_current_frame())


@app.on_event("shutdown")
async def stop_current_frame_monitor() -> None:
    global current_frame_monitor_task
    if current_frame_monitor_task is None:
        return

    current_frame_monitor_task.cancel()
    with suppress(asyncio.CancelledError):
        await current_frame_monitor_task
    current_frame_monitor_task = None


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/runtime", response_model=RuntimeInfo)
def get_runtime() -> RuntimeInfo:
    locale, prompt = get_bbox_prompt()
    return RuntimeInfo(
        paths={},
        shared={
            "config_yaml_path": str(ROOT_CONFIG_YAML_PATH),
            "debug": settings.debug,
            "model_timeout": settings.MODEL_TIMEOUT,
            "runtime_mode": RUNTIME_MODE,
        },
        core={
            "prompt_locale": locale,
            "bbox_prompt_loaded": bool(prompt),
            "bbox_prompt_length": len(prompt),
        },
    )


@app.get("/api/v1/playground/prompts/bbox", response_model=PromptPayload)
def get_bbox_prompt_endpoint() -> PromptPayload:
    locale, content = get_bbox_prompt()
    return PromptPayload(
        prompt_key="bbox",
        locale=locale,
        content=content,
    )


@app.get("/api/v1/playground/current/preprocess")
def get_current_preprocess_endpoint() -> dict[str, Any]:
    payload = get_current_preprocess_payload()
    if payload is None:
        raise HTTPException(status_code=404, detail="当前没有可预处理的图片")
    return payload


@app.websocket("/ws/playground/image")
async def playground_image_ws(websocket: WebSocket) -> None:
    client_id = await playground_image_hub.connect(websocket)
    try:
        await websocket.send_json(
            WsConnectedPayload(
                client_id=client_id,
                client_count=playground_image_hub.connection_count,
            ).model_dump(mode="json")
        )

        frame_was_broadcast = await sync_current_frame_if_updated()
        if not frame_was_broadcast and playground_image_hub.current_frame is not None:
            await websocket.send_json(playground_image_hub.current_frame.model_dump(mode="json"))

        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict):
                message_type = message.get("type")
                if message_type == "ping":
                    await sync_current_frame_if_updated()
                    await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        playground_image_hub.disconnect(client_id)
    except Exception:
        playground_image_hub.disconnect(client_id)
        raise


# ---------------------------------------------------------------------------
# 静态文件托管: dev 模式前端由 vite dev server (5173) 提供, 不挂载;
# prod 模式从 app/static/ 直接托管, 支持 TISUI_PLAYGROUND_DIR 环境变量覆盖。
# 使用 GET /{rest:path} catch-all + FileResponse 替代 StaticFiles mount,
# 确保 SPA 客户端路由 (如 /debug/locator) 也能回退到 index.html。
# 注册在所有 API/WebSocket 路由之后, 不影响已注册路由。
# ---------------------------------------------------------------------------
def _resolve_playground_dist() -> Path | None:
    # 环境变量最高优先级 (dev / prod 通用)
    override = os.environ.get("TISUI_PLAYGROUND_DIR", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if (candidate / "index.html").exists():
            logger.info(f"[static] 使用 TISUI_PLAYGROUND_DIR: {candidate}")
            return candidate

    if RUNTIME_MODE == "prod":
        # prod: 静态文件在 app/static/ 下 (构建时由 build.ps1/build.sh 放置)
        app_static = Path(__file__).resolve().parent / "static"
        if (app_static / "index.html").exists():
            logger.info(f"[static] prod 模式, 托管: {app_static}")
            return app_static
        logger.warning("[static] prod 模式但未找到 app/static/index.html")
        return None

    # dev: 可选托管本地构建产物 (便于调试, 通常不挂载)
    cwd_candidate = Path.cwd() / "playground"
    if (cwd_candidate / "index.html").exists():
        logger.info(f"[static] dev 模式, 托管 CWD playground: {cwd_candidate}")
        return cwd_candidate
    logger.info("[static] dev 模式, 不托管静态文件 (前端由 vite dev server 提供)")
    return None


_playground_dist = _resolve_playground_dist()
if _playground_dist is not None:
    from fastapi.responses import FileResponse

    _index_html = _playground_dist / "index.html"

    @app.get("/{rest:path}")
    async def _serve_spa(rest: str):
        """SPA fallback: 请求路径对应真实文件则直接返回, 否则回退到 index.html"""
        candidate = _playground_dist / rest
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_index_html), media_type="text/html")


logger.info(f"Tisui Server 启动: mode={RUNTIME_MODE}, static={'mounted' if _playground_dist else 'none'}")
