"""SDK 执行编排 (一期同步)。

薄门面 tisui 把即时操作委托到这里。每个动作遵循「观察→定位→执行」:
    截图 → run_pipeline 定位 → 取 primary 元素 → 驱动设备动作。

不做任务分解 (那是 agent.task_builder + ai_act, 后续阶段)。
"""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from tisui.agent.locate import LocateOptions, LocatedElement, LocateResult, run_pipeline
from tisui.agent.query import QueryResult, run_query as _run_query
from tisui.device.base import BaseDevice

DEFAULT_WAIT_AFTER_ACTION = 0.5
DEFAULT_SCROLL_DISTANCE = 500
_TRUE_TOKENS = frozenset({"true", "1", "yes", "y", "是", "对", "有"})
_SCROLL_DIRECTIONS = frozenset({"up", "down", "left", "right"})
_SAME_REGION_MEAN_DIFF = 2.0  # 灰度均差阈值 (0-255), 低于此值视为画面未变化


@dataclass(frozen=True)
class ScrollResult:
    """ai_scroll 执行结果; moved=False 表示已在滚动边界 (如在顶部时向上滚)。"""

    moved: bool
    direction: str
    distance: int
    element: Optional[LocatedElement] = None


def run_locate(
    device: BaseDevice,
    action_text: str,
    *,
    options: Optional[LocateOptions] = None,
) -> LocatedElement:
    """截图并定位, 返回主元素 (raw 坐标已就绪, 可直接驱动动作)。"""
    image = device.screenshot()
    result = run_pipeline(image, action_text, options=options)
    return _primary(result, action_text)


def run_tap(
    device: BaseDevice,
    action_text: str,
    *,
    options: Optional[LocateOptions] = None,
    wait_after: float = DEFAULT_WAIT_AFTER_ACTION,
) -> LocatedElement:
    element = run_locate(device, action_text, options=options)
    device.click(element.action_point)
    _settle(wait_after)
    return element


def run_double_click(
    device: BaseDevice,
    action_text: str,
    *,
    options: Optional[LocateOptions] = None,
    wait_after: float = DEFAULT_WAIT_AFTER_ACTION,
) -> LocatedElement:
    element = run_locate(device, action_text, options=options)
    device.double_click(element.action_point)
    _settle(wait_after)
    return element


def run_right_click(
    device: BaseDevice,
    action_text: str,
    *,
    options: Optional[LocateOptions] = None,
    wait_after: float = DEFAULT_WAIT_AFTER_ACTION,
) -> LocatedElement:
    element = run_locate(device, action_text, options=options)
    device.right_click(element.action_point)
    _settle(wait_after)
    return element


def run_input(
    device: BaseDevice,
    action_text: str,
    text: str,
    *,
    options: Optional[LocateOptions] = None,
    wait_after: float = DEFAULT_WAIT_AFTER_ACTION,
) -> LocatedElement:
    element = run_locate(device, action_text, options=options)
    device.input_text(text, position=element.action_point)
    _settle(wait_after)
    return element


def run_keyboard_press(
    device: BaseDevice,
    key: str,
    *,
    action_text: Optional[str] = None,
    options: Optional[LocateOptions] = None,
    wait_after: float = DEFAULT_WAIT_AFTER_ACTION,
) -> None:
    """把按键发送给当前焦点元素; 不做任何鼠标点击。

    按键始终作用于当前焦点 (通常由上一步 tap/input 已聚焦)。若需对特定控件按键,
    请先用 ai_tap 点击该控件使其获得焦点, 再调用本方法。
    action_text / options 仅为兼容保留, 不再触发定位或点击 (点击会干扰下拉/提交)。
    """
    device.press_key(key)
    _settle(wait_after)


def run_clear(
    device: BaseDevice,
    action_text: str,
    *,
    options: Optional[LocateOptions] = None,
    wait_after: float = DEFAULT_WAIT_AFTER_ACTION,
) -> LocatedElement:
    """定位输入框并清空内容 (聚焦 → 全选 → 删除; 组合键由设备层原生实现)。"""
    element = run_locate(device, action_text, options=options)
    device.clear_text(position=element.action_point)
    _settle(wait_after)
    return element


