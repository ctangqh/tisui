# tisui 用户手册（UserManual）

> tisui 是一个**视觉优先**的 Python UI 自动化 SDK：用自然语言描述界面元素，由视觉大模型（VLM）在屏幕截图上完成定位，再驱动底层设备执行点击 / 输入 / 按键等操作。一套 SDK 同时支持 Web（Playwright）、Windows 原生（WinAppDriver / PyAutoGUI）、HarmonyOS（Hypium）等设备。

写脚本只需三步：**创建设备 → 进入 `tisui` 门面 → 调 `ai_*` 方法**。

---

## 1. 运行前配置

SDK 通过视觉/语言模型完成定位与问答，**运行前必须配置好模型 provider**。项目根的 `config.yaml` 结构如下（未配置的项取默认值）：

```yaml
model:
  llm:                 # 语言模型 (ai_act 规划、结构化问答等)
    provider: doubao   # doubao / deepseek / openai (通用 OpenAI 协议)
    base_url: https://ark.cn-beijing.volces.com/api/coding/v3
    model: Doubao-Seed-2.0-pro
    temperature: 0.1
    max_tokens: 1500
  vision:              # 视觉模型 (截图定位, 核心能力)
    provider: doubao
    base_url: https://ark.cn-beijing.volces.com/api/coding/v3
    model: Doubao-Seed-2.0-pro
    max_tokens: 6000
  timeout: 60
  max_retries: 3

act:
  cycle_limit: 5       # ai_act 最大重规划轮次 (ai_act 未显式传参时使用)
  total_timeout: 900   # ai_act 单任务墙钟上限(秒)
```

- 密钥放在 `.env`（参考 `.env.sample`）：`VISION_API_KEY`、`LLM_API_KEY`。
- `provider: openai` 可接入任何兼容 OpenAI `/v1/chat/completions` 协议的端点（官方 OpenAI / 中转代理 / 本地 vLLM 等），用 `base_url` 指定端点。
- `config.yaml` 会作为包内兜底配置；在**运行目录**放一份 `config.yaml` 可覆盖，或用 `TISUI_CONFIG_PATH` 指向自定义配置文件。

---

## 2. 快速上手

```python
from tisui.device.playwright import PlaywrightDevice
from tisui.report import instrument, start_run
from tisui.sdk.tisui import tisui

device = PlaywrightDevice(headless=False, start_url="https://www.bing.com")

with tisui(device, debug=False) as app, start_run("我的用例", device=device) as run:
    app = instrument(app, run)     # 包装后 ai_* 自动写报告 (不需要报告可省去这两行)
    app.ai_input("搜索框", "midscene")
    app.ai_tap("搜索按钮")

print(f"报告: {run.run_dir}\\report.html")
```

- `with tisui(device) as app`：进入时自动 `launch()` 设备，退出时自动 `close()`。
- `start_run(...) as run`：即使中途异常也会落盘报告；`run.run_dir` 是本次运行的输出目录。
- `instrument(app, run)`：包装门面后每个 `ai_*` 自动记一步。

---

## 3. SDK 方法参考（`tisui` 门面）

### 3.1 门面构造

