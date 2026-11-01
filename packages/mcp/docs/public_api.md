# 公共基于坐标的 API 文档

本文档整理了 Windows Application Driver 和 Hypium 基于窗口坐标操作的公共 API，为跨平台 MCP 工具抽象提供标准。

---

## 1. Windows Application Driver API

基于设计文档 `design/midscene-winapp-design.md` 的分析，WinAppDriver 支持以下基于坐标的操作：

### 1.1 会话管理

| API | 说明 |
|-----|------|
| `session create` | 创建会话 |
| `session delete` | 删除会话 |
| `session query` | 查询会话状态 |

### 1.2 应用管理

| API | 说明 |
|-----|------|
| `application launch` | 启动应用 |
| `application close` | 关闭应用 |

### 1.3 鼠标/窗口操作

| API | 说明 |
|-----|------|
| `mouse move` | 移动鼠标到指定坐标 |
| `mouse click` | 在指定坐标点击鼠标 |
| `mouse double click` | 在指定坐标双击鼠标 |
| `mouse right click` | 在指定坐标右键点击 |
| `mouse long click` | 在指定坐标长按鼠标 |
| `mouse drag` | 从起始坐标拖拽到结束坐标 |
| `window screenshot` | 获取窗口截图 |
| `window source` | 获取 UI 源码 |

### 1.4 元素操作

| API | 说明 |
|-----|------|
| `element find` | 查找元素 |
| `element click` | 点击元素 |
| `element send keys` | 向元素输入文本 |

---

## 2. Hypium API

基于 `hypium` 包的分析，Hypium 支持以下基于坐标的操作：

### 2.1 设备信息

| API | 说明 |
|-----|------|
| `get display size` | 获取屏幕尺寸 |
| `get display rotation` | 获取屏幕旋转角度 |
| `get device type` | 获取设备类型 |
| `get os type` | 获取操作系统类型 |
| `get api level` | 获取 API 版本 |
| `get device sn` | 获取设备序列号 |

### 2.2 输入设备类型

| 类型 | 说明 |
|------|------|
| `TOUCHSCREEN` | 触摸屏 |
| `MOUSE` | 鼠标 |
| `KEYBOARD` | 键盘 |
| `TOUCHPAD` | 触控板 |
| `TS_PEN` | 触控笔 |
| `VOLUME_BUTTON` | 音量键 |
| `POWER_BUTTON` | 电源键 |
| `KNOB` | 旋钮 |

### 2.3 键盘输入

| API | 说明 |
|-----|------|
| `keyboard.click(key)` | 点击指定键 |
| `keyboard.long_click(key, duration)` | 长按指定键 |
| `keyboard.double_click(key, interval)` | 双击指定键 |
| `keyboard.click_combination_key(key_list, duration)` | 按组合键 |
| `keyboard.press(key)` | 按下键 |
| `keyboard.release(key)` | 释放键 |

### 2.4 鼠标输入

| API | 说明 |
|-----|------|
| `mouse.click(key)` | 点击鼠标键 |
| `mouse.long_click(key, duration)` | 长按鼠标键 |
| `mouse.double_click(key, interval)` | 双击鼠标键 |
| `mouse.move_to(pos, step_len=30)` | 移动鼠标到指定坐标 |
| `mouse.scroll(steps, duration)` | 滚动鼠标 |
| `mouse.drag_to(pos, step_len=30)` | 拖拽鼠标到指定坐标 |
| `mouse.press(key)` | 按下鼠标键 |
| `mouse.release(key)` | 释放鼠标键 |

### 2.5 触摸屏输入

| API | 说明 |
|-----|------|
| `touch.click(pos)` | 在指定坐标点击 |
| `touch.long_click(pos, duration)` | 在指定坐标长按 |
| `touch.double_click(pos, interval)` | 在指定坐标双击 |
| `touch.swipe(start_pos, end_pos, duration)` | 从起始坐标滑动到结束坐标 |
| `touch.drag(start_pos, end_pos, duration, press_time)` | 从起始坐标拖拽到结束坐标 |
| `touch.swipe_and_hold(start_pos, end_pos, duration, hold_duration=1)` | 滑动并保持 |
| `touch.swipe_by_two_finger(start_pos1, end_pos1, start_pos2, end_pos2, duration)` | 双指滑动 |
| `touch.press(key)` | 按下键 |
| `touch.release(key)` | 释放键 |