def run_scroll(
    device: BaseDevice,
    direction: str,
    *,
    distance: int = DEFAULT_SCROLL_DISTANCE,
    action_text: Optional[str] = None,
    options: Optional[LocateOptions] = None,
    wait_after: float = DEFAULT_WAIT_AFTER_ACTION,
    check_boundary: bool = True,
) -> ScrollResult:
    """四向滚动 + 滚动边界识别, 分两级实现 (见 design/scroll-design.md):

    L1 原生通道: device.scroll_probe() 返回 ScrollState → 事前边界拦截 + 事后读位置对比;
    L2 视觉通道: 无原生能力时回退到滚动前后截图对比 (边界处多滚一次是无害空操作)。

    action_text 可选: 传入时先定位, 滚动作用于目标元素区域, 截图对比也仅裁剪该区域;
    check_boundary=False 时跳过边界检测 (视频背景等动态页面防误判), 直接返回 moved=True。
    """
    direction = str(direction).strip().lower()
    if direction not in _SCROLL_DIRECTIONS:
        raise ValueError(
            f"无效滚动方向: {direction!r} (合法值: up / down / left / right)"
        )
    if distance <= 0:
        raise ValueError(f"滚动距离必须为正数: {distance!r}")

    element = (
        run_locate(device, action_text, options=options) if action_text else None
    )
    point = element.action_point if element is not None else None
    delta_x, delta_y = _scroll_deltas(direction, distance)

    if not check_boundary:
        device.scroll(delta_x=delta_x, delta_y=delta_y, position=point)
        _settle(wait_after)
        return ScrollResult(moved=True, direction=direction, distance=distance, element=element)

    state = device.scroll_probe(point)
    if state is not None:
        # ---- L1 原生通道: 零截图, 可精确"在顶部"事前预判 ----
        if state.at_boundary(direction):
            return ScrollResult(moved=False, direction=direction, distance=distance, element=element)
        device.scroll(delta_x=delta_x, delta_y=delta_y, position=point)
        _settle(wait_after)
        new_state = device.scroll_probe(point)
        moved = new_state is None or (new_state.top, new_state.left) != (state.top, state.left)
        return ScrollResult(moved=moved, direction=direction, distance=distance, element=element)

    # ---- L2 视觉通道: 滚动前后截图对比 ----
    before = device.screenshot()
    device.scroll(delta_x=delta_x, delta_y=delta_y, position=point)
    _settle(wait_after)
    after = device.screenshot()
    region = getattr(element, "bbox", None) if element is not None else None
    moved = not _same_region(before, after, region)
    return ScrollResult(moved=moved, direction=direction, distance=distance, element=element)


def run_query(device: BaseDevice, query: str) -> QueryResult:
    """截图并按 query 提取数据 (纯读取, 不定位/不动作)。"""
    image = device.screenshot()
    return _run_query(image, query)


