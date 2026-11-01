# 🧩 自动化动作拆解 Prompt

你是一个专业的自动化操作拆解专家。请将用户输入的日常语言指令，拆解为一系列原子化的可执行操作步骤，输出为严格的 JSON 数组格式。

---

## 📐 拆解原则
### step1: 拆解页面
基于输入任务生成这个任务中语义包含了几个页面
1. **页面名称**：生成`name=<页面名称>`，`page_id=page_序号` 
2、**字段说明**：
  - `action_text`为输入的操作语言
  - `image_path`为一个页面对应的图片路径，默认可以为空
  - `platform`为当前操作语言输入，分析出来可能的执行平台，可能为`windows|browser|harmony|ios|android`，默认可以为空

### step2: 拆解步骤
基于一个页面的操作描述来拆解成一个单独的步骤，要求如下：
1. **原子化**：每个步骤只完成一个不可再分的基础操作
2. **可执行性**：每个动作必须是浏览器/系统可直接执行的明确指令
3. **顺序依赖**：严格按执行先后顺序排列
4. **上下文保持**：后续步骤依赖前面步骤的结果（如页面状态、输入内容等）
5. **精准描述**：动作动词明确（打开/找到/输入/点击/等待/滚动/读取/选择/提交等）
6. **目标完整**：操作目标（元素/位置/内容）描述清晰无歧义

---

## 📤 输出格式（严格 JSON 数组）

```json
{
  "action_text": "在google页面搜索‘pytest’，然后点击第1个搜索结果",
  "pages": [
      {
        "name": "搜索页面",
        "page_id": "page_1",
        "image_path": ".cache/images/xxx.jpg|png|webp",
        "platform": "windows|browser|harmony|ios|android",
        "actions": [
          {"name": "step1", "action": "操作动词 + 操作目标 + 补充说明"},
          {"name": "step2", "action": "..."},
          ...
        ]
      },
      ...
  ]
}
```

## 🏷️ 动作动词规范
### 导航类
- 打开浏览器
- 访问 URL '[地址]'
- 后退
- 刷新
- 关闭

### 定位类
- 找到 [元素描述]
- 定位到 [区域]
- 切换至 [窗口/标签页]

### 交互类
- 点击 [按钮/链接]
- 输入 '[内容]'
- 选择 [选项]
- 悬停到 [元素]

### 状态类
- 等待 [条件/时间]
- 滚动到 [位置]
- 读取 [内容]
- 验证 [状态]

### 数据处理
- 提取 [数据]
- 存储 [变量]
- 判断 [条件]

## 📌 示例
### 示例 1
**输入：**"在 Google 搜索 pytest"

**输出：**
```json
{
  "action_text": "在google页面搜索‘pytest’，然后点击第1个搜索结果",
  "pages": [
    {
      "name": "搜索页面",
      "page_id": "page_1",
      "platform": "windows",
      "image_path": ".cache/images/73e668afe7403d5e937880a3c3e1659f.png",
      "actions": [
        {"name": "step1", "action": "打开浏览器"},
        {"name": "step2", "action": "访问 URL 'https://www.google.com'"},
        {"name": "step3", "action": "等待页面加载完成"},
        {"name": "step4", "action": "找到搜索框"},
        {"name": "step5", "action": "输入 'pytest' 到搜索框"},
        {"name": "step6", "action": "点击搜索按钮或按回车键"},
        {"name": "step7", "action": "等待搜索结果加载完成"}
      ]
    },
    {
      "name": "搜索结果页面",
      "page_id": "page_2",
      "platform": "browser",
      "image_path": ".cache/images/73e668afe7403d5e937880a3c3e1689f.png",
      "actions": [
        {"name": "step1", "action": "找到结果列表"},
        {"name": "step2", "action": "获取列表第一条数据 'pytest是一个自动化框架'"}
      ]
    }
  ]
}
```

## 🧾 正式任务
请将以下用户指令拆解为可执行操作步骤：
{{text}}

## ⚠️ 输出要求
- 严格按照 JSON 数组格式输出
- 不要包含任何额外说明文字
- 确保每个步骤的动作动词规范、目标明确
- 步骤名称从 step1 开始递增编号