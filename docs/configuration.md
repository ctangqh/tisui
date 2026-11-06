# Tisui 配置说明（configuration.md）

> 本文档覆盖 `config.yaml` **全部配置项**：含义、类型、默认值、示例。
> 快速上手见 [UserManual.md](./UserManual.md#1-运行前配置)。

---

## 目录

- [1. 配置文件位置与优先级](#1-配置文件位置与优先级)
- [2. 最小可用配置](#2-最小可用配置)
- [3. 全量配置示例](#3-全量配置示例)
- [4. 配置项详解](#4-配置项详解)
  - [4.1 model — 模型配置](#41-model--模型配置)
  - [4.2 act — ai_act 行为](#42-act--ai_act-行为)
  - [4.3 explore — ai_explore 行为](#43-explore--ai_explore-行为)
  - [4.4 logging — 日志](#44-logging--日志)
  - [4.5 runtime — 运行时环境](#45-runtime--运行时环境)
  - [4.6 prompt — 提示词本地化](#46-prompt--提示词本地化)
- [5. 环境变量](#5-环境变量)
- [6. 常见配置场景](#6-常见配置场景)
- [7. 配置排查](#7-配置排查)

---

## 1. 配置文件位置与优先级

SDK 按以下顺序查找 `config.yaml`，**找到第一个就用**：

| 顺序 | 位置 | 说明 |
|------|------|------|
| 1 | `$TISUI_CONFIG_PATH` | 环境变量指向的绝对路径，优先级最高 |
| 2 | `<workspace>/config.yaml` | 开发态工作区根目录（存在 `packages/` 时） |
| 3 | `<cwd>/config.yaml` | 当前工作目录 |
| 4 | `<PACKAGE_ROOT>/config.yaml` | 包安装目录 |
| 5 | `packages/shared/src/tisui/shared/env/config.yaml` | 包内兜底模板（安装态默认值） |

**建议**：把 `config.yaml` 放在**运行目录**，这样不同项目可以有不同配置，互不干扰。

```bash
# 想看实际加载了哪个文件
python3 -c "from tisui.shared.config import ROOT_CONFIG_YAML_PATH; print(ROOT_CONFIG_YAML_PATH)"
```

---

## 2. 最小可用配置

模型是**唯一必填项**，其余都有默认值：

```yaml
model:
  llm:
    provider: openai
    base_url: https://api.openai.com/v1
    model: gpt-4o
    max_tokens: 1500
  vision:
    provider: openai
    base_url: https://api.openai.com/v1
    model: gpt-4o
    max_tokens: 6000
```

密钥不写在 yaml 里，放 `.env`：

```bash
LLM_API_KEY=sk-xxx
VISION_API_KEY=sk-xxx      # 不填则复用 LLM_API_KEY
```

**LLM 和 Vision 用同一个模型时，`vision` 段可以整段省略**——所有字段会自动继承 `llm` 的值。

---

## 3. 全量配置示例

完整的、带注释的配置模板见项目根目录的 [`config.yaml`](../config.yaml)。下面是它的内容：

```yaml
# -----------------------------------------------------------------------------
# 模型配置（必填，SDK 核心依赖）
# -----------------------------------------------------------------------------
model:
  # ===== 语言模型：ai_act 规划、结构化问答、位置推断 =====
  llm:
    provider: openai
    base_url: https://api.openai.com/v1
    model: gpt-4o
    temperature: 0.0
    max_tokens: 1500
    timeout: 60
    max_retries: 3

  # ===== 视觉模型：截图定位，核心能力 =====
  # 未配置的字段自动继承 llm 的值
  vision:
    provider: openai
    base_url: https://api.openai.com/v1
    model: gpt-4o
    temperature: 0.0
    max_tokens: 6000
    timeout: 60
    max_retries: 3

  # ===== 全局兜底 =====
  timeout: 60
  max_retries: 3

# -----------------------------------------------------------------------------
# ai_act 行为（一句话多步编排）
# -----------------------------------------------------------------------------
act:
  cycle_limit: 5
  total_timeout: 900

# -----------------------------------------------------------------------------
# ai_explore 行为（自主探索）
# -----------------------------------------------------------------------------
explore:
  max_cycles: 50
  total_timeout: 600
  max_depth: null
  forbidden_enabled: true

# -----------------------------------------------------------------------------
# 日志
# -----------------------------------------------------------------------------
logging:
  level: INFO
  file_path: logs/tisui.log

# -----------------------------------------------------------------------------
# 运行时环境
# -----------------------------------------------------------------------------
runtime:
  env: dev
  debug: false
  workspace_root: .
  core_package_root: packages/core
  cache_path: .cache
  report_path: output/reports
  env_files:
    - .env

# -----------------------------------------------------------------------------
# Prompt 本地化
# -----------------------------------------------------------------------------
prompt:
  default_locale: zh-CN
  locale_fallbacks:
    zh: zh-CN
    en: en-US
```

---

## 4. 配置项详解

### 4.1 `model` — 模型配置

模型配置分三层，**后者覆盖前者**：

```
model.timeout / model.max_retries        ← 全局兜底
    ↓ 被覆盖
model.llm.*                              ← 语言模型
    ↓ 被继承（vision 没写时）
model.vision.*                           ← 视觉模型
```

#### `model.llm` — 语言模型

用于：`ai_act` 的任务规划、位置推断（阶段 0）、结构化问答、结束条件解析。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `provider` | string | `openai` | 供应商标识，仅作记录；实际协议走 OpenAI 兼容 |
| `base_url` | string | `https://api.openai.com/v1` | 服务端点 |
| `model` | string | `gpt-4o` | 模型名 |
| `temperature` | float | 不传 | 采样温度。**不填则请求里不带该参数**，由服务端决定 |
| `max_tokens` | int | 不传 | 单次最大输出。不填则不带该参数 |
| `timeout` | int | 继承 `model.timeout`（60） | 单次请求超时（秒） |
| `max_retries` | int | 继承 `model.max_retries`（3） | 失败重试次数 |

**示例**：接豆包

```yaml
model:
  llm:
    provider: doubao
    base_url: https://ark.cn-beijing.volces.com/api/v3
    model: doubao-seed-1-6-250615
    temperature: 0.1
    max_tokens: 1500
```

**示例**：接本地 vLLM

```yaml
model:
  llm:
    provider: openai
    base_url: http://127.0.0.1:8000/v1
    model: Qwen/Qwen2.5-32B-Instruct
    max_tokens: 2048
    timeout: 120          # 本地推理慢，调大超时
```

#### `model.vision` — 视觉模型

用于：截图定位（核心能力）、全页控件识别、探索决策。

**所有字段都可省略，省略时自动继承 `llm` 的对应值。**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `provider` | string | 继承 `llm.provider` | |
| `base_url` | string | 继承 `llm.base_url` | |
| `model` | string | 继承 `llm.model` | |
| `temperature` | float | 继承 `llm.temperature` | 视觉任务建议固定 0 |
| `max_tokens` | int | 继承 `llm.max_tokens` | **建议单独调大**，视觉输出含坐标列表 |
| `timeout` | int | 继承 `model.timeout` | |
| `max_retries` | int | 继承 `model.max_retries` | |

**为什么要分开配**：

```yaml
model:
  llm:
    model: gpt-4o-mini       # 文本任务用便宜模型
    max_tokens: 1500
  vision:
    model: gpt-4o            # 视觉定位用强模型
    max_tokens: 6000
```

一次 `ai_act` 可能调用 LLM 3-5 次、Vision 2-4 次，分开配能显著降本。

#### `model.timeout` / `model.max_retries`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `timeout` | int | 60 | 全局请求超时（秒），`llm`/`vision` 都没写时生效 |
| `max_retries` | int | 3 | 全局重试次数 |

---

### 4.2 `act` — ai_act 行为

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cycle_limit` | int | 5 | 最大重规划轮次。一轮 = 规划 → 执行 → 观察。任务复杂时调大 |
| `total_timeout` | float | 900.0 | 单任务墙钟上限（秒）。超时抛异常并终止 |

```yaml
act:
  cycle_limit: 8          # 复杂多步任务
  total_timeout: 1800     # 30 分钟
```

**调用时可覆盖**（优先级：调用参数 > 配置）：

```python
app.ai_act("...", cycle_limit=3, total_timeout=300)
```

---

### 4.3 `explore` — ai_explore 行为

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_cycles` | int | 50 | 最大探索轮次。一轮 = 观察 + 决策 + 执行一个动作 |
| `total_timeout` | float | 600.0 | 探索墙钟上限（秒） |
| `max_depth` | int \| null | null | 最大页面跳转深度。`null` = 不限制 |
| `forbidden_enabled` | bool | true | 危险词拦截开关（详见下文） |

#### `forbidden_enabled` — 危险词拦截开关

`ai_explore` 内置一份危险词黑名单（28 个词，见 `agent/explore/prompts.py` 的 `DANGEROUS_KEYWORDS`）：

```
删除 清空 支付 购买 发送 提交订单 卸载 恢复出厂 注销 退出登录 关机 重启
delete remove clear pay purchase buy send submit order uninstall
factory reset logout log out sign out shutdown reboot restart
```

命中黑名单的目标**强制不点击**，并记一条 `forbidden-hit` anomaly。

| 配置值 | 行为 |
|--------|------|
| `true`（默认） | 内置黑名单 + 调用时传入的 `forbidden` 合并生效 |
| `false` | **关闭内置黑名单**；调用时显式传入的 `forbidden` 仍然生效 |
| 缺失 / 非 bool | 回退 `true`（向后兼容） |

```yaml
explore:
  forbidden_enabled: false
```

**设计取舍**：关闭开关**只影响内置黑名单**，不影响调用方显式传入的 `forbidden`——那是业务层的显式安全意图，不该被全局开关抹掉。

```python
# 全局关掉内置黑名单后，仍可精确控制
app.ai_explore(..., forbidden=["支付", "提交订单"])
```

| 什么时候关 | 什么时候别关 |
|-----------|------------|
| 测试环境要验证「删除/清空」流程本身 | 生产环境探索任务 |
| 需要探索设置页的「恢复出厂设置」入口 | 只读巡检 |
| 内部工具的完整功能遍历 | 给非技术同事用的工具 |

**注意**：关掉后，`ai_explore` 有可能真的点到「删除」按钮。**务必先确认有回滚手段**（测试环境、快照、可重建的数据）。

#### `max_depth` 用法

只在 `strategy="depth-first"` 时起作用：

```python
app.ai_explore(
    "遍历设置页所有子菜单",
    strategy="depth-first",
    backtrack=True,
)
```

```yaml
explore:
  max_depth: 3      # 最多下钻 3 层页面
```

---

### 4.4 `logging` — 日志

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `level` | string | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR`，自动转大写 |
| `file_path` | string | `logs/tisui.log` | 日志文件路径，相对路径以配置文件所在目录为基准 |

```yaml
logging:
  level: DEBUG                              # 排查问题时开
  file_path: /var/log/tisui/tisui.log       # 绝对路径
```

---

### 4.5 `runtime` — 运行时环境

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `env` | `dev` \| `prod` | 自动判断 | 运行环境。有 `packages/` 目录时判 dev，否则 prod。可用 `TISUI_ENV` 覆盖 |
| `debug` | bool | false | 调试模式，输出更详细的执行轨迹 |
| `workspace_root` | string | `.` | 工作区根目录 |
| `core_package_root` | string | dev 态 `packages/core`，prod 态 `.` | core 包位置 |
| `cache_path` | string | `<cwd>/.cache` | 缓存目录（定位缓存、页面指纹等） |
| `report_path` | string | `<workspace>/output/reports` | 测试报告输出目录 |
| `env_files` | list[string] | `[".env"]` | `.env` 文件列表，按顺序加载，后面的覆盖前面的 |

**相对路径规则**：`workspace_root` / `core_package_root` / `cache_path` / `report_path` 若不是绝对路径，**以配置文件所在目录为基准解析**。

```yaml
runtime:
  env: prod
  debug: false
  cache_path: /data/tisui/cache
  report_path: /data/tisui/reports
  env_files:
    - .env
    - .env.local          # 本地覆盖，放后面
```

#### `env` 取值说明

| 值 | 含义 | 影响 |
|----|------|------|
| `dev` | 开发态 | `core_package_root` 默认 `packages/core`，`.env` 会找多个位置 |
| `prod` | 安装态 | `core_package_root` 默认 `.`，`.env` 只找 cwd 和包目录 |

**同名别名**：`development` → `dev`，`production` → `prod`。

**旧字段兼容**：顶层 `environment: dev` 等价于 `runtime.env`，但优先级更低。

---

### 4.6 `prompt` — 提示词本地化

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `default_locale` | string | `zh-CN` | 默认提示词语言 |
| `locale_fallbacks` | map | `{}` | 语言回退链，如 `zh → zh-CN` |

内置提示词目录：`packages/core/src/tisui/resource/prompt/{zh-CN,en-US}/`

```yaml
prompt:
  default_locale: en-US
  locale_fallbacks:
    zh: zh-CN
    en: en-US
```

**回退逻辑**：先找 `default_locale` 对应目录，找不到则按 `locale_fallbacks` 链逐级回退。

---

## 5. 环境变量

配置里的 `api_key` **不在 yaml 里写**，用环境变量或 `.env`：

| 变量 | 必填 | 说明 |
|------|------|------|
| `LLM_API_KEY` | ✅ | 语言模型密钥 |
| `VISION_API_KEY` | ⬜ | 视觉模型密钥。不填则复用 `LLM_API_KEY` |
| `TISUI_CONFIG_PATH` | ⬜ | 指定 config.yaml 绝对路径（优先级最高） |
| `TISUI_ENV` | ⬜ | 覆盖 `runtime.env`（`dev` / `prod`） |
| `TISUI_ENV_FILE` | ⬜ | 指定 `.env` 文件路径，覆盖 `runtime.env_files` |

**`.env` 示例**（参考 `packages/core/.env.sample`）：

```bash
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
VISION_API_KEY=sk-yyyyyyyyyyyyyyyy
```

**注意**：`.env.sample` 里的 `LLM_PROVIDER` / `LLM_MODEL` / `MODEL_TIMEOUT` 等**已经废弃**，现在统一在 `config.yaml` 里配。保留这些变量不会报错，但不会生效。

---

## 6. 常见配置场景

### 场景 A：全用 OpenAI

```yaml
model:
  llm:
    provider: openai
    base_url: https://api.openai.com/v1
    model: gpt-4o
    max_tokens: 1500
  vision:
    model: gpt-4o
    max_tokens: 6000
```

```bash
LLM_API_KEY=sk-xxx
```

### 场景 B：文本便宜 + 视觉强

```yaml
model:
  llm:
    provider: deepseek
    base_url: https://api.deepseek.com/v1
    model: deepseek-chat
    max_tokens: 1500
  vision:
    provider: doubao
    base_url: https://ark.cn-beijing.volces.com/api/v3
    model: doubao-seed-1-6-250615
    max_tokens: 6000
```

```bash
LLM_API_KEY=sk-deepseek-xxx
VISION_API_KEY=xxx-volces-key
```

### 场景 C：本地全离线

```yaml
model:
  llm:
    provider: openai
    base_url: http://127.0.0.1:8000/v1
    model: Qwen/Qwen2.5-32B-Instruct
    max_tokens: 2048
    timeout: 120
    max_retries: 1
  vision:
    base_url: http://127.0.0.1:8001/v1
    model: Qwen/Qwen2.5-VL-7B-Instruct
    max_tokens: 6000
    timeout: 180
```

### 场景 D：测试环境关掉危险词拦截

```yaml
explore:
  forbidden_enabled: false
  max_cycles: 30
```

配合显式白名单更安全：

```python
app.ai_explore(..., forbidden=["恢复出厂设置"])
```

### 场景 E：CI 环境

```yaml
runtime:
  env: prod
  debug: false
  report_path: /build/reports
  cache_path: /tmp/tisui-cache

act:
  total_timeout: 300      # CI 不允许长任务
```

```bash
export TISUI_CONFIG_PATH=/build/tisui-config.yaml
export LLM_API_KEY=${{ secrets.LLM_KEY }}
export VISION_API_KEY=${{ secrets.VISION_KEY }}
```

---

## 7. 配置排查

### 7.1 确认加载了哪个配置文件

```python
from tisui.shared.config import ROOT_CONFIG_YAML_PATH
print(ROOT_CONFIG_YAML_PATH)
```

### 7.2 打印生效的配置

```python
from tisui.shared.config import settings

print('LLM   :', settings.llm_config)
print('Vision:', settings.vision_config)
print('Act   :', settings.act_config)
print('Explore:', settings.explore_config)
print('Runtime:', settings.runtime_environment)
print('Logging:', settings.logging_config)
```

### 7.3 常见问题

| 症状 | 原因 | 解决 |
|------|------|------|
| 改了配置不生效 | 加载的不是你以为的那个文件 | 用 7.1 确认路径 |
| `model` 配置没生效，但 `prompt` 生效 | 改的是包内 `env/config.yaml` | 两套配置已统一，改根目录 `config.yaml` 即可 |
| `api_key` 读不到 | `.env` 路径不对 | 用 `runtime.env_files` 或 `TISUI_ENV_FILE` 指定 |
| 超时频繁 | 模型慢 / `timeout` 太小 | 调大 `model.timeout` 或分端配置的 `timeout` |
| `forbidden_enabled: false` 不生效 | 改的是包内配置文件 | 改根目录 `config.yaml` |
| YAML 解析错误 | 冒号后没空格、缩进用 Tab | YAML 缩进只能用空格 |

### 7.4 YAML 常见坑

```yaml
# ❌ 冒号后没空格
model:llm:

# ✅
model:
  llm:

# ❌ 用了 Tab 缩进
model:
	llm:

# ✅ 两个空格
model:
  llm:

# ❌ 布尔值没加引号（YAML 1.1 会把 on/off/yes/no 当布尔）
flag: yes        # 被解析成 True

# ✅
flag: "yes"
```

---

## 相关文档

- [UserManual.md](./UserManual.md) — 用户手册（SDK 用法、设备接入、示例）
- [../config.yaml](../config.yaml) — 全量配置模板（带注释）
- [../packages/core/.env.sample](../packages/core/.env.sample) — 环境变量模板
