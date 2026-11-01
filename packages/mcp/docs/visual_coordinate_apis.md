# 基于视觉坐标操作的公共 API 名称

本文档整理了基于视觉坐标操作的公共 API 名称，这些 API 是从 Windows Application Driver 和 Hypium API 中抽象出来的，用于跨平台 MCP 工具开发。

---

## 1. 基础点击操作

| API 名称 | 说明 | 参数 |
|----------|------|------|
| `click` | 在指定坐标点击 | `x`, `y` |
| `long_click` | 在指定坐标长按 | `x`, `y`, `duration` |
| `double_click` | 在指定坐标双击 | `x`, `y`, `interval` |
| `right_click` | 在指定坐标右键点击 | `x`, `y` |

---

## 2. 滑动/拖拽操作

| API 名称 | 说明 | 参数 |
|----------|------|------|
| `swipe` | 从起始坐标滑动到结束坐标 | `start_x`, `start_y`, `end_x`, `end_y`, `duration` |
| `drag` | 从起始坐标拖拽到结束坐标 | `start_x`, `start_y`, `end_x`, `end_y`, `duration`, `press_time` |
| `scroll` | 在指定坐标滚动 | `x`, `y`, `steps`, `direction` |

---

## 3. 键盘输入操作

| API 名称 | 说明 | 参数 |
|----------|------|------|
| `send_keys` | 输入文本 | `text` |
| `press_key` | 按下键 | `key` |
| `release_key` | 释放键 | `key` |
| `key_combination` | 按组合键 | `key_list` |

---

## 4. 屏幕操作

| API 名称 | 说明 | 参数 |
|----------|------|------|
| `get_screenshot` | 获取屏幕截图 | 无 |
| `get_source` | 获取 UI 源码 | 无 |
| `get_screen_size` | 获取屏幕尺寸 | 无 |
| `get_rotation` | 获取屏幕旋转角度 | 无 |

---

## 5. 应用管理

| API 名称 | 说明 | 参数 |
|----------|------|------|
| `launch_app` | 启动应用 | `app_name` |
| `close_app` | 关闭应用 | `app_name` |

---

## 6. 会话管理

| API 名称 | 说明 | 参数 |
|----------|------|------|
| `create_session` | 创建会话 | 无 |
| `delete_session` | 删除会话 | 无 |
| `query_session` | 查询会话状态 | 无 |

---

## 7. MCP 工具命名规范

### 7.1 命名格式

```
{api_name}
```

不同平台在握手（handshake）时返回其支持的平台名称和可用工具列表，而不需要在工具名称中包含 platform 前缀。

### 7.2 公共参数定义

| 参数名 | 类型 | 说明 |
|--------|------|------|
| `x` | number | X 坐标（像素） |
| `y` | number | Y 坐标（像素） |
| `duration` | number | 持续时间（秒） |
| `interval` | number | 间隔时间（秒） |
| `text` | string | 输入文本 |
| `key` | string | 按键名称 |
| `key_list` | array | 组合键列表 |
| `steps` | number | 滚动步数 |
| `direction` | string | 滚动方向（up/down/left/right） |
| `app_name` | string | 应用名称 |
| `press_time` | number | 按下时间（秒） |

---

## 8. 核心 API 优先级

### 高优先级（基础操作）

1. `click` - 最常用的点击操作
2. `swipe` - 滑动操作
3. `get_screenshot` - 获取截图
4. `get_source` - 获取源码

### 中优先级

5. `long_click` - 长按操作
6. `double_click` - 双击操作
7. `drag` - 拖拽操作
8. `send_keys` - 输入文本
9. `get_screen_size` - 获取屏幕尺寸

### 低优先级

10. `right_click` - 右键点击
11. `scroll` - 滚动操作
12. `press_key` / `release_key` - 按下/释放键
13. `key_combination` - 组合键
14. `launch_app` / `close_app` - 启动/关闭应用
15. `create_session` / `delete_session` - 创建/删除会话

---

## 9. 完整 MCP tools 返回 JSON

### 9.1 WinAppDriver 平台