```python
tisui(device, models=None, debug=False, *, wait_after_action=0.5, options=None)
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `device` | 必填 | 任一设备实例（见第 4 节） |
| `debug` | `False` | 开启定位调试（产出更详细的阶段可视化） |
| `wait_after_action` | `0.5` | 每次动作后的默认等待秒数（每个 `ai_*` 调用也可用 `wait_after=` 单独覆盖） |

### 3.2 交互（定位 + 操作）

| 方法 | 说明 | 返回 |
| --- | --- | --- |
| `ai_locate(action_text, **kw)` | 只定位，不操作 | `LocatedElement` |
| `ai_tap(action_text, **kw)` | 定位并点击（别名 `ai_click`） | `LocatedElement` |
| `ai_doubleclick(action_text, **kw)` | 定位并双击（触摸设备为双击手势） | `LocatedElement` |
| `ai_rightclick(action_text, **kw)` | 定位并右键单击（呼出上下文菜单） | `LocatedElement` |
| `ai_input(action_text, text, **kw)` | 定位输入框 → 点击聚焦 → 输入文本 | `LocatedElement` |
| `ai_clear(action_text, **kw)` | 定位输入框并清空内容（聚焦 → 全选 → 删除） | `LocatedElement` |
| `ai_scroll(direction="down", distance=500, action_text=None, **kw)` | 四向滚动，带滚动边界识别（详见 3.3） | `ScrollResult` |
| `ai_keyboard_press(key, action_text=None, **kw)` | 把按键发给当前焦点元素 | `LocatedElement`/`None` |

`key` 支持通用名（大小写不敏感）：`enter`/`return`、`backspace`、`delete`、`tab`、`escape`/`esc`、`space`、方向键 `up/down/left/right`、`home`、`end`、`pageup`、`pagedown` 等。

```python
app.ai_clear("搜索输入框")                       # 清空后重新输入
app.ai_input("搜索输入框", "新的关键词")
app.ai_doubleclick("文件列表中的报表.xlsx")        # 双击打开
app.ai_rightclick("文件列表中的第一项")            # 右键呼出菜单
app.ai_tap("右键菜单中的重命名")
app.ai_keyboard_press("Enter")                   # 把回车发给当前焦点
```

### 3.3 滚动 `ai_scroll`

```python
result = app.ai_scroll(direction="down", distance=500, action_text=None, check_boundary=True)
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `direction` | `"down"` | 滚动方向：`up` / `down` / `left` / `right` |
| `distance` | `500` | 滚动距离（像素），必须为正数 |
| `action_text` | `None` | 可选；传入时先定位该元素，滚动作用于其所在区域（内层滚动区） |
| `check_boundary` | `True` | 是否做边界识别；动态页面（视频/动画）易误判时可关掉 |

返回 `ScrollResult`：

| 字段 | 含义 |
| --- | --- |
| `moved` | 是否真的滚动了；`False` 表示已在边界（如已到顶部时向上滚） |
| `direction` / `distance` | 实际执行的方向与距离 |
| `element` | 传了 `action_text` 时的定位命中，否则 `None` |

```python
app.ai_scroll("down")                                  # 页面向下滚 500px
app.ai_scroll("down", distance=1000)                   # 指定距离
app.ai_scroll("up", action_text="商品列表")             # 在指定元素区域内滚
while app.ai_scroll("down").moved:                     # 一直滚到底
    ...
if not app.ai_scroll("up").moved:
    print("已经在顶部")
```

### 3.4 查询（读取界面）

| 方法 | 说明 | 返回 |
| --- | --- | --- |
| `ai_query(query, **kw)` | 从截图提取结构化数据（可要求返回对象 `{title, url}` 之类） | `Any` |
| `ai_boolean(query)` | 自然语言是/否判断 | `bool` |
| `ai_number(query)` | 提取一个数值 | `float` |
| `ai_string(query)` | 提取一个字符串 | `str` |

```python
price = app.ai_number("页面中商品的价格")
titles = app.ai_query("当前可见结果列表, 返回 [{title, url}]")
```

### 3.5 等待与断言

| 方法 | 说明 |
| --- | --- |
| `ai_wait_for(condition, *, timeout=15.0, interval=1.0)` | 轮询截图直到条件满足，超时抛出 |
| `ai_assert(condition)` | 对当前界面做一次视觉断言，不满足抛出 |

```python
app.ai_wait_for("出现结果列表")
app.ai_assert("页面右上角显示已登录")
```

### 3.6 动作编排 `ai_act`（一句话多步）

```python
summary = app.ai_act(
    "在搜索框输入 midscene 并回车，等结果出现后提取第一条标题作为结果",
    context="这是搜索页，提交后需要等待加载",
    cycle_limit=5,        # 可选，覆盖 config.yaml 的 act.cycle_limit
    total_timeout=900,    # 可选，覆盖 config.yaml 的 act.total_timeout
)
```

- `instruction`：必填，一句自然语言指令；规划器在 plan-act-observe 循环中自动拆解为多步动作并逐步执行。
- `context`：可选，背景知识（如页面结构、提交后需等待）。
- 返回规划器给出的最终结论（`summary`）；任务无法完成或超过轮次/墙钟上限时抛 `ActError`。
- 执行过程中检测到模态弹窗会**优先处理弹窗**再继续任务：协议/条款类弹窗自动确认，删除/支付等危险弹窗自动跳过不点击，同一弹窗反复出现导致任务被阻塞时抛 `ActError`。

### 3.7 自主探索 `ai_explore`

