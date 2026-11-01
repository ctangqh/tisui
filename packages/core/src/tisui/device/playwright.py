"""Playwright 直连设备 (一期同步实现)。

包一个 playwright sync Page, 把 BaseDevice 的同步原语映射到浏览器操作:
- screenshot()            -> PNG bytes
- click([x, y])           -> page.mouse.click
- input_text(text, pos)   -> 可选先点位, 再 keyboard.type
- press_key(key, pos)     -> 可选先点位, 再 keyboard.press

坐标为 run_pipeline 输出的 raw 像素坐标; device_scale_factor=1 时与 CSS 像素一致。
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from tisui.device.base import BaseDevice, ScrollState, NativeRef, BBox

Coordinate = Sequence[int]  # [x, y]

# 从坐标点向上查找可滚动祖先容器; 无坐标或未命中时回退到页面根滚动容器。
_JS_FIND_SCROLLABLE = """
(pos) => {
  const scrollable = (el, axis) => {
    const st = getComputedStyle(el);
    const ov = axis === 'y' ? st.overflowY : st.overflowX;
    const can = ['auto', 'scroll', 'overlay'].includes(ov);
    return axis === 'y'
      ? can && el.scrollHeight > el.clientHeight
      : can && el.scrollWidth > el.clientWidth;
  };
  let el = null;
  if (pos) {
    let cur = document.elementFromPoint(pos[0], pos[1]);
    while (cur && cur !== document.body && cur !== document.documentElement) {
      if (scrollable(cur, 'y') || scrollable(cur, 'x')) { el = cur; break; }
      cur = cur.parentElement;
    }
  }
  if (!el) el = document.scrollingElement || document.documentElement;
  return el;
}
"""

# elementFromPoint → 生成稳定 CSS 选择器 (有 id/data-testid/name 优先, 否则返回 None 表示不稳)
_JS_RESOLVE_NATIVE_REF = """
(pos) => {
  let el = document.elementFromPoint(pos[0], pos[1]);
  if (!el) return null;
  const id = el.getAttribute && el.getAttribute('id');
  if (id) return {kind: 'id', value: id};
  const dt = el.getAttribute && (el.getAttribute('data-testid') || el.getAttribute('data-test-id') || el.getAttribute('data_testid'));
  if (dt) return {kind: 'data-testid', value: dt};
  const nm = el.getAttribute && el.getAttribute('name');
  if (nm) return {kind: 'name', value: nm};
  return null;
}
"""

# 按 NativeRef 查实时 bbox (CSS 像素), 返回 [x1,y1,x2,y2] 或 null
_JS_RECT_BY_REF = """
(ref) => {
  if (!ref || !ref.kind || ref.value === undefined || ref.value === null) return null;
  let el = null;
  try {
    switch (ref.kind) {
      case 'id':        el = document.getElementById(String(ref.value)); break;
      case 'name':      el = document.querySelector(`[name="${String(ref.value).replace(/"/g, '\\"')}"]`); break;
      case 'data-testid':
      case 'data_testid': {
        const v = String(ref.value).replace(/"/g, '\\"');
        el = document.querySelector(`[data-testid="${v}"],[data-test-id="${v}"],[data_testid="${v}"]`);
        break;
      }
      case 'css':       el = document.querySelector(String(ref.value)); break;
      default:          return null;
    }
  } catch (_) { return null; }
  if (!el || !el.getBoundingClientRect) return null;
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  const offX = window.scrollX || window.pageXOffset || 0;
  const offY = window.scrollY || window.pageYOffset || 0;
  return [Math.round(r.left + offX), Math.round(r.top + offY),
          Math.round(r.right + offX), Math.round(r.bottom + offY)];
}
"""


class PlaywrightDevice(BaseDevice):
    def __init__(
        self,
        *,
        headless: bool = True,
        viewport: tuple[int, int] = (1280, 800),
        start_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("platform", "web")
        super().__init__(**kwargs)
        self.headless = headless
        self.viewport = viewport
        self.start_url = start_url
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # ---- 生命周期 -------------------------------------------------------
    def launch(self) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        width, height = self.viewport
        self._context = self._browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        self._page = self._context.new_page()
        if self.start_url:
            self._page.goto(self.start_url, wait_until="domcontentloaded")

    lanch = launch  # 兼容 BaseDevice 抽象方法命名 (上游拼写), 见交付说明

    def close(self) -> bool:
        try:
            if self._browser is not None:
                self._browser.close()
            if self._pw is not None:
                self._pw.stop()
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None
        return True

    # ---- 感知 -----------------------------------------------------------
    def screenshot(self) -> bytes:
        return self.page.screenshot()

    # ---- 动作 -----------------------------------------------------------
    def click(self, coordinate: Coordinate) -> None:
        x, y = self._xy(coordinate)
        self.page.mouse.click(x, y)

    def double_click(self, coordinate: Coordinate) -> None:
        x, y = self._xy(coordinate)
        self.page.mouse.dblclick(x, y)

    def right_click(self, coordinate: Coordinate) -> None:
        x, y = self._xy(coordinate)
        self.page.mouse.click(x, y, button="right")

    def input_text(self, text: str, position: Optional[Coordinate] = None) -> None:
        if position is not None:
            x, y = self._xy(position)
            self.page.mouse.click(x, y)
        self.page.keyboard.type(text)

    def clear_text(self, position: Optional[Coordinate] = None) -> None:
        if position is not None:
            x, y = self._xy(position)
            self.page.mouse.click(x, y)
        self.page.keyboard.press("Control+A")
        self.page.keyboard.press("Delete")

    def press_key(self, key: str, position: Optional[Coordinate] = None) -> None:
        if position is not None:
            x, y = self._xy(position)
            self.page.mouse.click(x, y)
        self.page.keyboard.press(key)

    def swipe(
        self,
        start: Coordinate,
        end: Coordinate,
        *,
        duration_ms: int = 300,
    ) -> None:
        sx, sy = self._xy(start)
        ex, ey = self._xy(end)
        self.page.mouse.move(sx, sy)
        self.page.mouse.down()
        self.page.mouse.move(ex, ey, steps=max(1, duration_ms // 10))
        self.page.mouse.up()

    def scroll(
        self,
        *,
        delta_x: int = 0,
        delta_y: int = 0,
        position: Optional[Coordinate] = None,
    ) -> None:
        # L1 原生 scrollBy: 确定性强于 mouse.wheel (滚多少是多少, 无惯性/平滑动画)
        js = (
            "(args) => {"
            f"  const el = ({_JS_FIND_SCROLLABLE})(args.pos);"
            "  el.scrollBy({left: args.dx, top: args.dy, behavior: 'instant'});"
            "}"
        )
        pos = [*self._xy(position)] if position is not None else None
        self.page.evaluate(js, {"pos": pos, "dx": delta_x, "dy": delta_y})

    def scroll_probe(self, position: Optional[Coordinate] = None) -> Optional[ScrollState]:
        js = (
            "(pos) => {"
            f"  const el = ({_JS_FIND_SCROLLABLE})(pos);"
            "  return {"
            "    top: el.scrollTop, left: el.scrollLeft,"
            "    maxTop: Math.max(0, el.scrollHeight - el.clientHeight),"
            "    maxLeft: Math.max(0, el.scrollWidth - el.clientWidth),"
            "  };"
            "}"
        )
        pos = [*self._xy(position)] if position is not None else None
        info = self.page.evaluate(js, pos)
        return ScrollState(
            top=float(info["top"]),
            left=float(info["left"]),
            max_top=float(info["maxTop"]),
            max_left=float(info["maxLeft"]),
        )

    def goto(self, url: str, **kwargs: Any) -> None:
        wait_until = kwargs.pop("wait_until", "domcontentloaded")
        self.page.goto(url, wait_until=wait_until, **kwargs)

    # ---- explore 可选能力覆写 (loop-design.md §5.7 + §6.1) ----
    def navigate_back(self) -> None:
        try:
            self.page.go_back(wait_until="domcontentloaded")
        except Exception:
            # 无历史时 go_back 可能抛错，对探索者忽略并保留 None 兜底
            pass

    def resolve_native_ref(self, coordinate: Coordinate) -> Optional[NativeRef]:
        x, y = self._xy(coordinate)
        result = self.page.evaluate(_JS_RESOLVE_NATIVE_REF, [x, y])
        if isinstance(result, dict) and result.get("kind") and result.get("value") is not None:
            return {"kind": str(result["kind"]), "value": result["value"]}
        return None

    def rect_by_native_ref(self, ref: NativeRef) -> Optional[BBox]:
        if not isinstance(ref, dict):
            return None
        rect = self.page.evaluate(_JS_RECT_BY_REF, {"kind": ref.get("kind"), "value": ref.get("value")})
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            try:
                x1, y1, x2, y2 = (int(v) for v in rect)
                if x2 > x1 and y2 > y1:
                    return (x1, y1, x2, y2)
            except (TypeError, ValueError):
                pass
        return None

    # ---- 内部 -----------------------------------------------------------
    @property
    def page(self):
        if self._page is None:
            raise RuntimeError("PlaywrightDevice 尚未 launch(), 无可用页面")
        return self._page

    @staticmethod
    def _xy(coordinate: Coordinate) -> tuple[float, float]:
        return float(coordinate[0]), float(coordinate[1])


__all__ = ["PlaywrightDevice"]