---

## 3. 公共 API 抽象

基于以上分析，抽象出跨平台公共的基于坐标操作的 API：

### 3.1 基础操作

| API | 说明 | 对应 WinAppDriver | 对应 Hypium |
|-----|------|------------------|-------------|
| `click(x, y)` | 在指定坐标点击 | `mouse click` | `touch.click` / `mouse.click` |
| `long_click(x, y, duration)` | 在指定坐标长按 | `mouse long click` | `touch.long_click` |
| `double_click(x, y, interval)` | 在指定坐标双击 | `mouse double click` | `touch.double_click` |
| `right_click(x, y)` | 在指定坐标右键点击 | `mouse right click` | `mouse.right_click` |

### 3.2 滑动/拖拽操作

| API | 说明 | 对应 WinAppDriver | 对应 Hypium |
|-----|------|------------------|-------------|
| `swipe(start_x, start_y, end_x, end_y, duration)` | 从起始坐标滑动到结束坐标 | `window swipe` | `touch.swipe` |
| `drag(start_x, start_y, end_x, end_y, duration, press_time)` | 从起始坐标拖拽到结束坐标 | `mouse drag` | `touch.drag` |
| `scroll(x, y, steps, direction)` | 在指定坐标滚动 | `mouse scroll` | `mouse.scroll` |

### 3.3 键盘输入

| API | 说明 | 对应 WinAppDriver | 对应 Hypium |
|-----|------|------------------|-------------|
| `send_keys(text)` | 输入文本 | `element send keys` | `keyboard.send_keys` |
| `press_key(key)` | 按下键 | `element press key` | `keyboard.press` |
| `release_key(key)` | 释放键 | `element release key` | `keyboard.release` |
| `key_combination(key_list)` | 按组合键 | `element key combination` | `keyboard.click_combination_key` |

### 3.4 屏幕操作

| API | 说明 | 对应 WinAppDriver | 对应 Hypium |
|-----|------|------------------|-------------|
| `get_screenshot()` | 获取屏幕截图 | `window screenshot` | `device screenshot` |
| `get_source()` | 获取 UI 源码 | `window source` | `device source` |
| `get_screen_size()` | 获取屏幕尺寸 | `window size` | `get display size` |
| `get_rotation()` | 获取屏幕旋转角度 | `window rotation` | `get display rotation` |

### 3.5 应用管理

| API | 说明 | 对应 WinAppDriver | 对应 Hypium |
|-----|------|------------------|-------------|
| `launch_app(app_name)` | 启动应用 | `application launch` | `app launch` |
| `close_app(app_name)` | 关闭应用 | `application close` | `app close` |

### 3.6 会话管理

| API | 说明 | 对应 WinAppDriver | 对应 Hypium |
|-----|------|------------------|-------------|
| `create_session()` | 创建会话 | `session create` | `device connect` |
| `delete_session()` | 删除会话 | `session delete` | `device disconnect` |
| `query_session()` | 查询会话状态 | `session query` | `device status` |

---

## 4. 坐标系统

### 4.1 坐标定义

- **绝对坐标**：相对于屏幕/窗口左上角的像素坐标 (x, y)
- **相对坐标**：相对于区域或屏幕的比例坐标 (0-1)

---

## 5. 下一步建议

### 5.1 MCP 工具命名

基于设计文档，建议 MCP 工具命名遵循以下格式：
```
{api_name}
```

不同平台在握手（handshake）时返回其支持的平台名称和可用工具列表，而不需要在工具名称中包含 platform 前缀。

示例：
```
click
swipe
get_source
```

### 5.2 参数 Schema

建议参数 schema 标准化：
```json
{
  "x": "number",
  "y": "number",
  "duration": "number",
  "interval": "number",
  "text": "string"
}
```

---

## 6. 完整 MCP tools 返回 JSON

### 6.1 WinAppDriver 平台

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

### 6.2 Hypium 平台

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

## 附录

### 相关资源

- `design/midscene-winapp-design.md`：WinApp 平台设计文档
- `hypium` 包：HarmonyOS 自动化测试框架
- WinAppDriver：Windows 应用自动化驱动