```python
result = app.ai_explore(
    "找出页面所有导航入口并点击进入, 收集各页面标题",
    end_condition="已收集到 5 个页面",   # 可选, 满足时 status=completed
    strategy="depth-first",              # 可选, 深度优先: 沿分支深入到底回溯
    max_depth=5,                         # 可选, 最大探索深度(页面层级), 默认不限
    max_cycles=20,                      # 可选, 最大轮数
    total_timeout=600,                  # 可选, 墙钟上限(秒)
    max_tokens=5000,                    # 可选, token 预算, 耗尽时 status=exhausted
    context="",                         # 可选, 背景知识
    forbidden=["退出登录", "删除"],       # 可选, 追加危险词, 命中的目标强制不操作
    backtrack=True,                     # 允许规划器返回上一页继续探索 (depth-first 必需)
)
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `goal` | 必填 | 探索目标，不能为空 |
| `end_condition` | `""` | 提前结束条件；满足时探索以 `completed` 收尾。**双通道判定**：引号关键词（如 `'开发者选项'`）与数字+单位（如 `3 个页面`/`2 个发现`/`3 个开关`）由框架客观判定并在动作后立即收尾，其余描述由模型评估；模型误报 `completed` 且客观条件未满足时会被框架拒绝并继续探索 |
| `strategy` | `"coverage"` | 探索策略：`coverage`（默认，优先覆盖未访问元素）/ `depth-first`（沿一条分支深入，到底后回溯最近分叉点继续；需 `backtrack=True`，否则报错） |
| `max_depth` | `None` | 最大探索深度（页面跳转层级），`None` 不限制；当前深度达上限时不再进入新页面，只探索本页元素或回溯；越界时自动返回并记一条 finding |
| `max_cycles` / `total_timeout` / `max_tokens` | 取 config | 轮次 / 墙钟 / token 预算上限 |
| `forbidden` | 内置黑名单 | 危险词清单，与内置黑名单合并；命中"删除/退出登录/支付"等词的目标强制不点击并记 anomaly |
| `backtrack` | `True` | 允许规划器用 back 返回上一页继续探索 |
| `memory_cache` / `reset_memory` | 预留 | Phase 2 接入，当前传 `memory_cache` 仅警告并按纯内存探索执行 |

返回 `ExploreResult`：

| 字段 | 含义 |
| --- | --- |
| `status` | `completed`（满足结束条件）/ `exhausted`（探索完毕或预算耗尽）/ `timeout` / `cycle_exceeded` / `failed` |
| `end_condition_met` | 是否因满足结束条件而结束 |
| `total_cycles` / `duration_ms` / `new_pages` | 执行轮数 / 耗时 / 访问到的页面数 |
| `findings` | `list[ExploreFinding]`：发现的异常、有价值页面、提取数据（`type` 为 `element`/`page`/`anomaly`/`data`） |
| `path` | `list[ExploreNode]`：每轮一步的轨迹（`action`/`target`/`from_page_id`/`to_page_id`/`is_new_page`/`depth`/`error`），`depth` 为动作执行前的页面深度（起点页 0，仅 depth-first 生效） |
| `coverage` | `pages_visited` / `elements_interacted` / `total_findings` / `anomalies` |
| `token_usage` / `error` | token 消耗统计 / 失败原因（`None` 表示无） |

```python
result = app.ai_explore("浏览设置页, 找出所有开关项")
for f in result.findings:
    print(f.type, f.description, f"出现 {f.occurrences} 次")
print(result.coverage)
```

> 行为说明：`anomaly` 类发现需**二次确认**——同一异常出现两次才计入最终结果（避免单次误报）；探索中检测到模态弹窗会自动处理——协议类弹窗自动确认、危险按钮被黑名单拦截并记 anomaly、处理失败自动放弃继续探索。

### 3.8 命中结果 `LocatedElement`

交互类方法返回 `LocatedElement`，常用字段：

| 字段 | 含义 |
| --- | --- |
| `action_point` | 实际操作点 `[x, y]`（raw 屏幕像素坐标） |
| `bbox` | 元素包围盒 `[left, top, right, bottom]`（raw 像素） |
| `confidence` | 命中置信度（0~1） |
| `text` | 元素文本（如结果标题） |
| `description` / `type` | 描述与类型 |

```python
box = app.ai_input("Bing 页面顶部的搜索输入框", "midscene")
print(box.action_point, box.confidence)
```

---

## 4. 设备接入

所有设备都实现同一套原语（`launch/close`、`screenshot`、`click`、`input_text`、`press_key`、`scroll` 等），坐标一律为**截图像素坐标**。日常使用只需构造设备并交给 `tisui` 门面，原语由 `ai_*` 自动调用。

### 4.1 PlaywrightDevice（Web）

```python
from tisui.device.playwright import PlaywrightDevice

