# tisui-server

`packages/server` 是给 `packages/playground` 提供后台能力的 Python 服务工程。

当前工程提供：

- `FastAPI` 应用入口
- 本地引用 `packages/core` 与 `packages/shared` 源码的路径引导
- 健康检查接口
- 基于 `core.agent.prompt` 的示例接口

## 安装

```bash
cd packages/server
pip install -e ".[dev]"
```

## 启动

```bash
cd packages/server
python -m server.main
```

默认监听 `http://127.0.0.1:8000`。

## 接口

- `GET /healthz`
- `GET /api/v1/runtime`
- `GET /api/v1/playground/prompts/bbox`

## 说明

由于当前 `core` 与 `shared` 主要以仓库内源码目录方式被引用，`server` 通过启动时注入本地源码路径来复用它们，而不修改现有包定义。
