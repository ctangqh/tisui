"""
执行设备基础协议定义。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List, Sequence

Coordinate = Sequence[int]  # [x, y] 像素
BBox = Tuple[int, int, int, int]  # (x1, y1, x2, y2) 像素

NativeRef = Dict[str, Any]  # {kind: "id|automation_id|css|... , value: ...} — 见 loop-design.md §5.7


@dataclass(frozen=True)
class ScrollState:
    """滚动容器位置状态 (L1 原生通道 scroll_probe 探测结果)。

    top/left 为当前滚动偏移; max_top/max_left 为可滚动上限
    (即 scrollHeight - clientHeight / scrollWidth - clientWidth)。
    """

    top: float
    left: float
    max_top: float
    max_left: float

    def at_boundary(self, direction: str) -> bool:
        """判断沿 direction 方向是否已到达滚动边界 (如在顶部不能再向上滚)。"""
        if direction == "up":
            return self.top <= 0
        if direction == "down":
            return self.top >= self.max_top
        if direction == "left":
            return self.left <= 0
        if direction == "right":
            return self.left >= self.max_left
        return False


class BaseDevice(ABC):
    def __init__(self, **kwargs):
        self.platform = kwargs.get("platform", "harmony")
        self.config = kwargs.get("config", {})

    @abstractmethod
    def lanch(self) -> None:
        ...

    @abstractmethod
    def close(self) -> bool:
        ...

    @abstractmethod
    def screenshot(self) -> bytes:
        ...

    @abstractmethod
    def click(self, coordinate: Coordinate) -> None:
        ...

    @abstractmethod
    def double_click(self, coordinate: Coordinate) -> None:
        """鼠标左键双击 (触摸设备为双击手势)。"""
        ...

    @abstractmethod
    def right_click(self, coordinate: Coordinate) -> None:
        """鼠标右键单击 (呼出上下文菜单)。"""
        ...

    @abstractmethod
    def input_text(self, text: str, position: Optional[Coordinate]=None) -> None:
        ...

    @abstractmethod
    def clear_text(self, position: Optional[Coordinate]=None) -> None:
        """清空输入框内容 (可选先点击 position 聚焦); 组合键各平台差异大, 由各设备原生实现。"""
        ...

    @abstractmethod
    def press_key(self, key: str, position: Optional[Coordinate]=None) -> None:
        ...

    @abstractmethod
    def swipe(
        self,
        start: Coordinate,
        end: Coordinate,
        *,
        duration_ms: int = 300,
    ) -> None:
        ...

    @abstractmethod
    def scroll(
        self,
        *,
        delta_x: int = 0,
        delta_y: int = 0,
        position: Optional[Coordinate] = None,
    ) -> None:
        """滚动。统一约定: delta_y > 0 = 页面向下滚, delta_x > 0 = 页面向右滚;
        position 可选, 指定时滚动作用于该坐标所在区域。"""
        ...

    def scroll_probe(self, position: Optional[Coordinate] = None) -> Optional[ScrollState]:
        """探测滚动容器位置 (L1 原生通道)。

        默认返回 None 表示无原生能力, executor 回退到 L2 视觉通道 (截图对比);
        有原生滚动位置 API 的设备 (如 Playwright JS) 覆盖此方法。
        """
        return None

    @abstractmethod
    def goto(self, url: str, **kwargs) -> None: 
        ...

    # -------- explore LocateCache / Backtrack 可选能力 (默认实现返回 None) ----
    def navigate_back(self) -> None:
        """返回上一页 (loop-design.md §6.1)。

        Playwright -> page.go_back(); Hypium -> Back 键; WinAppDriver/PyAutoGUI
        不覆写, 返回 None 时 executor 降级为让 VLM 在界面上找「返回/关闭」按钮点击。
        """
        return None

    def resolve_native_ref(self, coordinate: Coordinate) -> Optional[NativeRef]:
        """反查该坐标处控件的稳定原生引用 (loop-design.md §5.7 方案 A)。

        返回 dict: {kind, value}, 例如:
          - Web:      {"kind": "id", "value": "btn-ok"}
          - Win:      {"kind": "automation_id", "value": "ConfirmBtn"}
          - Hypium:   {"kind": "by_id",  "value": "main_input"}
        无控件树能力 / 拿不到稳定引用 -> 返回 None (PyAutoGUI 永远 None)。
        """
        return None

    def rect_by_native_ref(self, ref: NativeRef) -> Optional[BBox]:
        """按原生引用实时查找控件并返回屏幕像素 bbox; 找不到 -> None 触发 LocateCache 降级。"""
        return None

    # -------- 应用前台状态契约 (loop-design §4.7 失焦检测与恢复) ---------
    def is_app_foreground(self) -> Optional[bool]:
        """被测应用是否处于可交互前台 (失焦检测)。

        返回: True=前台正常; False=失焦/后台; None=平台无此概念或无法检测 (调用方跳过)。
        各平台实现互不相同, 由设备类各自覆写:
          - PyAutoGUI (Windows 原生): GetForegroundWindow() == 绑定 hwnd; 全桌面模式 None
          - WinAppDriver (Windows):   会话当前窗口句柄 vs 目标窗口句柄
          - Hypium (鸿蒙):            前台包名 == 被测包名
          - Playwright (Web):         无失焦概念, 不覆写 (默认 None)
        """
        return None

    def restore_app_foreground(self) -> Optional[bool]:
        """把被测应用恢复到前台 (失焦恢复)。

        返回: True=已恢复; False=恢复失败; None=无恢复能力 (调用方按失败累计)。
        各平台实现互不相同, 由设备类各自覆写:
          - PyAutoGUI: ShowWindow + AttachThreadInput + Alt 模拟 + SetForegroundWindow 组合拳
          - WinAppDriver: switch_to.window(目标窗口)
          - Hypium: 重新拉起/激活应用
          - Playwright: 无失焦概念, 不覆写 (默认 None)
        """
        return None

    def __enter__(self):
        self.launch()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
