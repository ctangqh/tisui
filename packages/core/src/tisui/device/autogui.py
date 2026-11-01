"""PyAutoGUI 直连设备 (桌面自动化)。

把 BaseDevice 的同步原语映射到 pyautogui 的屏幕/鼠标/键盘操作:
- screenshot()          -> pyautogui.screenshot() 落 PIL Image 后 BytesIO 导出 PNG 字节
- click([x, y])         -> pyautogui.click(x, y)
- input_text(text, pos) -> 可选先点 (x,y) 聚焦, 再 write (ASCII) / 剪贴板+Ctrl+V (Unicode)
- press_key(key, pos)   -> 可选先点 (x,y), 再 pyautogui.press(key_name)
- swipe(start, end, duration_ms) -> mouseDown -> moveTo(duration=...) -> mouseUp
- scroll(dx, dy)        -> pyautogui.scroll(dy) + pyautogui.hscroll(dx)

坐标为 run_pipeline 输出的全屏截图像素坐标; 默认 pyautogui 按屏幕物理像素工作。
Windows 下若系统缩放 (DPI) 非 100%, 可通过构造时传 dpi_aware=True 启用
ctypes.windll.user32.SetProcessDPIAware(), 让 pyautogui 与截图返回的物理像素一致。

依赖: pyautogui 非 pip 强制依赖, 在 launch() 内懒 import, 导入失败时抛出清晰提示。
      pyperclip 仅在 input_text 含非 ASCII 字符时才需要 (可选); 缺失则回退到
      win32clipboard (Windows 原生) 或抛 NotImplementedError。

注意:
- 默认 pyautogui.FAILSAFE = False, 避免鼠标移到 (0,0) 触发中断; 可在构造时传
  failsafe=True 恢复 pyautogui 默认 (用于本地调试)。
- 默认 pyautogui.PAUSE = 0, 避免动作之间被插入 0.1s 延迟; 可在构造时通过
  pause 覆盖。

窗口绑定 (借鉴 WinAppDriver appTopLevelWindow):
- 构造时传 hwnd / window_title / window_class (三选一) 可绑定到固定窗口;
  launch() 内通过 win32gui.FindWindow / EnumWindows 解析为真实 HWND。
- activate_before_action=True (默认) 时, 每个输入动作前自动 SetForegroundWindow,
  确保 pyautogui 的键盘/鼠标事件落到目标窗口。
- coords_relative_to_window=True 时, 用户传入的坐标视为"窗口内相对坐标",
  自动加 GetWindowRect 左上角偏移换算为屏幕绝对坐标 (等价 WinAppDriver 的
  /window/position + 屏幕绝对像素坐标分离设计)。
- 运行时可用 focus_window() 切换目标窗口 (等价 WinAppDriver switch_to.window)。
- 未传任何窗口参数时, 退化为"全桌面模式" (原行为, 不绑定窗口)。

win32gui / win32con (pywin32) 仅在指定窗口参数时才需要; 缺失则降级为全桌面模式
或抛 RuntimeError (取决于是否无法满足窗口绑定请求)。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from tisui.device.base import BaseDevice

Coordinate = Sequence[int]  # [x, y]

# 字符串键名 -> pyautogui.KEYBOARD_KEYS 中的合法字符串。
# pyautogui 原生键名即为小写 (如 'enter', 'tab', 'up', 'f1'), 本表仅做别名归一化,
# 未命中的字符串将按原样透传给 pyautogui.press() (pyautogui 自身校验)。
_KEY_MAP: dict[str, str] = {
    "enter": "enter",
    "return": "enter",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "tab": "tab",
    "escape": "escape",
    "esc": "escape",
    "space": "space",
    " ": "space",
    "up": "up",
    "arrowup": "up",
    "down": "down",
    "arrowdown": "down",
    "left": "left",
    "arrowleft": "left",
    "right": "right",
    "arrowright": "right",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4", "f5": "f5", "f6": "f6",
    "f7": "f7", "f8": "f8", "f9": "f9", "f10": "f10", "f11": "f11", "f12": "f12",
    "ctrl": "ctrl", "control": "ctrl",
    "shift": "shift", "alt": "alt",
    "win": "win", "windows": "win",
}


class PyAutoGUIDevice(BaseDevice):
    def __init__(
        self,
        *,
        failsafe: bool = False,
        pause: float = 0.0,
        dpi_aware: bool = False,
        hwnd: Optional[int] = None,
        window_title: Optional[str] = None,
        window_class: Optional[str] = None,
        activate_before_action: bool = True,
        coords_relative_to_window: bool = False,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("platform", "windows")
        super().__init__(**kwargs)
        self.failsafe = failsafe
        self.pause = pause
        self.dpi_aware = dpi_aware
        # ---- 窗口绑定 (借鉴 WinAppDriver appTopLevelWindow) ----
        self._hwnd: Optional[int] = hwnd
        self._window_title = window_title
        self._window_class = window_class
        self._activate_before_action = activate_before_action
        self._coords_relative = coords_relative_to_window
        self._pyautogui = None

    # ---- 生命周期 -------------------------------------------------------
    def launch(self) -> None:
        try:
            import pyautogui
        except ImportError as exc:  # noqa: BLE001
            raise RuntimeError(
                "无法导入 pyautogui; 请在当前环境安装 (pip install pyautogui)"
            ) from exc

        # Windows 下若启用 DPI 感知, 让截图与 pyautogui 坐标均为物理像素。
        if self.dpi_aware:
            self._try_enable_dpi_awareness()

        pyautogui.FAILSAFE = bool(self.failsafe)
        pyautogui.PAUSE = float(self.pause)
        self._pyautogui = pyautogui

        # 解析窗口绑定 (hwnd > window_class > window_title); 无参数则全桌面
        self._resolve_window()

    lanch = launch  # 兼容 BaseDevice 抽象方法命名 (上游拼写)

    def close(self) -> bool:
        self._pyautogui = None
        return True

    # ---- 感知 -----------------------------------------------------------
    def screenshot(self) -> bytes:
        from io import BytesIO

        pil_image = self.pyautogui.screenshot()
        buffer = BytesIO()
        pil_image.save(buffer, format="PNG")
        return buffer.getvalue()

    # ---- 动作 -----------------------------------------------------------
    def click(self, coordinate: Coordinate) -> None:
        self._ensure_foreground()
        x, y = self._to_screen(*self._xy(coordinate))
        self.pyautogui.click(x, y)

    def double_click(self, coordinate: Coordinate) -> None:
        self._ensure_foreground()
        x, y = self._to_screen(*self._xy(coordinate))
        self.pyautogui.doubleClick(x, y)

    def right_click(self, coordinate: Coordinate) -> None:
        self._ensure_foreground()
        x, y = self._to_screen(*self._xy(coordinate))
        self.pyautogui.rightClick(x, y)

    def input_text(self, text: str, position: Optional[Coordinate] = None) -> None:
        self._ensure_foreground()
        if position is not None:
            x, y = self._to_screen(*self._xy(position))
            self.pyautogui.click(x, y)
        if not text:
            return

        # 纯 ASCII: 直接走 pyautogui.write (逐字符模拟按键, 兼容性好)
        if text.isascii():
            self.pyautogui.write(text)
            return

        # 含非 ASCII (中文/emoji/...): pyautogui.write 不支持, 回退到剪贴板 + Ctrl+V
        self._paste_text(text)

    def clear_text(self, position: Optional[Coordinate] = None) -> None:
        self._ensure_foreground()
        if position is not None:
            x, y = self._to_screen(*self._xy(position))
            self.pyautogui.click(x, y)
        self.pyautogui.hotkey("ctrl", "a")
        self.pyautogui.press("delete")

    def press_key(self, key: str, position: Optional[Coordinate] = None) -> None:
        self._ensure_foreground()
        if position is not None:
            x, y = self._to_screen(*self._xy(position))
            self.pyautogui.click(x, y)
        # 组合键支持: "alt+n" / "ctrl+shift+esc" 形式 → hotkey (如窗口按钮快捷键助记符);
        # 单键 ("enter" / "f5" / 表内别名) → press
        parts = [p.strip() for p in str(key).split("+") if p.strip()]
        if len(parts) > 1:
            self.pyautogui.hotkey(*[self._resolve_key(p) for p in parts])
        else:
            self.pyautogui.press(self._resolve_key(parts[0] if parts else str(key)))

    def swipe(
        self,
        start: Coordinate,
        end: Coordinate,
        *,
        duration_ms: int = 300,
    ) -> None:
        self._ensure_foreground()
        sx, sy = self._to_screen(*self._xy(start))
        ex, ey = self._to_screen(*self._xy(end))
        duration_s = max(0.0, duration_ms / 1000)
        pag = self.pyautogui
        pag.moveTo(sx, sy)
        pag.mouseDown()
        try:
            pag.moveTo(ex, ey, duration=duration_s)
        finally:
            pag.mouseUp()

    def scroll(
        self,
        *,
        delta_x: int = 0,
        delta_y: int = 0,
        position: Optional[Coordinate] = None,
    ) -> None:
        self._ensure_foreground()
        pag = self.pyautogui
        pos_kwargs: dict[str, int] = {}
        if position is not None:
            x, y = self._to_screen(*self._xy(position))
            pos_kwargs = {"x": x, "y": y}
        if delta_y != 0:
            # 统一约定 delta_y > 0 = 页面向下滚; pyautogui.scroll 正数 = 滚轮向上, 故取反
            pag.scroll(-int(delta_y), **pos_kwargs)
        if delta_x != 0:
            hscroll = getattr(pag, "hscroll", None)
            if hscroll is None:
                raise NotImplementedError(
                    "PyAutoGUIDevice 当前平台不支持水平滚动 (pyautogui.hscroll 不可用)"
                )
            hscroll(int(delta_x), **pos_kwargs)

    def goto(self, url: str, **kwargs: Any) -> None:
        raise NotImplementedError(
            "PyAutoGUIDevice 不支持 goto(url): 桌面自动化无 URL 导航概念; "
            "如需启动应用请配合 press_key/hotkey 或外部启动"
        )

    # ---- 窗口管理 (借鉴 WinAppDriver 窗口句柄语义) ----------------------
    @property
    def current_hwnd(self) -> Optional[int]:
        """当前绑定的窗口句柄 (等价 WinAppDriver CurrentWindowHandle); None=全桌面。"""
        return self._hwnd

    @property
    def window_rect(self) -> Optional[tuple[int, int, int, int]]:
        """当前窗口的 (left, top, right, bottom) 屏幕坐标; 未绑定返回 None。"""
        if self._hwnd is None:
            return None
        win32gui = self._import_win32()[0]
        if win32gui is None:
            return None
        try:
            return win32gui.GetWindowRect(self._hwnd)
        except Exception:
            return None

    def is_app_foreground(self) -> Optional[bool]:
        """契约实现 (BaseDevice): 绑定窗口是否处于前台 (GetForegroundWindow 对比)。

        全桌面模式 (未绑定窗口) / 无 pywin32 时返回 None = 无失焦概念, 探索层跳过检测。
        """
        if self._hwnd is None:
            return None
        win32gui = self._import_win32()[0]
        if win32gui is None:
            return None
        try:
            return win32gui.GetForegroundWindow() == self._hwnd
        except Exception:
            return None

    def restore_app_foreground(self) -> Optional[bool]:
        """契约实现 (BaseDevice): 组合拳激活绑定窗口; 返回是否已在前台。

        全桌面模式 (未绑定窗口) / 无 pywin32 时返回 None = 无恢复能力;
        窗口已销毁时按已恢复计 (不阻断)。
        """
        if self._hwnd is None:
            return None
        win32gui, win32con = self._import_win32()
        if win32gui is None:
            return None
        try:
            if not win32gui.IsWindow(self._hwnd):
                return True  # 窗口已销毁, 按已恢复计, 不阻断
            self._bring_to_foreground(win32gui, win32con)
            try:
                return win32gui.GetForegroundWindow() == self._hwnd
            except Exception:
                return True
        except Exception:
            return False

    def focus_window(
        self,
        *,
        hwnd: Optional[int] = None,
        window_title: Optional[str] = None,
        window_class: Optional[str] = None,
    ) -> int:
        """运行时切换目标窗口 (等价 WinAppDriver switch_to.window)。

        三选一指定新窗口; 返回新绑定的 HWND。
        """
        if hwnd is not None:
            self._hwnd = int(hwnd)
        elif window_class:
            win32gui = self._import_win32()[0]
            if win32gui is None:
                raise RuntimeError("无 pywin32 (win32gui), 无法按类名查找窗口")
            h = win32gui.FindWindow(window_class, None)
            if not h:
                raise RuntimeError(f"按类名 '{window_class}' 未找到窗口")
            self._hwnd = h
        elif window_title:
            h = self._find_window_by_title(window_title)
            if not h:
                raise RuntimeError(f"按标题 '{window_title}' 未找到窗口")
            self._hwnd = h
        else:
            raise ValueError("必须指定 hwnd / window_title / window_class 之一")
        return self._hwnd  # type: ignore[return-value]

    # ---- 内部 -----------------------------------------------------------
    @property
    def pyautogui(self):
        if self._pyautogui is None:
            raise RuntimeError("PyAutoGUIDevice 尚未 launch(), 无可用 pyautogui 模块")
        return self._pyautogui

    @staticmethod
    def _xy(coordinate: Coordinate) -> tuple[int, int]:
        return int(coordinate[0]), int(coordinate[1])

    def _resolve_key(self, key: str) -> str:
        normalized = str(key).strip().lower()
        return _KEY_MAP.get(normalized, normalized)

    def _paste_text(self, text: str) -> None:
        """把 text 写到系统剪贴板后 Ctrl+V 粘贴 (用于非 ASCII 字符)。"""
        pag = self.pyautogui
        if self._try_copy_to_clipboard_pyperclip(text):
            pag.hotkey("ctrl", "v")
            return
        if self._try_copy_to_clipboard_win32(text):
            pag.hotkey("ctrl", "v")
            return
        raise NotImplementedError(
            "PyAutoGUIDevice.input_text 含非 ASCII 字符, 但当前环境既无 pyperclip 也无 "
            "win32clipboard, 无法写到系统剪贴板; 请 pip install pyperclip 后重试"
        )

    @staticmethod
    def _try_copy_to_clipboard_pyperclip(text: str) -> bool:
        try:
            import pyperclip  # type: ignore
        except ImportError:
            return False
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            return False

    @staticmethod
    def _try_copy_to_clipboard_win32(text: str) -> bool:
        try:
            import win32clipboard  # type: ignore
        except ImportError:
            return False
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:
            return False

    @staticmethod
    def _try_enable_dpi_awareness() -> None:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # ---- 窗口绑定内部实现 -----------------------------------------------
    @staticmethod
    def _import_win32():
        """懒加载 win32gui / win32con (pywin32); 缺失返回 (None, None)。"""
        try:
            import win32gui  # type: ignore
            import win32con  # type: ignore
            return win32gui, win32con
        except ImportError:
            return None, None

    def _resolve_window(self) -> None:
        """launch() 内调用: 根据构造参数解析目标窗口句柄。

        优先级: hwnd (直接传) > window_class (FindWindow 精确匹配)
              > window_title (EnumWindows 子串匹配)。
        无任何窗口参数时, 保持全桌面模式 (不绑定)。
        """
        if self._hwnd is not None:
            return  # 已通过构造或 focus_window 设置
        win32gui = self._import_win32()[0]
        if win32gui is None:
            if self._window_title or self._window_class:
                raise RuntimeError(
                    "指定了 window_title/window_class, 但当前环境无 pywin32 (win32gui), "
                    "无法查找窗口; 请 pip install pywin32"
                )
            return  # 全桌面模式: 降级为原行为
        if self._window_class:
            hwnd = win32gui.FindWindow(self._window_class, None)
            if not hwnd:
                raise RuntimeError(f"按类名 '{self._window_class}' 未找到窗口")
            self._hwnd = hwnd
            return
        if self._window_title:
            hwnd = self._find_window_by_title(self._window_title)
            if not hwnd:
                raise RuntimeError(f"按标题 '{self._window_title}' 未找到窗口")
            self._hwnd = hwnd

    def _ensure_foreground(self) -> None:
        """每个输入动作前调用: 把绑定的窗口激活到前台 (绕过前台锁组合拳)。"""
        if not self._activate_before_action or self._hwnd is None:
            return
        win32gui, win32con = self._import_win32()
        if win32gui is None:
            return
        try:
            if not win32gui.IsWindow(self._hwnd):
                return  # 窗口已销毁, 不阻断
            self._bring_to_foreground(win32gui, win32con)
        except Exception:
            pass  # 前台权限限制等: 静默降级

    def _bring_to_foreground(self, win32gui: Any, win32con: Any) -> None:
        """绕过 Windows 前台锁激活窗口: AttachThreadInput + 模拟 Alt + SetForegroundWindow。

        SetForegroundWindow 只允许"前台进程 / 最近接收过用户输入的进程"成功:
        1) AttachThreadInput 把本线程输入队列挂到目标窗口线程;
        2) 模拟 Alt 键让本进程获得"最近接收输入"资格;
        3) BringWindowToTop + SetForegroundWindow + SetWindowPos(HWND_TOP) 置顶激活。
        任一步失败不影响整体 (尽力而为)。
        """
        win32gui.ShowWindow(self._hwnd, win32con.SW_RESTORE)
        try:
            import win32api  # type: ignore
            import win32process  # type: ignore
        except ImportError:
            win32api, win32process = None, None
        cur_tid = target_tid = -1
        attached = False
        if win32api is not None and win32process is not None:
            try:
                target_tid = win32process.GetWindowThreadProcessId(self._hwnd)[0]
                cur_tid = win32process.GetCurrentThreadId()
            except Exception:
                target_tid = cur_tid = -1
            if target_tid != cur_tid and cur_tid != -1:
                try:
                    attached = bool(win32gui.AttachThreadInput(cur_tid, target_tid, True))
                except Exception:
                    attached = False
            try:
                # 模拟 Alt 键: 本进程获得"最近接收用户输入"资格, 解除前台锁
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
        try:
            win32gui.BringWindowToTop(self._hwnd)
            win32gui.SetForegroundWindow(self._hwnd)
            win32gui.SetWindowPos(
                self._hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
            )
        finally:
            if attached:
                try:
                    win32gui.AttachThreadInput(cur_tid, target_tid, False)
                except Exception:
                    pass

    def _to_screen(self, x: int, y: int) -> tuple[int, int]:
        """若 coords_relative_to_window=True, 加窗口左上角偏移换算为屏幕坐标。"""
        if not self._coords_relative or self._hwnd is None:
            return x, y
        win32gui = self._import_win32()[0]
        if win32gui is None:
            return x, y
        try:
            left, top, _, _ = win32gui.GetWindowRect(self._hwnd)
            return left + x, top + y
        except Exception:
            return x, y

    @staticmethod
    def _find_window_by_title(title_sub: str) -> int:
        """EnumWindows 遍历, 返回标题包含 title_sub 的第一个可见顶层窗口。"""
        win32gui = PyAutoGUIDevice._import_win32()[0]
        if win32gui is None:
            return 0
        found: list[int] = []

        def _enum_cb(hwnd: int, _lParam: Any) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            text = win32gui.GetWindowText(hwnd)
            if text and title_sub in text:
                found.append(hwnd)
                return False  # 停止遍历
            return True

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            pass
        return found[0] if found else 0


__all__ = ["PyAutoGUIDevice"]