def run_swipe(
    device: BaseDevice,
    direction: str,
    *,
    distance: int = DEFAULT_SCROLL_DISTANCE,
    duration_ms: int = 300,
    wait_after: float = DEFAULT_WAIT_AFTER_ACTION,
) -> None:
    """从屏幕中心沿 direction 滑动 (轮播图/Tab 切换; 与 scroll 区别见 loop-design.md 6.1)。"""
    direction = str(direction).strip().lower()
    if direction not in _SCROLL_DIRECTIONS:
        raise ValueError(
            f"无效滑动方向: {direction!r} (合法值: up / down / left / right)"
        )
    width, height = _screen_size(device)
    cx, cy = width // 2, height // 2
    half = min(distance, width // 3 if direction in ("left", "right") else height // 3)
    delta_x, delta_y = _scroll_deltas(direction, half)
    # swipe 手势方向与内容移动方向相反: 内容向左 = 手指向左拖, 起点在中心偏反方向
    start = (cx + delta_x // 2, cy + delta_y // 2)
    end = (cx - delta_x // 2, cy - delta_y // 2)
    device.swipe(start, end, duration_ms=duration_ms)
    _settle(wait_after)


def run_back(
    device: BaseDevice,
    *,
    wait_after: float = DEFAULT_WAIT_AFTER_ACTION,
) -> None:
    """返回上一页: 设备有 navigate_back 能力时优先走原生通道,
    否则降级为 VLM 定位页内"返回/后退/关闭"按钮 (跨设备语义见 loop-design.md 6.1)。"""
    navigate_back = getattr(device, "navigate_back", None)
    if callable(navigate_back):
        navigate_back()
        _settle(wait_after)
        return
    run_tap(device, "返回上一页的返回/后退/关闭按钮", wait_after=wait_after)


def run_boolean(device: BaseDevice, query: str) -> bool:
    """截图问答并将结果收敛为布尔 (ai_boolean 执行层)。"""
    return _extract(device, query, coerce=_coerce_bool)


def run_number(device: BaseDevice, query: str) -> float:
    """截图问答并将结果收敛为数值 (ai_number 执行层)。"""
    return _extract(device, query, coerce=_coerce_number)


def run_string(device: BaseDevice, query: str) -> str:
    """截图问答并将结果收敛为字符串 (ai_string 执行层)。"""
    return _extract(device, query, coerce=_coerce_str)


def run_assert(device: BaseDevice, condition: str) -> None:
    """对当前界面做视觉断言, 条件不满足抛 AssertionError (ai_assert 执行层)。"""
    if not _judge(device, condition):
        raise AssertionError(f"视觉断言失败: {condition}")


def run_wait_for(
    device: BaseDevice,
    condition: str,
    *,
    timeout: float = 15.0,
    interval: float = 1.0,
) -> None:
    """轮询截图判断 condition 是否满足, 命中即返回, 超时抛 TimeoutError (ai_wait_for 执行层)。"""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if _judge(device, condition):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"等待条件超时 ({timeout}s): {condition}")
        _settle(interval)


# ---- 内部 ---------------------------------------------------------------

def _primary(result: LocateResult, action_text: str) -> LocatedElement:
    if result.status == "failed" or not result.elements:
        raise RuntimeError(
            f"定位失败: action={action_text!r} status={result.status} "
            f"error={result.error or 'no element'}"
        )
    index = result.primary_index
    if not 0 <= index < len(result.elements):
        index = 0
    return result.elements[index]


def _settle(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(seconds)


def _scroll_deltas(direction: str, distance: int) -> tuple[int, int]:
    """方向+距离 → (delta_x, delta_y); 约定 delta_y > 0 = 页面向下滚。"""
    if direction == "down":
        return 0, distance
    if direction == "up":
        return 0, -distance
    if direction == "right":
        return distance, 0
    return -distance, 0  # left


def _screen_size(device: BaseDevice) -> tuple[int, int]:
    """取屏幕尺寸 (截一张图量宽高; swipe 起止点计算用)。"""
    from PIL import Image

    with Image.open(io.BytesIO(device.screenshot())) as img:
        return img.size


def _same_region(before: bytes, after: bytes, bbox: Any = None) -> bool:
    """判断两张截图 (或其 bbox 裁剪区域) 是否基本相同 (L2 边界检测)。

    降采样后算灰度均差, 小阈值判定"未变化", 抗 PNG 编码噪声与光标闪烁。
    对比失败时保守返回 False (视为有变化, 不误报边界)。
    """
    try:
        from PIL import Image, ImageChops, ImageStat

        img_a = Image.open(io.BytesIO(before)).convert("L")
        img_b = Image.open(io.BytesIO(after)).convert("L")
        if bbox is not None and len(bbox) == 4:
            box = tuple(int(v) for v in bbox)
            img_a = img_a.crop(box)
            img_b = img_b.crop(box)
        if img_a.size != img_b.size or img_a.width < 1 or img_a.height < 1:
            return False
        target = (max(1, img_a.width // 4), max(1, img_a.height // 4))
        img_a = img_a.resize(target)
        img_b = img_b.resize(target)
        diff = ImageChops.difference(img_a, img_b)
        return ImageStat.Stat(diff).mean[0] < _SAME_REGION_MEAN_DIFF
    except Exception:  # noqa: BLE001 - 对比异常不阻断主流程
        return False


def _extract(device: BaseDevice, query: str, *, coerce: Callable[[Any], Any]) -> Any:
    return coerce(run_query(device, query).data)


def _judge(device: BaseDevice, condition: str) -> bool:
    prompt = (
        f"{condition.strip()}\n\n"
        "判断该条件在当前界面是否满足, 满足返回 true, 否则返回 false。"
    )
    return _coerce_bool(run_query(device, prompt).data)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_TOKENS
    return bool(value)


def _coerce_number(value: Any) -> float:
    if isinstance(value, bool):  # bool 是 int 子类, 单独拦住
        raise ValueError(f"无法将布尔值转为数值: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            return float(match.group())
    raise ValueError(f"无法从结果解析数值: {value!r}")


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


__all__ = [
    "run_locate",
    "run_tap",
    "run_double_click",
    "run_right_click",
    "run_input",
    "run_keyboard_press",
    "run_clear",
    "run_scroll",
    "run_swipe",
    "run_back",
    "run_query",
    "run_boolean",
    "run_number",
    "run_string",
    "run_assert",
    "run_wait_for",
    "QueryResult",
    "ScrollResult",
    "DEFAULT_WAIT_AFTER_ACTION",
    "DEFAULT_SCROLL_DISTANCE",
]