```json
{
  "jsonrpc": "2.0",
  "result": {
    "tools": [
      {
        "name": "click",
        "description": "在指定坐标点击",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" }
          },
          "required": ["x", "y"]
        }
      },
      {
        "name": "long_click",
        "description": "在指定坐标长按",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" },
            "duration": { "type": "number", "description": "持续时间（秒）", "default": 1.0 }
          },
          "required": ["x", "y"]
        }
      },
      {
        "name": "double_click",
        "description": "在指定坐标双击",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" },
            "interval": { "type": "number", "description": "间隔时间（秒）", "default": 0.3 }
          },
          "required": ["x", "y"]
        }
      },
      {
        "name": "right_click",
        "description": "在指定坐标右键点击",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" }
          },
          "required": ["x", "y"]
        }
      },
      {
        "name": "swipe",
        "description": "从起始坐标滑动到结束坐标",
        "inputSchema": {
          "type": "object",
          "properties": {
            "start_x": { "type": "number", "description": "起始 X 坐标" },
            "start_y": { "type": "number", "description": "起始 Y 坐标" },
            "end_x": { "type": "number", "description": "结束 X 坐标" },
            "end_y": { "type": "number", "description": "结束 Y 坐标" },
            "duration": { "type": "number", "description": "持续时间（秒）", "default": 0.5 }
          },
          "required": ["start_x", "start_y", "end_x", "end_y"]
        }
      },
      {
        "name": "drag",
        "description": "从起始坐标拖拽到结束坐标",
        "inputSchema": {
          "type": "object",
          "properties": {
            "start_x": { "type": "number", "description": "起始 X 坐标" },
            "start_y": { "type": "number", "description": "起始 Y 坐标" },
            "end_x": { "type": "number", "description": "结束 X 坐标" },
            "end_y": { "type": "number", "description": "结束 Y 坐标" },
            "duration": { "type": "number", "description": "持续时间（秒）", "default": 0.5 },
            "press_time": { "type": "number", "description": "按下时间（秒）", "default": 0.2 }
          },
          "required": ["start_x", "start_y", "end_x", "end_y"]
        }
      },
      {
        "name": "scroll",
        "description": "在指定坐标滚动",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" },
            "steps": { "type": "number", "description": "滚动步数" },
            "direction": { "type": "string", "description": "滚动方向（up/down/left/right）" }
          },
          "required": ["x", "y", "steps", "direction"]
        }
      },
      {
        "name": "send_keys",
        "description": "输入文本",
        "inputSchema": {
          "type": "object",
          "properties": {
            "text": { "type": "string", "description": "输入文本" }
          },
          "required": ["text"]
        }
      },
      {
        "name": "press_key",
        "description": "按下键",
        "inputSchema": {
          "type": "object",
          "properties": {
            "key": { "type": "string", "description": "按键名称" }
          },
          "required": ["key"]
        }
      },
      {
        "name": "release_key",
        "description": "释放键",
        "inputSchema": {
          "type": "object",
          "properties": {
            "key": { "type": "string", "description": "按键名称" }
          },
          "required": ["key"]
        }
      },
      {
        "name": "key_combination",
        "description": "按组合键",
        "inputSchema": {
          "type": "object",
          "properties": {
            "key_list": { "type": "array", "description": "组合键列表" }
          },
          "required": ["key_list"]
        }
      },
      {
        "name": "get_screenshot",
        "description": "获取屏幕截图",
        "inputSchema": {}
      },
      {
        "name": "get_source",
        "description": "获取 UI 源码",
        "inputSchema": {}
      },
      {
        "name": "get_screen_size",
        "description": "获取屏幕尺寸",
        "inputSchema": {}
      },
      {
        "name": "get_rotation",
        "description": "获取屏幕旋转角度",
        "inputSchema": {}
      },
      {
        "name": "launch_app",
        "description": "启动应用",
        "inputSchema": {
          "type": "object",
          "properties": {
            "app_name": { "type": "string", "description": "应用名称" }
          },
          "required": ["app_name"]
        }
      },
      {
        "name": "close_app",
        "description": "关闭应用",
        "inputSchema": {
          "type": "object",
          "properties": {
            "app_name": { "type": "string", "description": "应用名称" }
          },
          "required": ["app_name"]
        }
      },
      {
        "name": "create_session",
        "description": "创建会话",
        "inputSchema": {}
      },
      {
        "name": "delete_session",
        "description": "删除会话",
        "inputSchema": {}
      },
      {
        "name": "query_session",
        "description": "查询会话状态",
        "inputSchema": {}
      }
    ],
    "platform": "winapp",
    "version": "1.0.0"
  }
}
```

### 9.2 Hypium 平台