device = PlaywrightDevice(
    headless=False,            # 依赖真实渲染/焦点的页面建议 headed
    viewport=(1280, 900),
    start_url="https://www.bing.com",
)
```

- `device_scale_factor=1`，截图像素与 CSS 像素一致。
- 可通过 `device.page` 拿到 Playwright `Page`（如 `page.wait_for_timeout`、`page.wait_for_selector`）；支持 `goto(url)`。

### 4.2 WinAppDriverDevice（Windows 原生）

```python
from tisui.device.winappdriver import WinAppDriverDevice

device = WinAppDriverDevice()   # 默认 Root 会话, 控制整个桌面
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `app` | `"Root"` | `Root`=整个桌面；也可传 exe 路径或 AppUserModelId 直接启动某应用 |
| `app_arguments` / `app_working_dir` | `None` | 启动参数 / 工作目录 |
| `app_top_level_window` | `None` | 附着到已有窗口句柄 |
| `server_url` | `http://127.0.0.1:4723` | WinAppDriver 服务地址 |

- 默认 `Root` 会话下截图为全桌面、点击按绝对屏幕坐标，二者一致，最适合视觉定位。
- `input_text` **必须**带 `position`（先点击聚焦再输入，`ai_input` 会自动处理）；`goto` 不支持（启动应用请用 `app` 参数）。

### 4.3 PyAutoGUIDevice（Windows 桌面键鼠模拟）

```python
from tisui.device.autogui import PyAutoGUIDevice

device = PyAutoGUIDevice()                      # 全桌面
device = PyAutoGUIDevice(window_title="记事本")  # 绑定到指定窗口
```

- 不依赖 WinAppDriver 服务，直接模拟真实键鼠。
- 支持窗口绑定（`hwnd` / `window_title` / `window_class`），动作前自动把目标窗口带到前台。
- 操作期间请勿人为移动鼠标 / 切换前台窗口。

### 4.4 HypiumDevice（HarmonyOS）

```python
from tisui.device.hypium import HypiumDevice

device = HypiumDevice(
    connector="hdc",
    start_app="com.example.app",   # 可选, 连接后自动拉起
)
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `device_sn` | `None` | 指定设备序列号 |
| `connector` / `connector_server` | `"hdc"` / `None` | 连接器；`(host, port)` 远程连接器 |
| `report_path` / `log_level` | `None` / `"info"` | Hypium 报告路径 / 日志级别 |
| `start_app` | `None` | 连接后自动启动的包名 |

- `input_text` / `ai_clear` 必须带位置（`ai_input` / `ai_clear` 会自动定位）；`ai_rightclick` 仅对外接鼠标的设备（平板/PC）有效；`goto` 不支持（启动应用用 `start_app`）。
- 底层 `hypium` 框架截图产生的 `tmp_hypium/` 中间目录由 SDK 自动重定向到缓存目录并在 `launch()` 时清空、`close()` 时删除。

---

## 5. 测试报告

```python
from tisui.report import instrument, start_run

with tisui(device) as app, start_run("用例名称", device=device) as run:
    app = instrument(app, run)   # 关键: 包装后每个 ai_* 自动记一步
    app.ai_tap("按钮")

print(f"报告: {run.run_dir}\\report.html")
```

- `start_run(name, *, device=None, output_root=None)`：开启运行上下文，自动 finalize；异常也会落盘。可用 `output_root=Path("...")` 自定义报告根目录（默认读 `runtime.report_path`）。
- `instrument(app, run)`：零侵入包装门面，采集每个 `ai_*` 步骤（截图 + 命中信息），产出 `report.json` + `report.html`。
- 报告路径为 `<report_path>/<run_id>/`（`<run_id>` 形如 `20260715_165556_f3742f`）。
- 报告页面支持步骤回放：动作类步骤展示操作前后截图与命中元素的 BBOX 标注；`ai_act` 步骤可逐帧回放每一轮动作。

> 注意：一定要用 `instrument` 返回的对象替换原 `app`（`app = instrument(app, run)`），否则不会记步。

---

## 6. 完整示例

### 6.1 手工编排（Web）

```python
device = PlaywrightDevice(headless=False, viewport=(1280, 900), start_url="https://www.bing.com")
with tisui(device) as app, start_run("Bing 搜索", device=device) as run:
    app = instrument(app, run)
    app.ai_input("Bing 页面顶部的搜索输入框", "midscene")
    app.ai_keyboard_press("Enter")
    first = app.ai_locate("搜索结果列表中的第一条结果标题链接")
    print("第一条结果:", first.text)
