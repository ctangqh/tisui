from __future__ import annotations

from pathlib import Path

import uvicorn


def _resolve_app_str() -> str:
    """
    根据运行模式返回 uvicorn 应用字符串:
      - prod: dist/app/ 下有 static/index.html → "app.app:app"
      - dev:  monorepo 源码, 包名 server           → "server.app:app"
    """
    app_static_index = Path(__file__).resolve().parent / "static" / "index.html"
    return "app.app:app" if app_static_index.exists() else "server.app:app"


def run() -> None:
    uvicorn.run(
        _resolve_app_str(),
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    run()
