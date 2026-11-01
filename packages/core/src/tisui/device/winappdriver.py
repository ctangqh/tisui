"""WinAppDriver (Windows Application Driver) 直连设备。

把 BaseDevice 的同步原语映射到 WinAppDriver 的 WebDriver 操作 (经 Appium-Python-Client):
- screenshot()          -> driver.get_screenshot_as_png()  (直接拿 PNG 字节)
- click([x, y])         -> W3C 指针: 绝对移动到 (x,y) 后左键点击
- input_text(text, pos) -> 先点 (x,y) 聚焦, 再向活动元素发送文本 (pos 必填)
- press_key(key, pos)   -> 可选先点 (x,y), 再发送 selenium Keys
- swipe(start, end)     -> W3C 指针: down -> move -> up
- scroll(dx, dy)        -> ActionChains.scroll_by_amount (滚轮)

坐标为 run_pipeline 输出的全屏截图像素坐标; 默认以 Root 会话 (app="Root") 连接整个桌面,
截图为全桌面、点击按绝对屏幕坐标, 二者坐标系一致。

前提: 需本机已运行 WinAppDriver.exe 服务 (默认 127.0.0.1:4723)。
依赖: appium / selenium 为可选运行时依赖, 在 launch() 内懒 import, 不加入 pyproject 强依赖;
导入失败时抛出清晰提示。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from tisui.device.base import BaseDevice, NativeRef, BBox

Coordinate = Sequence[int]  # [x, y]

# 字符串键名 -> selenium.webdriver.common.keys.Keys 成员名。
# 通过 getattr(Keys, name) 解析, 未命中即报错。
_KEY_MAP: dict[str, str] = {
    "enter": "ENTER",
    "return": "ENTER",
    "backspace": "BACKSPACE",
    "delete": "DELETE",
    "tab": "TAB",
    "escape": "ESCAPE",
    "esc": "ESCAPE",
    "space": "SPACE",
    " ": "SPACE",
    "up": "ARROW_UP",
    "arrowup": "ARROW_UP",
    "down": "ARROW_DOWN",
    "arrowdown": "ARROW_DOWN",
    "left": "ARROW_LEFT",
    "arrowleft": "ARROW_LEFT",
    "right": "ARROW_RIGHT",
    "arrowright": "ARROW_RIGHT",
    "home": "HOME",
    "end": "END",
    "pageup": "PAGE_UP",
    "pagedown": "PAGE_DOWN",
}


class WinAppDriverDevice(BaseDevice):
    def __init__(
        self,
        *,
        app: str = "Root",
        app_arguments: str | None = None,
        app_working_dir: str | None = None,
        app_top_level_window: str | None = None,
        server_url: str = "http://127.0.0.1:4723",
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("platform", "windows")
        super().__init__(**kwargs)
        self.app = app
        self.app_arguments = app_arguments
        self.app_working_dir = app_working_dir
        self.app_top_level_window = app_top_level_window
        self.server_url = server_url
        self._driver = None
        self._ActionChains = None
        self._Keys = None

    # ---- 生命周期 -------------------------------------------------------
    def launch(self) -> None:
        try:
            from appium import webdriver
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.keys import Keys
        except ImportError as exc:  # noqa: BLE001
            raise RuntimeError(
                "无法导入 appium/selenium; 请安装 Appium-Python-Client 与 selenium "
                "(pip install Appium-Python-Client selenium), 并确保本机已运行 WinAppDriver.exe"
            ) from exc

        caps: dict[str, Any] = {
            "platformName": "Windows",
            "deviceName": "WindowsPC",
            "app": self.app,
        }
        if self.app_arguments is not None:
            caps["appArguments"] = self.app_arguments
        if self.app_working_dir is not None:
            caps["appWorkingDir"] = self.app_working_dir
        if self.app_top_level_window is not None:
            caps["appTopLevelWindow"] = self.app_top_level_window

        self._driver = self._create_driver(webdriver, caps)
        self._ActionChains = ActionChains
        self._Keys = Keys

    lanch = launch  # 兼容 BaseDevice 抽象方法命名 (上游拼写)

    def close(self) -> bool:
        try:
            if self._driver is not None:
                self._driver.quit()
        finally:
            self._driver = None
            self._ActionChains = None
            self._Keys = None
        return True

    # ---- 感知 -----------------------------------------------------------
    def screenshot(self) -> bytes:
        return self.driver.get_screenshot_as_png()

    # ---- 动作 -----------------------------------------------------------
    def click(self, coordinate: Coordinate) -> None:
        x, y = self._xy(coordinate)
        actions = self._ActionChains(self.driver)
        actions.w3c_actions.pointer_action.move_to_location(x, y).click()
        actions.perform()

    def double_click(self, coordinate: Coordinate) -> None:
        x, y = self._xy(coordinate)
        actions = self._ActionChains(self.driver)
        actions.w3c_actions.pointer_action.move_to_location(x, y).double_click()
        actions.perform()

    def right_click(self, coordinate: Coordinate) -> None:
        x, y = self._xy(coordinate)
        actions = self._ActionChains(self.driver)
        actions.w3c_actions.pointer_action.move_to_location(x, y).context_click()
        actions.perform()

    def input_text(self, text: str, position: Optional[Coordinate] = None) -> None:
        if position is None:
            raise NotImplementedError(
                "WinAppDriverDevice.input_text 需要 position: 按坐标先点击聚焦再输入, "
                "必须指定输入框坐标"
            )
        x, y = self._xy(position)
        actions = self._ActionChains(self.driver)
        actions.w3c_actions.pointer_action.move_to_location(x, y).click()
        actions.perform()
        self._ActionChains(self.driver).send_keys(text).perform()

    def clear_text(self, position: Optional[Coordinate] = None) -> None:
        if position is not None:
            x, y = self._xy(position)
            focus = self._ActionChains(self.driver)
            focus.w3c_actions.pointer_action.move_to_location(x, y).click()
            focus.perform()
        keys = self._Keys
        # Selenium 修饰键成对写法: CONTROL+a+CONTROL 全选, 再 DELETE 删除
        self._ActionChains(self.driver).send_keys(
            keys.CONTROL + "a" + keys.CONTROL
        ).send_keys(keys.DELETE).perform()

    def press_key(self, key: str, position: Optional[Coordinate] = None) -> None:
        key_value = self._resolve_key(key)
        if position is not None:
            x, y = self._xy(position)
            focus = self._ActionChains(self.driver)
            focus.w3c_actions.pointer_action.move_to_location(x, y).click()
            focus.perform()
        self._ActionChains(self.driver).send_keys(key_value).perform()

    def swipe(
        self,
        start: Coordinate,
        end: Coordinate,
        *,
        duration_ms: int = 300,
    ) -> None:
        sx, sy = self._xy(start)
        ex, ey = self._xy(end)
        actions = self._ActionChains(self.driver)
        pointer = actions.w3c_actions.pointer_action
        (
            pointer.move_to_location(sx, sy)
            .pointer_down()
            .pause(max(0.0, duration_ms / 1000))
            .move_to_location(ex, ey)
            .pointer_up()
        )
        actions.perform()

    def scroll(
        self,
        *,
        delta_x: int = 0,
        delta_y: int = 0,
        position: Optional[Coordinate] = None,
    ) -> None:
        if delta_x == 0 and delta_y == 0:
            return
        if position is not None:
            try:
                from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
            except ImportError:
                ScrollOrigin = None
            if ScrollOrigin is not None:
                x, y = self._xy(position)
                origin = ScrollOrigin.from_viewport(x, y)
                self._ActionChains(self.driver).scroll_from_origin(
                    origin, delta_x, delta_y
                ).perform()
                return
        self._ActionChains(self.driver).scroll_by_amount(delta_x, delta_y).perform()

    def goto(self, url: str, **kwargs: Any) -> None:
        raise NotImplementedError(
            "WinAppDriverDevice 不支持 goto(url): Windows 原生设备无 URL 导航概念; "
            "如需启动应用请在构造时传入 app (exe 路径或 AppUserModelId)"
        )

    # ---- explore 可选能力覆写 (loop-design.md §5.7) ----
    # navigate_back: Windows 桌面无全局返回语义, 不覆写 (executor 降级, 见 §6.1 表)

    # ---- 应用前台状态契约覆写 (loop-design §4.7 失焦检测与恢复) ----
    def is_app_foreground(self) -> Optional[bool]:
        """契约实现: 绑定会话窗口是否处于前台 (win32gui.GetForegroundWindow 对比)。

        检测无 WinAppDriver 前台 API, 复用 win32gui (懒加载, 缺失返回 None = 无法检测);
        Root 会话 (app="Root") 无绑定窗口 -> None, 探索层跳过。
        """
        hwnd = self._target_hwnd()
        if hwnd is None:
            return None
        try:
            import win32gui  # type: ignore
        except ImportError:
            return None
        try:
            return win32gui.GetForegroundWindow() == hwnd
        except Exception:
            return None

    def restore_app_foreground(self) -> Optional[bool]:
        """契约实现: WinAppDriver switch_to.window 把绑定窗口激活到前台。

        WinAppDriver POST /session/:id/window 即 Set focus (见官方 Window.cs 测试);
        Root 会话 (app="Root") 无绑定窗口 -> None = 无恢复能力。
        """
        handle = self._target_window_handle()
        if handle is None:
            return None
        try:
            self.driver.switch_to.window(handle)
            return True
        except Exception:
            return False

    def resolve_native_ref(self, coordinate: Coordinate) -> Optional[NativeRef]:
        """拉 UIA 树, 找到 bounding rect 包含该坐标的最深节点。

        稳定性判据 (§5.7): 有 AutomationId 时 kind='automation_id';
        Name 可变但允许低优先级 kind='name' (命中率自限, 文本变自然 miss);
        自动生成的 RuntimeId 绝对不存 (进程重启就变)。
        """
        x, y = self._xy(coordinate)
        try:
            driver = self.driver
            try:
                # WinAppDriver 扩展命令: /element/from_point
                # GET session/<id>/element/from_point?x=&y=  (部分版本支持)
                url = driver.command_executor._url + f"/session/{driver.session_id}/element/from_point"
                params = {"x": x, "y": y}
                resp = driver.command_executor._request("POST", url, params)
                if isinstance(resp, dict) and resp.get("status") in (0, None) and resp.get("value"):
                    value = resp["value"]
                    el = None
                    # 不同版本返回 {ELEMENT:..} 或 {element-6066-11e4-a52e-4f735466cecf:..}
                    for k in ("ELEMENT", "element-6066-11e4-a52e-4f735466cecf"):
                        if isinstance(value, dict) and k in value:
                            from appium.webdriver.webelement import WebElement
                            el = WebElement(driver, value[k])
                            break
                    if el is None:
                        return None
                    return _ref_from_webelement(el)
            except Exception:
                pass
            # 兜底: driver.find_elements + rect 命中匹配 (慢, 但能兼容)
            try:
                from selenium.webdriver.common.by import By
                all_els = driver.find_elements(By.XPATH, "//*")
            except Exception:
                return None
            best: Any = None
            best_area = float("inf")
            for el in all_els:
                b = _rect_of_webelement(el)
                if b is None:
                    continue
                x1, y1, x2, y2 = b
                if not (x1 <= x <= x2 and y1 <= y <= y2):
                    continue
                area = max(0, x2 - x1) * max(0, y2 - y1)
                if area <= 0 or area >= best_area:
                    continue
                best_area = area
                best = el
            if best is not None:
                return _ref_from_webelement(best)
        except Exception:
            return None
        return None

    def rect_by_native_ref(self, ref: NativeRef) -> Optional[BBox]:
        if not isinstance(ref, dict):
            return None
        kind = str(ref.get("kind") or "").strip().lower()
        value = ref.get("value")
        if value is None:
            return None
        try:
            from selenium.webdriver.common.by import By
            driver = self.driver
            if kind == "automation_id":
                locator = (By.XPATH, f'//*[@AutomationId="{_escape_xpath(str(value))}"]')
            elif kind == "name":
                locator = (By.XPATH, f'//*[@Name="{_escape_xpath(str(value))}"]')
            else:
                return None
            el = driver.find_element(*locator)
        except Exception:
            return None
        return _rect_of_webelement(el)

    # ---- 内部 -----------------------------------------------------------
    @property
    def driver(self):
        if self._driver is None:
            raise RuntimeError("WinAppDriverDevice 尚未 launch(), 无可用 driver")
        return self._driver

    def _create_driver(self, webdriver: Any, caps: dict[str, Any]) -> Any:
        """WinAppDriver 会话创建兼容层。

        本机 WinAppDriver 1.2.x 对 W3C capabilities.alwaysMatch 支持不完整, 只认
        JSON Wire 的 desiredCapabilities; 而 selenium>=4 只发 W3C 格式 (desired_capabilities
        参数已移除), appium>=2 客户端又会把 app 等键加 appium: 前缀 —— 两条路都会报
        "Bad capabilities. Specify either app or appTopLevelWindow"。
        因此用标准库 urllib 按 desiredCapabilities 创建会话, 再把 selenium Remote
        挂接到该 session_id (子类覆盖 start_session 跳过二次建会话)。
        """
        import json as _json
        import urllib.request

        from selenium import webdriver as _se_webdriver
        from selenium.webdriver.remote.webdriver import BaseOptions

        req = urllib.request.Request(
            f"{self.server_url}/session",
            data=_json.dumps({"desiredCapabilities": caps}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        session_id = data.get("sessionId")
        if not session_id:
            raise RuntimeError(f"WinAppDriver 创建会话失败: {data!r}")
        value = data.get("value") or {}

        class _AttachedRemote(_se_webdriver.Remote):
            """不自行创建会话: 会话已由 desiredCapabilities 请求建好, 直接挂接。"""

            def start_session(self, capabilities):  # noqa: ARG002
                self.session_id = session_id
                self.caps = value

        class _WadOptions(BaseOptions):
            @property
            def default_capabilities(self):
                return {}

            def to_capabilities(self):
                return dict(self._caps)

        opts = _WadOptions()
        opts.set_capability("platformName", str(caps.get("platformName") or "Windows"))
        return _AttachedRemote(command_executor=self.server_url, options=opts)

    @staticmethod
    def _xy(coordinate: Coordinate) -> tuple[int, int]:
        return int(coordinate[0]), int(coordinate[1])

    def _target_window_handle(self) -> Optional[str]:
        """WinAppDriver 会话当前窗口句柄 (字符串); Root 会话/异常 -> None。"""
        try:
            handle = self.driver.current_window_handle
            if handle is None:
                return None          # Root 会话等无窗口句柄
            text = str(handle).strip()
            return text or None
        except Exception:
            return None

    def _target_hwnd(self) -> Optional[int]:
        """把会话窗口句柄转成整数 hwnd (兼容十进制与 0x 十六进制); 取不到 -> None。"""
        handle = self._target_window_handle()
        if not handle:
            return None
        try:
            return int(handle)
        except (TypeError, ValueError):
            try:
                return int(handle, 16) if handle.lower().startswith("0x") else None
            except (TypeError, ValueError):
                return None

    def _resolve_key(self, key: str) -> Any:
        name = _KEY_MAP.get(str(key).strip().lower())
        if name is None:
            raise NotImplementedError(f"WinAppDriverDevice 暂不支持按键: {key!r}")
        value = getattr(self._Keys, name, None)
        if value is None:
            raise RuntimeError(
                f"当前 selenium Keys 无成员 {name!r} (映射自按键 {key!r})"
            )
        return value


__all__ = ["WinAppDriverDevice"]


def _rect_of_webelement(el: Any) -> Optional[BBox]:
    """Selenium/Appium WebElement -> 屏幕像素 bbox (x1,y1,x2,y2)。"""
    try:
        loc = el.location  # {'x': .., 'y': ..}
        size = el.size    # {'width': .., 'height': ..}
        if not isinstance(loc, dict) or not isinstance(size, dict):
            return None
        x = int(loc.get("x", 0)); y = int(loc.get("y", 0))
        w = int(size.get("width", 0)); h = int(size.get("height", 0))
        if w <= 0 or h <= 0:
            return None
        return (x, y, x + w, y + h)
    except Exception:
        return None


def _ref_from_webelement(el: Any) -> Optional[NativeRef]:
    """§5.7 稳定性判据: 有 AutomationId 才存; Name 允许但低优先级; RuntimeId 绝对不存。"""
    for attr_name, attr_kind in (
        ("get_attribute", None),  # callable 需要 name 形参调用
    ):
        _ = attr_name
    # 优先取 AutomationId (UIA 属性)
    try:
        aid = el.get_attribute("AutomationId")
    except Exception:
        aid = None
    if isinstance(aid, str) and aid.strip():
        return {"kind": "automation_id", "value": aid.strip()}
    # 其次 Name (文案, 低优先级, 允许存, 不稳定会自己 miss)
    try:
        name_val = None
        for method_name in ("text", "get_attribute"):
            method = getattr(el, method_name, None)
            if method_name == "text" and not callable(method):
                name_val = method
            elif method_name == "get_attribute" and callable(method):
                for attr in ("Name", "name"):
                    try:
                        v = method(attr)
                        if isinstance(v, str) and v.strip():
                            name_val = v
                            break
                    except Exception:
                        continue
            elif callable(method):
                continue
            if isinstance(name_val, str) and name_val.strip():
                break
        if isinstance(name_val, str) and name_val.strip():
            return {"kind": "name", "value": name_val.strip()}
    except Exception:
        return None
    return None


def _escape_xpath(s: str) -> str:
    """XPath 字符串内部转义 (含双引号时用 concat 表达式)。"""
    if '"' not in s:
        return s
    parts = s.split('"')
    built = [f"'\"'" if chunk == "" else f'"{chunk}"' for chunk in parts]
    return "concat(" + ",".join(part for tup in ((b, "'\"'") for b in built[:-1]) for part in tup if part) + f', {built[-1]})' if False \
        else "concat(" + ",".join(built) + ")"