```

### 6.2 一句话编排（Web）

```python
summary = app.ai_act(
    "在页面顶部搜索框输入 midscene 并回车; 等结果页出现后, 提取第一条结果标题返回。",
    context="这是搜索页, 提交后需要等待加载。",
)
print("结论:", summary)
```

### 6.3 自主探索

```python
result = app.ai_explore(
    "探索登录后页面, 找出所有功能入口并进入, 记录每个页面的标题与异常",
    end_condition="已访问 10 个页面",
)
print("状态:", result.status, "| 发现:", len(result.findings), "| 异常:",
      result.coverage.anomalies)
```

### 6.4 Windows 原生

```python
import subprocess, time
from tisui.device.winappdriver import WinAppDriverDevice

subprocess.Popen(["calc.exe"]); time.sleep(3)     # 先开计算器, 再连 Root 保证坐标系一致
device = WinAppDriverDevice()
with tisui(device) as app, start_run("计算器 1+2", device=device) as run:
    app = instrument(app, run)
    app.ai_tap("计算器上的数字按键 1")
    app.ai_tap("计算器上的加号 + 按键")
    app.ai_tap("计算器上的数字按键 2")
    app.ai_tap("计算器上的等号 = 按键")
    print("结果:", app.ai_string("计算器结果显示区域当前显示的数字"))
```

### 6.5 滚动加载（Web）

```python
# 逐屏向下滚, 直到页面到底, 期间收集每屏的第一条标题
titles = []
while True:
    titles.append(app.ai_string("当前可见区域第一条结果的标题"))
    if not app.ai_scroll("down").moved:
        break
```

### 6.6 用 `ai_explore` 安装 Windows 程序

```python
import subprocess, time
from pathlib import Path
from tisui.device.winappdriver import WinAppDriverDevice
from tisui.report import instrument, start_run
from tisui.sdk.tisui import tisui

installer = Path(r"D:\downloads\myapp_setup.exe")
subprocess.Popen([str(installer)])      # 1) 启动安装程序
time.sleep(3)                           #    等待安装向导窗口出现

device = WinAppDriverDevice()           # 2) Root 会话: 全桌面截图, 与点击坐标系一致
with tisui(device) as app, start_run("安装 myapp", device=device) as run:
    app = instrument(app, run)

    result = app.ai_explore(            # 3) 自主探索走完安装向导
        # goal: 探索目标 (必填) —— 一句话说清要做什么, 模型会自行分步
        "安装 myapp 软件: 跟随安装向导逐步点击下一步/安装/完成等按钮, 接受许可协议, "
        "不修改任何安装选项",

        # end_condition: 提前结束条件 (可选) —— 满足时 status=completed
        # 写法: 描述"完成"时界面上可观察的特征, 模型在每轮截图后判断
        end_condition="安装向导进入最后完成页面, 界面上出现[完成]按钮或'安装已完成'字样",

        # 预算与上限: 防止安装卡死/异常时无限跑下去
        max_cycles=30,                  # 最大轮数 (安装向导通常十几步, 留足余量)
        total_timeout=900,              # 墙钟上限 15 分钟
        max_tokens=8000,                # token 预算, 耗尽时 status=exhausted

        # context: 背景知识 (可选) —— 帮助模型理解当前场景
        context="这是 Windows 桌面安装向导, 每一步界面都不同; "
                "使用默认安装路径即可, 不要修改任何选项",

        # forbidden: 危险词清单 (可选, 与内置黑名单合并)
        # 命中这些词的目标会被强制跳过不点击, 避免误终止安装
        forbidden=["卸载", "删除", "取消"],

        # backtrack: 是否允许规划器返回上一页 (安装向导不可回退)
        backtrack=False,
    )

    # 4) 读取结果
    print("状态:", result.status, "| 完成:", result.end_condition_met,
          "| 轮数:", result.total_cycles, "| 耗时(s):", round(result.duration_ms / 1000, 1))
    for f in result.findings:
        print("发现:", f.type, f.description)
