# AGENTS.md

本文件定义 Agent 在本仓库中的变更边界。除非用户明确批准，否则以下规则一律强制执行。

## MCP协议要求
统一MCP中的tools/list的返回
示例：

|方法名称|功能说明|winappdriver|hypium|playwright|appium|
|---|---|---|---|---|---|
|screenshot|截屏|[/session/:sessionId/screenshot|capture_screen|||
|input|||
|SendKeys|||


capture_screen


```json
{
    "jsonrpc": "2.0",
    "result" {
        "tools": [
            {
                "name": "click|input|scroll|screenshot|session|"
            }
        ]
    }
}
```