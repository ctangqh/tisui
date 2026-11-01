"""Hypium (HarmonyOS UiDriver) 直连设备。

把 BaseDevice 的同步原语映射到 Hypium 6.1.0 的 UiDriver 操作:
- screenshot()          -> capture_screen 落临时 png 后读回字节 (Hypium 无 bytes 截图)
- click([x, y])         -> driver.touch((x, y))
- input_text(text, pos) -> driver.input_text((x, y), text)  (pos 必填)
- press_key(key, pos)   -> 可选先 touch(pos), 再 driver.press_key(KeyCode.X)
- swipe(start, end)     -> driver.slide(start, end)
- scroll(dx, dy)        -> driver.swipe(direction, distance)  (方向近似)

坐标为 run_pipeline 输出的截图像素坐标; 与 touch 使用的设备物理像素一致的前提是
screenshot() 始终全屏截图、不裁剪 (等同 PlaywrightDevice device_scale_factor=1)。

依赖: hypium 为 HarmonyOS 私有测试框架, 非 pip 公有包, 故在 launch() 内懒 import,
不加入 pyproject 强依赖; 导入失败时抛出清晰提示。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any, Optional, Sequence

from tisui.device.base import BaseDevice, NativeRef, BBox
from tisui.shared.config import CACHE_ROOT

Coordinate = Sequence[int]  # [x, y]

# 字符串键名 -> Hypium KeyCode 枚举成员名 (去 KEYCODE_ 前缀)。
# 通过 getattr(KeyCode, name) 解析, 防枚举名漂移; 未命中即报错。
_KEY_MAP: dict[str, str] = {
    "enter": "ENTER",
    "return": "ENTER",
    "backspace": "DEL",
    "delete": "FORWARD_DEL",
    "tab": "TAB",
    "escape": "ESCAPE",
    "esc": "ESCAPE",
    "space": "SPACE",
    " ": "SPACE",
    "up": "DPAD_UP",
    "arrowup": "DPAD_UP",
    "down": "DPAD_DOWN",
    "arrowdown": "DPAD_DOWN",
    "left": "DPAD_LEFT",
    "arrowleft": "DPAD_LEFT",
    "right": "DPAD_RIGHT",
    "arrowright": "DPAD_RIGHT",
    "home": "MOVE_HOME",
    "end": "MOVE_END",
    "pageup": "PAGE_UP",
    "pagedown": "PAGE_DOWN",
    "back": "BACK",
}


class HypiumDevice(BaseDevice):
    def __init__(
        self,
        *,
        device_sn: str | None = None,
        connector: str = "hdc",
        connector_server: tuple[str, int] | None = None,
        report_path: str | None = None,
        log_level: str = "info",
        start_app: str | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("platform", "harmony")
        super().__init__(**kwargs)
        self.device_sn = device_sn
        self.connector = connector
        self.connector_server = connector_server
        self.report_path = report_path
        self.log_level = log_level
        self.start_app = start_app
        self._driver = None
        self._KeyCode = None
        self._UiParam = None
        # hypium/xdevice 库会在进程 CWD 下创建两个副作用目录 (均不可通过参数关闭):
        #   1) tmp_hypium/    - capture_screen(in_pc=True) 存放 hdc pull 回来的中间截图
        #   2) report/        - xdevice reporter 写 task_log.log 等报告产物
        # 这里统一做生命周期治理: tmp_hypium 重定向到 CACHE_ROOT 下, report 仅做启动清空 + close 删除。
        self._tmp_hypium_dir: Optional[str] = None
        self._original_cwd: Optional[str] = None
        self._cwd_report_dir: Optional[str] = None

    # ---- 生命周期 -------------------------------------------------------
    def launch(self) -> None:
        try:
            from hypium import UiDriver, KeyCode
            from hypium.model import UiParam
        except ImportError as exc:  # noqa: BLE001
            raise RuntimeError(
                "无法导入 hypium; 请确认已在当前环境安装 HarmonyOS 测试框架 hypium "
                "(from hypium import UiDriver, KeyCode, UiParam)"
            ) from exc

        connect_kwargs: dict[str, Any] = {"log_level": self.log_level}
        if self.device_sn is not None:
            connect_kwargs["device_sn"] = self.device_sn
        if self.connector_server is not None:
            connect_kwargs["connector_server"] = self.connector_server
        # ---- 默认把 hypium 的落盘日志目录放到 CACHE_ROOT/hypium_report 下 ----
        # hypium 的 UiDriver.connect(report_path=...) 会转传给 xdevice EnvPool,
        # 进而决定 task_log.log 等报告产物的位置; 未传时 xdevice 默认写到 CWD/reports/<timestamp>/,
        # 会污染工程根目录。这里默认重定向到 .cache 下, 用户显式传入 report_path 时优先级更高。
        effective_report_path = self.report_path
        if not effective_report_path:
            effective_report_path = os.path.join(str(CACHE_ROOT), "hypium_report")
        os.makedirs(effective_report_path, exist_ok=True)
        connect_kwargs["report_path"] = effective_report_path

        self._driver = UiDriver.connect(connector=self.connector, **connect_kwargs)
        self._KeyCode = KeyCode
        self._UiParam = UiParam

        # ---- 把 hypium 副作用目录 tmp_hypium 重定向到 cache_path 下 ----
        # 注: hypium capture_screen(in_pc=True) 内部会在进程 CWD 下创建 tmp_hypium/ 存放 hdc pull 回来的中间截图,
        #     调用方无法通过参数关闭。这里预先在 CACHE_ROOT 下建好同名目录, 并一次性清空旧产物。
        tmp_dir = os.path.join(str(CACHE_ROOT), "tmp_hypium")
        os.makedirs(tmp_dir, exist_ok=True)
        # 启动时一次性清理: 仅清空子项 (rmtree 后再 mkdir 也可, 但保留目录本身更稳)
        for name in os.listdir(tmp_dir):
            p = os.path.join(tmp_dir, name)
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            except OSError:
                pass
        self._tmp_hypium_dir = tmp_dir

        # ---- 启动时清空根目录 report/ 旧产物 (xdevice reporter 硬编码写入 CWD/report) ----
        # 仅清空子项, 不删除目录本身 (xdevice 运行时还要往里写 task_log.log)。
        cwd_report = os.path.join(os.getcwd(), "report")
        if os.path.isdir(cwd_report) and not os.path.islink(cwd_report):
            for name in os.listdir(cwd_report):
                p = os.path.join(cwd_report, name)
                try:
                    if os.path.isdir(p) and not os.path.islink(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        try:
                            os.remove(p)
                        except OSError:
                            pass
                except OSError:
                    pass
        self._cwd_report_dir = cwd_report

        if self.start_app:
            self._driver.start_app(self.start_app)

    lanch = launch  # 兼容 BaseDevice 抽象方法命名 (上游拼写)

    def close(self) -> bool:
        try:
            if self._driver is not None:
                self._driver.close()
        finally:
            self._driver = None
            self._KeyCode = None
            self._UiParam = None
            # 关闭时删除 launch() 期间重定向到 CACHE_ROOT 下的 tmp_hypium 目录,
            # 避免残留中间截图; 失败不阻断 close。
            if self._tmp_hypium_dir:
                try:
                    shutil.rmtree(self._tmp_hypium_dir, ignore_errors=True)
                except OSError:
                    pass
            # 关闭时删除根目录下 xdevice reporter 生成的 report/ 目录,
            # 避免残留 task_log.log 等报告产物; 失败不阻断 close。
            if self._cwd_report_dir and os.path.isdir(self._cwd_report_dir):
                try:
                    shutil.rmtree(self._cwd_report_dir, ignore_errors=True)
                except OSError:
                    pass
            self._tmp_hypium_dir = None
            self._cwd_report_dir = None
            self._original_cwd = None
        return True

    # ---- 感知 -----------------------------------------------------------
    def screenshot(self) -> bytes:
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        prev_cwd = os.getcwd()
        # 临时切 CWD 到 tmp_hypium_dir, 让 hypium 库产生的 tmp_hypium/ 副作用落在 cache_path 下
        if self._tmp_hypium_dir:
            try:
                os.chdir(self._tmp_hypium_dir)
            except OSError:
                pass
        try:
            self.driver.capture_screen(path, in_pc=True)
            with open(path, "rb") as fp:
                return fp.read()
        finally:
            # 无论如何恢复 CWD, 避免影响同进程其他相对路径访问
            try:
                os.chdir(prev_cwd)
            except OSError:
                pass
            try:
                os.remove(path)
            except OSError:
                pass

    # ---- 动作 -----------------------------------------------------------
    def click(self, coordinate: Coordinate) -> None:
        self.driver.touch(self._xy(coordinate))

    def double_click(self, coordinate: Coordinate) -> None:
        # 触摸双击手势: driver.touch(pos, mode=UiParam.DOUBLE)
        self.driver.touch(self._xy(coordinate), mode=self._UiParam.DOUBLE)

    def right_click(self, coordinate: Coordinate) -> None:
        # 鼠标右键: 仅对接鼠标的 HarmonyOS 设备有效 (平板/PC 外接鼠标场景)
        try:
            from hypium.model import MouseButton
        except ImportError as exc:  # noqa: BLE001
            raise RuntimeError(
                "无法导入 hypium.model.MouseButton; 请确认 hypium 版本支持鼠标操作"
            ) from exc
        self.driver.mouse_click(self._xy(coordinate), MouseButton.MOUSE_BUTTON_RIGHT)

    def input_text(self, text: str, position: Optional[Coordinate] = None) -> None:
        if position is None:
            raise NotImplementedError(
                "HypiumDevice.input_text 需要 position: Hypium 无\"当前焦点输入\", "
                "必须指定输入框坐标或控件"
            )
        self.driver.input_text(self._xy(position), text)

    def clear_text(self, position: Optional[Coordinate] = None) -> None:
        if position is None:
            raise NotImplementedError(
                "HypiumDevice.clear_text 需要 position: Hypium 无\"当前焦点\"概念, "
                "必须指定输入框坐标"
            )
        # hypium input_text 默认行为: 先清空控件中的文本再执行输入, 输入空串即为清空
        # (driver.clear_text 仅支持 ISelector/IUiComponent, 不支持坐标, 故走 input_text)
        self.driver.input_text(self._xy(position), "")

    def press_key(self, key: str, position: Optional[Coordinate] = None) -> None:
        key_code = self._resolve_keycode(key)
        if position is not None:
            self.driver.touch(self._xy(position))
        self.driver.press_key(key_code)

    def swipe(
        self,
        start: Coordinate,
        end: Coordinate,
        *,
        duration_ms: int = 300,
    ) -> None:
        self.driver.slide(
            self._xy(start), self._xy(end), slide_time=max(0.0, duration_ms / 1000)
        )

    def scroll(
        self,
        *,
        delta_x: int = 0,
        delta_y: int = 0,
        position: Optional[Coordinate] = None,
    ) -> None:
        # position 暂不支持区域滚动: hypium swipe 为全屏手势, 接受参数仅为签名对齐
        direction, distance = self._scroll_gesture(delta_x, delta_y)
        if direction is None:
            return
        self.driver.swipe(direction, distance=distance)

    def goto(self, url: str, **kwargs: Any) -> None:
        raise NotImplementedError(
            "HypiumDevice 不支持 goto(url): HarmonyOS 原生设备无 URL 导航概念; "
            "如需启动应用请在构造时传入 start_app 包名"
        )

    # ---- explore 可选能力覆写 (loop-design.md §5.7 + §6.1) ----
    def navigate_back(self) -> None:
        # Hypium Back 键: 按 §6.1 表 = Back 键
        key_code = getattr(self._KeyCode, "BACK", None)
        if key_code is None:
            return None
        try:
            self.driver.press_key(key_code)
        except Exception:
            return None

    # ---- 应用前台状态契约覆写 (loop-design §4.7 失焦检测与恢复) ----
    def is_app_foreground(self) -> Optional[bool]:
        """契约实现: 前台 app 包名 == 被测包名 (driver.current_app())。

        current_app() 读取失败 (返回 None) 或未配置 start_app 包名时返回 None
        = 无法检测, 探索层跳过 (不误判失焦)。
        """
        if not self.start_app:
            return None
        try:
            pkg, _page = self.driver.current_app() or (None, None)
            if not pkg:
                return None          # 读取失败, 跳过
            return pkg == self.start_app
        except Exception:
            return None

    def restore_app_foreground(self) -> Optional[bool]:
        """契约实现: start_app 把被测应用拉回前台; 返回是否已恢复。

        未配置 start_app 包名时返回 None = 无恢复能力 (探索层按失败累计)。
        """
        if not self.start_app:
            return None
        try:
            self.driver.start_app(self.start_app)
            return True
        except Exception:
            return False

    def resolve_native_ref(self, coordinate: Coordinate) -> Optional[NativeRef]:
        """Hypium UI 树 dump → 找到 bounding rect 包含坐标的最深组件, 返回 BY.id/文字。

        稳定性判据 (§5.7): 有 id 时存 kind='by_id', 否则 kind='hypium_text'(低优先级允许)。
        """
        x, y = self._xy(coordinate)
        try:
            # hypium 一般支持 dump UI 树; 不同版本 API 名称差异较大, 这里使用鸭子类型尝试:
            #   1) driver.dump_hierarchy()  -> str
            #   2) driver.dump_ui_tree()
            #   3) driver.dump()
            dump_str = None
            for attr in ("dump_hierarchy", "dump_ui_tree", "dump"):
                fn = getattr(self._driver, attr, None)
                if callable(fn):
                    try:
                        dump_str = fn()
                        if isinstance(dump_str, (list, dict)):
                            return _ref_from_tree(dump_str, x, y)
                        if isinstance(dump_str, str) and dump_str.strip():
                            break
                    except Exception:
                        continue
            if isinstance(dump_str, str) and dump_str.strip():
                return _ref_from_xml(dump_str, x, y)
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
            from hypium import BY
        except ImportError:
            return None
        try:
            if kind == "by_id":
                comp = self.driver.find_component(BY.id(str(value)))
            elif kind == "hypium_text":
                comp = self.driver.find_component(BY.text(str(value)))
            else:
                return None
        except Exception:
            return None
        if comp is None:
            return None
        # Hypium IUiComponent 通常有 bounds() / rect 属性, 返回 [x1, y1, x2, y2]
        bbox = None
        for attr in ("bounds", "rect", "get_bounds", "getRect"):
            fn = getattr(comp, attr, None)
            try:
                if callable(fn):
                    r = fn()
                else:
                    r = fn
            except Exception:
                continue
            if isinstance(r, (list, tuple)) and len(r) == 4:
                bbox = r
                break
            if isinstance(r, dict):
                for k1, k2 in (("left", "top", "right", "bottom"), ("x", "y", "width", "height")):
                    try:
                        if all(k in r for k in k1):
                            bbox = [r[k1[0]], r[k1[1]], r[k1[2]], r[k1[3]]]
                            break
                    except Exception:
                        continue
                if bbox is not None:
                    break
        if bbox is None:
            return None
        try:
            vals = [int(v) for v in bbox]
            # bounds 可能是 [x, y, w, h], 需要转 x1,y1,x2,y2
            # 如果第三项 <= 第一项 → 视为宽高型
            if len(vals) == 4:
                if vals[2] <= vals[0] or vals[3] <= vals[1]:
                    x, y, w, h = vals
                    vals = [x, y, x + w, y + h]
            x1, y1, x2, y2 = vals
            if x2 > x1 and y2 > y1:
                return (x1, y1, x2, y2)
        except (TypeError, ValueError):
            return None
        return None

    # ---- 内部 -----------------------------------------------------------
    @property
    def driver(self):
        if self._driver is None:
            raise RuntimeError("HypiumDevice 尚未 launch(), 无可用 driver")
        return self._driver

    @staticmethod
    def _xy(coordinate: Coordinate) -> tuple[int, int]:
        return int(coordinate[0]), int(coordinate[1])

    def _resolve_keycode(self, key: str) -> Any:
        name = _KEY_MAP.get(str(key).strip().lower())
        if name is None:
            raise NotImplementedError(f"HypiumDevice 暂不支持按键: {key!r}")
        key_code = getattr(self._KeyCode, name, None)
        if key_code is None:
            raise RuntimeError(
                f"当前 hypium KeyCode 无成员 {name!r} (映射自按键 {key!r})"
            )
        return key_code

    def _scroll_gesture(
        self, delta_x: int, delta_y: int
    ) -> tuple[Optional[str], int]:
        # 取绝对值更大的轴为主方向; 屏幕滚动方向与手指滑动方向相反。
        up = getattr(self._UiParam, "UP", "UP")
        down = getattr(self._UiParam, "DOWN", "DOWN")
        left = getattr(self._UiParam, "LEFT", "LEFT")
        right = getattr(self._UiParam, "RIGHT", "RIGHT")
        if abs(delta_y) >= abs(delta_x):
            if delta_y == 0:
                return None, 0
            direction = up if delta_y > 0 else down
            magnitude = abs(delta_y)
        else:
            direction = left if delta_x > 0 else right
            magnitude = abs(delta_x)
        distance = max(1, min(100, magnitude // 5))
        return direction, distance


__all__ = ["HypiumDevice"]


# ---- Hypium UI 树解析辅助 (resolve_native_ref 用, 鸭子类型兼容多版本)


def _bbox_of(node: Any) -> tuple[int, int, int, int] | None:
    """从一个 UI 树节点尽力取 [x1,y1,x2,y2]; 取不到返回 None。

    兼容:
      - 属性 bounds = [x1,y1,x2,y2] 或 (x, y, w, h)
      - 属性 rect / bound / boundingRect (可 dict/list/对象)
      - dict 节点: {bounds: ..., rect: ..., left/top/right/bottom: ..., x/y/width/height: ...}
    """
    def _from_seq(xx: Any) -> tuple[int, int, int, int] | None:
        if not isinstance(xx, (list, tuple)) or len(xx) != 4:
            return None
        try:
            return (int(xx[0]), int(xx[1]), int(xx[2]), int(xx[3]))
        except (TypeError, ValueError):
            return None
    if isinstance(node, dict):
        for key in ("bounds", "rect", "bound", "boundingRect", "bbox"):
            if key in node:
                b = _from_seq(node[key])
                if b is not None:
                    return b
        keys = node.keys()
        if all(k in keys for k in ("left", "top", "right", "bottom")):
            try:
                return (int(node["left"]), int(node["top"]), int(node["right"]), int(node["bottom"]))
            except (TypeError, ValueError):
                pass
        if all(k in keys for k in ("x", "y", "width", "height")):
            try:
                x, y, w, h = int(node["x"]), int(node["y"]), int(node["width"]), int(node["height"])
                return (x, y, x + w, y + h)
            except (TypeError, ValueError):
                pass
    else:
        for attr in ("bounds", "rect", "bound", "boundingRect", "bbox"):
            v = getattr(node, attr, None)
            b = _from_seq(v)
            if b is not None:
                return b
    return None


def _normalise_bbox(b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """bounds 格式容忍: [x1,y1,x2,y2] 或 [x,y,w,h] (w>0,h>0, 按 x2,y2 相对量级判断)。"""
    x1, y1, x2, y2 = b
    if x2 > x1 and y2 > y1 and x2 - x1 < 65535 and y2 - y1 < 65535:
        return (x1, y1, x2, y2)
    # 视为 [x, y, w, h]
    return (x1, y1, x1 + x2, y1 + y2)


def _id_of(node: Any) -> str | None:
    if isinstance(node, dict):
        for k in ("id", "Id", "ID", "resource-id", "resid", "componentId", "compId"):
            if k in node and str(node[k]).strip():
                return str(node[k]).strip()
    else:
        for attr in ("id", "component_id", "comp_id", "resId", "resource_id"):
            v = getattr(node, attr, None)
            if v and str(v).strip():
                return str(v).strip()
    return None


def _text_of(node: Any) -> str | None:
    if isinstance(node, dict):
        for k in ("text", "Text", "label", "content-desc", "contentDescription"):
            if k in node and str(node[k]).strip():
                return str(node[k]).strip()
    else:
        for attr in ("text", "label", "content_desc", "description"):
            v = getattr(node, attr, None)
            if v and str(v).strip():
                return str(v).strip()
    return None


def _children_of(node: Any) -> list[Any]:
    if isinstance(node, dict):
        for k in ("children", "child", "nodes", "subnodes", "elements"):
            if k in node and isinstance(node[k], (list, tuple)):
                return list(node[k])
        return []
    for attr in ("children", "child_nodes", "subnodes", "nodes", "elements"):
        v = getattr(node, attr, None)
        if isinstance(v, (list, tuple)):
            return list(v)
    # 可迭代且非字符串 (鸭子类型)
    if hasattr(node, "__iter__") and not isinstance(node, (str, bytes)):
        try:
            return [c for c in node]
        except Exception:  # noqa: BLE001
            return []
    return []


def _contains(b: tuple[int, int, int, int], x: int, y: int) -> bool:
    return b[0] <= x <= b[2] and b[1] <= y <= b[3]


def _area(b: tuple[int, int, int, int]) -> int:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _ref_from_tree(root: Any, x: int, y: int) -> Optional[NativeRef]:
    """在 dict/对象 UI 树中递归找包围 (x,y) 的最深节点, 返回 by_id/hypium_text。"""
    best: Any = None
    best_area = float("inf")

    def walk(node: Any) -> None:
        nonlocal best, best_area
        b = _bbox_of(node)
        if b is None:
            pass
        else:
            b = _normalise_bbox(b)
            if _contains(b, x, y):
                a = _area(b)
                if a < best_area:
                    nonlocal_local = best, best_area  # avoid pyflakes
                    best = node
                    best_area = a
        for c in _children_of(node):
            walk(c)
    # 忽略 walk 未使用 (上面通过闭包写入)
    if False:
        _ = nonlocal_local if False else None
    walk(root)
    if best is None:
        return None
    iid = _id_of(best)
    if iid:
        return {"kind": "by_id", "value": iid}
    txt = _text_of(best)
    if txt:
        return {"kind": "hypium_text", "value": txt}
    return None


def _ref_from_xml(xml: str, x: int, y: int) -> Optional[NativeRef]:
    """最朴素的 XML/伪 XML 解析: 正则抽每个 node 的 bounds/id/text, 选命中最深。"""
    import re
    bounds_re = re.compile(
        r'bounds(?:\s*=\s*")?\s*\[?\s*(\d+)\s*[, ]\s*(\d+)\s*[, )\]]\s*(\d+)\s*[, )\]]\s*(\d+)',
        re.IGNORECASE,
    )
    id_re = re.compile(r'(?:resource-id|id|component-id|res-id|compId)(?:\s*=\s*"|\s+)([^"/\s>]+)', re.IGNORECASE)
    text_re = re.compile(r'(?:text|content-desc|label)(?:\s*=\s*")([^"]*)', re.IGNORECASE)
    nodes = re.split(r"<\s*/?\s*(?!--)", xml)
    best: NativeRef | None = None
    best_area = float("inf")
    for chunk in nodes:
        m = bounds_re.search(chunk)
        if not m:
            continue
        try:
            b = _normalise_bbox((int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))))
        except ValueError:
            continue
        if not _contains(b, x, y):
            continue
        a = _area(b)
        if a >= best_area:
            continue
        iid = id_re.search(chunk)
        txt = text_re.search(chunk)
        value = None
        kind = None
        if iid and iid.group(1).strip():
            kind, value = "by_id", iid.group(1).strip()
        elif txt and txt.group(1).strip():
            kind, value = "hypium_text", txt.group(1).strip()
        if kind is not None and value is not None:
            best_area = a
            best = {"kind": kind, "value": value}
    return best