print("报告:", f"{run.run_dir}\\report.html")
```

参数与结束条件要点：

- **`goal`**（必填）：一句话说清要做什么。安装类目标建议写成"跟随向导逐步点击…"而不是"点击某个按钮"，模型会自动分步。
- **`end_condition`**（关键）：描述**完成时界面的可观察特征**（如"出现[完成]按钮"），模型每轮截图判断，满足即 `completed` 提前收尾；不传则一直探索到所有可达页面覆盖完（`exhausted`）或预算耗尽。
- **`forbidden`**：安装向导常见"取消/上一步"按钮，加入清单后模型绝不点击，防止误终止安装。
- **`backtrack=False`**：安装向导不允许回退页面，关掉 back 可避免规划器做无意义的返回。
- 运行前提：先启动 WinAppDriver 服务（`WinAppDriver.exe`）；安装全程保持安装窗口在前台。

---

## 7. 使用要点

- **坐标即截图像素**：所有 `LocatedElement.action_point / bbox` 都是当前截图的原始像素坐标。保证「截图范围」与「操作坐标系」一致是稳定的前提（Web 用 `device_scale_factor=1`，Windows 建议 Root 全桌面）。
- **headed 更稳**：依赖真实渲染 / 焦点 / 反爬的页面（如登录页、Bing），用 `headless=False`。
- **等待**：Web 可用 `device.page.wait_for_timeout / wait_for_selector`；原生设备用 `time.sleep`；语义等待用 `app.ai_wait_for("出现结果列表")`。
- **`ai_input` / `ai_clear` 自动聚焦**：Windows / HarmonyOS 的文本操作必须先点击聚焦，SDK 会自动先定位再操作，无需手动传坐标。
- **滚动边界识别**：`ai_scroll` 默认开启边界识别；页面有视频 / 动画等持续变化内容时，非 Web 设备可能把「没滚动」误判成「滚动了」，可传 `check_boundary=False` 跳过检测。
- **右键仅限指针设备**：`ai_rightclick` 在 HarmonyOS 上仅对外接鼠标的设备（平板/PC）有效。
- **别忘了 `instrument`**：不包装就没有报告记步。

---

## 8. 常见问题（FAQ）

**Q：`goto(url)` 为什么在 Windows / HarmonyOS 报 `NotImplementedError`？**
A：原生设备没有 URL 导航概念。启动应用请在构造设备时传 `app`（WinAppDriver）或 `start_app`（Hypium）。

**Q：`ai_scroll` 返回 `moved=False` 但页面明明还能滚？**
A：先确认滚动作用的区域：不传 `action_text` 时滚的是页面主滚动容器，若目标内容在内层滚动区（如弹窗、列表面板），请传 `action_text` 指到该区域内的元素。非 Web 设备靠截图对比判断，`distance` 太小（如几个像素）时画面变化可能低于判定阈值，可加大 `distance`。

**Q：`ai_act` 遇到弹窗会自动处理吗？**
A：会。执行中检测到模态弹窗会优先处理：协议/条款类弹窗自动确认，删除/支付等危险弹窗自动跳过不点击；同一弹窗反复出现导致任务被阻塞时会抛出 `ActError` 说明原因。

**Q：`ai_explore` 返回 `status="exhausted"` 是什么意思？**
A：探索完毕（所有可达页面均已覆盖）或 token 预算耗尽。`coverage` 策略由规划器判定；`depth-first` 策略由框架复核——分叉点栈已空且当前页无未访问元素才接受，否则强制继续探索；探索中超过 `max_depth` 会自动返回并记一条 "深度上限截断" 的 finding。`error` 字段会给出具体原因（如"token 预算耗尽"）。

**Q：`ai_explore` 的 `end_condition` 是怎么判定的？**
A：双通道。可客观判定的子条件由框架直接判定：引号包裹的关键词（命中页面标题/操作目标/发现描述即满足）、数字+单位（如"3 个页面"统计访问页数、"2 个发现"统计 findings、"3 个开关"统计已交互元素），条件在动作执行后立即检查并收尾，不等下一轮模型决策；无法客观化的描述（如"页面布局合理"）由模型每轮评估。模型报 `completed` 但客观条件未满足时，框架会拒绝（路径中记录 `completed 复核拒绝` 节点）并强制继续。

**Q：跑完用例后运行目录出现了 `output/reports/` 和 `<cache_path>/tmp_hypium/`，是什么？**
A：`output/reports/<run_id>/` 是测试报告产物（`report.json` + `report.html` + `screenshots/`），可用 `start_run(..., output_root=...)` 自定义根目录；`<cache_path>/tmp_hypium/` 是 Hypium 截图中间目录，SDK 在 `launch()`/`close()` 时自动清空删除，通常不应残留。两者均已被 `.gitignore` 忽略。
