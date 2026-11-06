"""ai_explore 的 prompt 组装与回复解析。

每轮只有一次 VLM 调用: 观察 (页面标题/可见元素) 与决策合并在同一次输出里
(见 design/loop-design.md 4.3)。本模块无状态, 只负责文本进出。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from tisui.agent.vision_io import parse_json_loose
from tisui.shared.env import get_forbidden_enabled

# 内置危险词黑名单 (见 loop-design.md 4.6), 与 forbidden 参数合并生效
DANGEROUS_KEYWORDS = (
    "删除", "清空", "支付", "购买", "发送", "提交订单", "卸载", "恢复出厂",
    "注销", "退出登录", "关机", "重启",
    "delete", "remove", "clear", "pay", "purchase", "buy", "send",
    "submit order", "uninstall", "factory reset", "logout", "log out",
    "sign out", "shutdown", "reboot", "restart",
)

# 协议/许可类弹窗关键词 (中英文), 命中时一律选择"同意/接受/继续"
CONSENT_KEYWORDS = (
    "协议", "条款", "许可", "隐私政策", "用户协议", "服务条款", "隐私声明",
    "我已阅读", "我同意", "同意并", "接受", "继续", "下一步", "跳过",
    "terms", "privacy", "consent", "agree", "accept", "eula",
    "cookie", "license", "permission", "next", "skip", "continue",
)

# 安全可自动处理的弹窗关键词 (通知/成功提示/保存确认等)
SAFE_DIALOG_KEYWORDS = (
    "知道了", "好的", "关闭", "完成", "ok", "got it", "close",
    "成功", "已保存", "已复制", "done", "success",
)

# 非必要授权复选框关键词 (不应勾选)
UNNECESSARY_CONSENT_KEYWORDS = (
    "营销", "推送", "通知", "数据共享", "共享使用数据", "接收",
    "marketing", "push", "notification", "data sharing", "receive",
)


@dataclass
class ExploreDecision:
    """单轮 VLM 观察 + 决策的解析结果。"""

    status: str                                  # continue | completed | exhausted
    page_title: str = ""
    elements: list[str] = field(default_factory=list)
    regions: list[dict[str, Any]] = field(default_factory=list)    # 区域划分 (含弹窗检测)
    dialog_detected: bool = False                                # 是否检测到模态弹窗
    dialog_decision: dict[str, Any] | None = None                # 弹窗处理决策
    reason: str = ""
    action: dict[str, Any] = field(default_factory=dict)
    new_finding: dict[str, Any] | None = None


def build_explore_prompt(
    *,
    goal: str,
    end_condition: str,
    strategy: str,
    context: str,
    page_key: str,
    is_new_page: bool,
    known_elements: list[str],
    interacted: set[str],
    dead_elements: set[str],
    visited_summary: list[str],
    recent_ops: list[str],
    forbidden: list[str],
    findings_count: int,
    force_change_target: bool,
    backtrack: bool,
    current_depth: int = 0,
    max_depth: int | None = None,
    branch_summary: list[str] | None = None,
    exhausted_override: bool = False,
    completed_override: bool = False,
) -> str:
    """组装单轮探索规划 prompt (观察 + 决策合并, 每轮仅此一次 VLM 调用)。"""
    parts = [
        "你是一个 UI 自主探索器。你会看到当前界面截图, 需要先观察页面, 再规划下一步探索动作。",
        f"\n【探索目标】\n{goal.strip()}",
    ]
    if end_condition.strip():
        parts.append(f"\n【结束条件】\n{end_condition.strip()}\n(满足时 status=completed)")
    if strategy == "depth-first":
        depth_line = f"当前深度: {current_depth}"
        depth_line += f" / 上限 {max_depth}" if max_depth is not None else " / 不限"
        branch_lines = [
            f"\n待回溯分叉点: {len(branch_summary or [])} 个"
            + (f"\n" + "\n".join(f"  - {s}" for s in branch_summary) if branch_summary else "")
        ]
        depth_rules = [
            "1. 优先选未访问元素深入 (进入新页面深度+1); 本页无未访问元素 → 必须 back 回溯",
            ("2. 当前深度已达上限 → 只探索本页元素或 back, 不得再进入新页面"
             if max_depth is not None else ""),
            "3. 判定 exhausted 前确保所有分叉点已回溯完毕且本页无未访问元素",
        ]
        parts.append(
            "\n【探索策略】depth-first (深度优先): 沿当前分支深入, 到底后回溯到最近分叉点继续。\n"
            + depth_line + "".join(branch_lines) + "\n规则:\n"
            + "\n".join(line for line in depth_rules if line)
        )
    else:
        parts.append(f"\n【探索策略】coverage (广度覆盖): 优先覆盖当前页面未访问的元素, 不重复已探索路径。")
    if context.strip():
        parts.append(f"\n【背景知识】\n{context.strip()}")

    page_mark = "(新页面, 首次访问)" if is_new_page else ""
    parts.append(f"\n【当前页面】\npage_id: {page_key} {page_mark}")

    if known_elements:
        lines = []
        for name in known_elements:
            if name in dead_elements:
                lines.append(f"- {name} (死元素, 不可选)")
            elif name in interacted:
                lines.append(f"- {name} (已访问)")
            else:
                lines.append(f"- {name} (未访问)")
        parts.append("\n【本页已知元素】(来自本页历史观察)\n" + "\n".join(lines))

    if visited_summary:
        parts.append(f"\n【已访问页面】共 {len(visited_summary)} 页\n" + "\n".join(visited_summary))
    if recent_ops:
        parts.append("\n【最近操作】\n" + "\n".join(recent_ops))
    parts.append(f"\n【当前发现计数】{findings_count} 条")
    if forbidden:
        parts.append("\n【禁止目标】(绝对不可点击/操作)\n" + " / ".join(forbidden))
    if force_change_target:
        parts.append("\n【强制要求】最近操作出现页面回环, 本轮必须选择与最近不同的目标或 back。")
    if exhausted_override:
        parts.append(
            "\n【强制要求】上轮你误判了 exhausted (仍有分叉点未回溯或本页有未访问元素), 本轮必须继续探索。"
        )
    if completed_override:
        parts.append(
            "\n【强制要求】上轮你误判了 completed (结束条件尚未满足), 本轮必须继续探索, 不得再报 completed 或 exhausted。"
        )
    if not recent_ops:
        parts.append(
            "\n【首轮约束】当前是探索开始后的第一轮 (尚未执行任何操作), 界面可能尚未稳定:\n"
            "   禁止使用 tap/double_click/right_click/input/clear 等点击类动作 (点击易落空或点错窗口);\n"
            "   本轮只允许 keyboard_press / scroll / sleep / query / back, 待界面稳定后再点击。"
        )

    parts.append(
        "\n【可用动作】(locate 用自然语言描述目标, bbox 为该目标在截图中的像素框 [x1,y1,x2,y2])\n"
        '- {"type":"tap","locate":"要点击的元素","bbox":[x1,y1,x2,y2]}\n'
        '- {"type":"double_click","locate":"要双击的元素","bbox":[x1,y1,x2,y2]}\n'
        '- {"type":"right_click","locate":"要右键的元素","bbox":[x1,y1,x2,y2]}\n'
        '- {"type":"input","locate":"输入框","bbox":[x1,y1,x2,y2],"value":"要输入的文本"}  (value 为要输入的文本内容, 必须给出)\n'
        '- {"type":"clear","locate":"要清空的输入框","bbox":[x1,y1,x2,y2]}\n'
        '- {"type":"keyboard_press","key":"Enter"}  (作用于当前焦点元素)\n'
        '- {"type":"scroll","direction":"up|down|left|right"}\n'
        '- {"type":"swipe","direction":"left|right"}\n'
        + ('- {"type":"back"}  (返回上一页)\n' if backtrack else "")
        + '- {"type":"query","query":"要从当前界面提取的数据需求"}\n'
        '- {"type":"sleep","seconds":2}'
    )
    parts.append(
        "\n【规划要求】\n"
        "1. 首先输出观察: page_title (当前页面标题)、elements (本页可见可交互元素清单) 和 regions (区域划分)。\n"
        "2. 从可见元素中选一个未访问且非死元素的目标。\n"
        "3. 当前页面已无未访问元素时" + ("选择 back 回溯。\n" if backtrack else "标记 exhausted。\n") +
        "4. 探索已满足结束条件时 status=completed, 所有可达页面探索完毕时 status=exhausted。\n"
        "5. 避免重复操作: 浏览列表用 scroll, 不要反复回到已访问页。\n"
        "6. 发现异常 (白屏/报错/布局错乱)、有价值页面或数据时写入 new_finding。\n"
        "7. 禁止选择【禁止目标】中的元素及语义等同的危险操作, 包括危险图标 (如垃圾桶)。\n"
        "8. 未执行任何动作前不得判定完成: 只有在截图明确显示任务目标已达成时才可 status=completed,\n"
        "   每轮都必须给出非空 action (任务未完成时不许输出空 action 或仅凭意图判定完成)。\n"
        "9. 弹窗优先处理: 如果 regions 中存在 kind=\"dialog\" 且 modal=true 的模态弹窗区域:\n"
        "   - 必须优先处理弹窗, 正常探索动作暂停\n"
        "   - 设置 dialog_detected=true 并在 dialog_decision 中给出处理方案\n"
        "   - action 可选: close(关闭) / confirm(确认/同意) / cancel(取消) / skip(跳过不操作)\n"
        "   - target 为要点击的按钮文字, bbox 为该按钮在截图中的像素框\n"
        "   - check_first: 需要先勾选的复选框列表 [{label, bbox}], 协议同意类必须先勾选\n"
        "   - 协议/条款/隐私政策/EULA 等同意类弹窗一律 action=confirm\n"
        "   - 营销/推送/数据共享等非必要授权复选框不要放入 check_first\n"
        "   - 删除/支付/退出登录等危险弹窗 action=skip, 在 anomaly 中说明\n"
        "   - target 按钮也受【禁止目标】约束, 危险按钮不可点击"
    )
    parts.append(
        "\n只输出一个 JSON 对象:\n"
        '{"page_title":"", "elements":[], \n'
        ' "regions":[{"kind":"content|dialog|toast|menu","stability":"stable|volatile","modal":false,"bbox":[x1,y1,x2,y2]}],\n'
        ' "dialog_detected": false,\n'
        ' "dialog_decision": null 或 {"action":"close|confirm|cancel|skip",\n'
        '   "target":"按钮文字", "bbox":[x1,y1,x2,y2],\n'
        '   "check_first":[{"label":"复选框文字","bbox":[x1,y1,x2,y2]}],\n'
        '   "reason":"处理理由", "anomaly":"危险弹窗描述(仅skip时)"},\n'
        ' "status":"continue|completed|exhausted",\n'
        ' "reason":"", "action":{...},\n'
        ' "new_finding": null 或 {"type":"element|page|anomaly|data","description":"","data":null}}\n'
        "不要输出任何解释或多余文字。"
    )
    return "\n".join(parts)


def parse_explore_reply(text: str) -> ExploreDecision:
    """解析 VLM 回复; 非法输出抛 ValueError (由 loop 计入失败轮)。"""
    parsed = parse_json_loose(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"探索规划返回非法 JSON: {text[:200]!r}")
    status = str(parsed.get("status") or "").strip().lower()
    if status not in ("continue", "completed", "exhausted"):
        raise ValueError(f"探索规划返回未知 status: {status!r}")
    raw_elements = parsed.get("elements")
    elements = (
        [str(e).strip() for e in raw_elements if str(e).strip()]
        if isinstance(raw_elements, list)
        else []
    )
    raw_regions = parsed.get("regions")
    regions = (
        [r for r in raw_regions if isinstance(r, dict)]
        if isinstance(raw_regions, list)
        else []
    )
    dialog_detected = bool(parsed.get("dialog_detected", False))
    raw_dialog = parsed.get("dialog_decision")
    dialog_decision = raw_dialog if isinstance(raw_dialog, dict) else None
    action = parsed.get("action") if isinstance(parsed.get("action"), dict) else {}
    finding = parsed.get("new_finding") if isinstance(parsed.get("new_finding"), dict) else None
    return ExploreDecision(
        status=status,
        page_title=str(parsed.get("page_title") or "").strip(),
        elements=elements,
        regions=regions,
        dialog_detected=dialog_detected,
        dialog_decision=dialog_decision,
        reason=str(parsed.get("reason") or ""),
        action=dict(action),
        new_finding=finding,
    )


def match_forbidden(target: str, forbidden: list[str]) -> str | None:
    """目标描述与禁止清单做子串匹配, 命中返回命中的词, 否则 None (框架二次拦截)。"""
    lowered = (target or "").strip().lower()
    if not lowered:
        return None
    for word in forbidden:
        w = word.strip().lower()
        if w and w in lowered:
            return word
    return None


def merge_forbidden(user_forbidden: list[str] | None) -> list[str]:
    """内置黑名单 + 用户追加清单合并去重, 保持顺序。

    配置 explore.forbidden_enabled: false 时关闭内置黑名单,
    但用户显式传入的 forbidden 仍然生效(那是显式意图)。
    """
    merged = list(DANGEROUS_KEYWORDS) if get_forbidden_enabled() else []
    for word in user_forbidden or []:
        w = str(word).strip()
        if w and w not in merged:
            merged.append(w)
    return merged


# ---- 结束条件解析 (见 loop-design.md 4.5) --------------------------------

# 单位词前 1-2 字 -> 框架可数对象 (白名单启发式)
_NUM_UNIT_MAP = {
    "页": "pages", "页面": "pages",
    "发现": "findings", "异常": "findings", "问题": "findings", "结果": "findings",
    "数据": "data_findings", "信息": "data_findings",
    "价格": "data_findings", "产品": "data_findings",
    "元素": "elements", "选项": "elements", "按钮": "elements", "开关": "elements",
}
_CN_NUM_MAP = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
# 引号包裹的关键词 (支持中英文引号/书名号)
_QUOTED_RE = re.compile(
    r"[\"“”'‘’「」『』《》]([^\"“”'‘’「」『』《》]{1,40})[\"“”'‘’「」『』《》]"
)
# 数字(中英文) + 可省略量词 + 1-3 字名词, 如 "3 个产品价格" "5页"
_NUM_CLAUSE_RE = re.compile(
    r"(\d{1,3}|[一二两三四五六七八九十]{1,3})\s*([个条次])?\s*([\u4e00-\u9fa5]{1,3})"
)


@dataclass
class EndConditionSpec:
    """从 end_condition 解析出的客观子条件 (见 4.5)。空 spec 表示全部交 VLM 判定。"""

    thresholds: dict[str, int] = field(default_factory=dict)  # 可数对象 -> 目标数
    keywords: list[str] = field(default_factory=list)          # 引号关键词

    def has_objective(self) -> bool:
        return bool(self.thresholds or self.keywords)


def _cn_to_int(s: str) -> int | None:
    """中文数字转 int; 无法解析返回 None。"""
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    total = 0
    for ch in s:
        v = _CN_NUM_MAP.get(ch)
        if v is None:
            return None
        total = total * 10 + v
    return total if total else None


def _unit_to_object(noun: str) -> str | None:
    """名词前 1-2 字映射可数对象 (startswith 白名单)。"""
    for key, obj in _NUM_UNIT_MAP.items():
        if noun.startswith(key):
            return obj
    return None


def parse_end_condition(text: str) -> EndConditionSpec:
    """从自然语言结束条件解析可客观判定的子条件 (见 4.5)。

    解析不出任何子条件时返回空 spec, 调用方回退为纯 VLM 判定。
    """
    spec = EndConditionSpec()
    src = str(text or "")
    if not src.strip():
        return spec
    for num_raw, _unit, noun in _NUM_CLAUSE_RE.findall(src):
        num = _cn_to_int(num_raw)
        if num is None or num <= 0:
            continue
        obj = _unit_to_object(noun)
        if obj and spec.thresholds.get(obj, 0) < num:
            spec.thresholds[obj] = num
    for kw in _QUOTED_RE.findall(src):
        k = kw.strip()
        if k and k not in spec.keywords:
            spec.keywords.append(k)
    return spec


__all__ = [
    "ExploreDecision",
    "EndConditionSpec",
    "build_explore_prompt",
    "parse_explore_reply",
    "parse_end_condition",
    "match_forbidden",
    "merge_forbidden",
    "DANGEROUS_KEYWORDS",
    "CONSENT_KEYWORDS",
    "SAFE_DIALOG_KEYWORDS",
    "UNNECESSARY_CONSENT_KEYWORDS",
]