```json
{
  "jsonrpc": "2.0",
  "result": {
    "tools": [
      {
        "name": "click",
        "description": "在指定坐标点击",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" }
          },
          "required": ["x", "y"]
        }
      },
      {
        "name": "long_click",
        "description": "在指定坐标长按",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" },
            "duration": { "type": "number", "description": "持续时间（秒）", "default": 1.0 }
          },
          "required": ["x", "y"]
        }
      },
      {
        "name": "double_click",
        "description": "在指定坐标双击",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" },
            "interval": { "type": "number", "description": "间隔时间（秒）", "default": 0.3 }
          },
          "required": ["x", "y"]
        }
      },
      {
        "name": "right_click",
        "description": "在指定坐标右键点击",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" }
          },
          "required": ["x", "y"]
        }
      },
      {
        "name": "swipe",
        "description": "从起始坐标滑动到结束坐标",
        "inputSchema": {
          "type": "object",
          "properties": {
            "start_x": { "type": "number", "description": "起始 X 坐标" },
            "start_y": { "type": "number", "description": "起始 Y 坐标" },
            "end_x": { "type": "number", "description": "结束 X 坐标" },
            "end_y": { "type": "number", "description": "结束 Y 坐标" },
            "duration": { "type": "number", "description": "持续时间（秒）", "default": 0.5 }
          },
          "required": ["start_x", "start_y", "end_x", "end_y"]
        }
      },
      {
        "name": "drag",
        "description": "从起始坐标拖拽到结束坐标",
        "inputSchema": {
          "type": "object",
          "properties": {
            "start_x": { "type": "number", "description": "起始 X 坐标" },
            "start_y": { "type": "number", "description": "起始 Y 坐标" },
            "end_x": { "type": "number", "description": "结束 X 坐标" },
            "end_y": { "type": "number", "description": "结束 Y 坐标" },
            "duration": { "type": "number", "description": "持续时间（秒）", "default": 0.5 },
            "press_time": { "type": "number", "description": "按下时间（秒）", "default": 0.2 }
          },
          "required": ["start_x", "start_y", "end_x", "end_y"]
        }
      },
      {
        "name": "scroll",
        "description": "在指定坐标滚动",
        "inputSchema": {
          "type": "object",
          "properties": {
            "x": { "type": "number", "description": "X 坐标" },
            "y": { "type": "number", "description": "Y 坐标" },
            "steps": { "type": "number", "description": "滚动步数" },
            "direction": { "type": "string", "description": "滚动方向（up/down/left/right）" }
          },
          "required": ["x", "y", "steps", "direction"]
        }
      },
      {
        "name": "send_keys",
        "description": "输入文本",
        "inputSchema": {
          "type": "object",
          "properties": {
            "text": { "type": "string", "description": "输入文本" }
          },
          "required": ["text"]
        }
      },
      {
        "name": "press_key",
        "description": "按下键",
        "inputSchema": {
          "type": "object",
          "properties": {
            "key": { "type": "string", "description": "按键名称" }
          },
          "required": ["key"]
        }
      },
      {
        "name": "release_key",
        "description": "释放键",
        "inputSchema": {
          "type": "object",
          "properties": {
            "key": { "type": "string", "description": "按键名称" }
          },
          "required": ["key"]
        }
      },
      {
        "name": "key_combination",
        "description": "按组合键",
        "inputSchema": {
          "type": "object",
          "properties": {
            "key_list": { "type": "array", "description": "组合键列表" }
          },
          "required": ["key_list"]
        }
      },
      {
        "name": "get_screenshot",
        "description": "获取屏幕截图",
        "inputSchema": {}
      },
      {
        "name": "get_source",
        "description": "获取 UI 源码",
        "inputSchema": {}
      },
      {
        "name": "get_screen_size",
        "description": "获取屏幕尺寸",
        "inputSchema": {}
      },
      {
        "name": "get_rotation",
        "description": "获取屏幕旋转角度",
        "inputSchema": {}
      },
      {
        "name": "launch_app",
        "description": "启动应用",
        "inputSchema": {
          "type": "object",
          "properties": {
            "app_name": { "type": "string", "description": "应用名称" }
          },
          "required": ["app_name"]
        }
      },
      {
        "name": "close_app",
        "description": "关闭应用",
        "inputSchema": {
          "type": "object",
          "properties": {
            "app_name": { "type": "string", "description": "应用名称" }
          },
          "required": ["app_name"]
        }
      },
      {
        "name": "create_session",
        "description": "创建会话",
        "inputSchema": {}
      },
      {
        "name": "delete_session",
        "description": "删除会话",
        "inputSchema": {}
      },
      {
        "name": "query_session",
        "description": "查询会话状态",
        "inputSchema": {}
      }
    ],
    "platform": "harmony",
    "version": "1.0.0"
  }
}
```

---

## 10. 下一步工作

1. 为高优先级 API 创建 MCP 工具定义
2. 实现参数 schema 验证
3. 编写单元测试
4. 在 Playground 中集成这些 API 进行测试
5. 逐步实现中优先级和低优先级 API

---

## 附录

### 相关文档

- `packages/mcp/docs/public_api.md`：完整公共 API 文档
- `design/midscene-winapp-design.md`：WinApp 平台设计文档
