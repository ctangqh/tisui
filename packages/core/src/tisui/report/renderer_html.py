"""report.html 渲染器 —— 参考 debug/locator 的左右分栏布局。

布局:
    左栏  = 操作步骤结果列表 (可点选)
    右栏上 = 用例时间刻度线 (刻度点与下方缩略图组横向对齐, 标注各步起始时刻)
    右栏下 = 当前所选刻度的大图
交互 (纯前端 vanilla JS, 无框架): 点击步骤卡片或时间线缩略图, 联动高亮并切换大图。
数据以 window.__REPORT__ 内嵌, 与 report.json 同源。
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tisui.report.types import ReportRun, ReportStep


def render_html(run: ReportRun, out_path: Path, *, screenshots_dirname: str = "screenshots") -> Path:
    """把运行模型渲染为左右分栏交互式 report.html, 返回写入路径。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_build_html(run, screenshots_dirname), encoding="utf-8")
    return out_path


# ---- 内部 ---------------------------------------------------------------

def _build_html(run: ReportRun, shots_dir: str) -> str:
    data_json = json.dumps(_build_payload(run, shots_dir), ensure_ascii=False, default=str)
    title = _esc(run.name or run.run_id)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{title} · tisui 测试报告</title>\n"
        "<style>" + _CSS + "</style>\n"
        "</head>\n<body>\n"
        '<header id="topbar"></header>\n'
        '<div class="report">\n'
        '  <aside class="steps">\n'
        '    <div class="steps__head">操作步骤</div>\n'
        '    <div id="stepList" class="steps__list"></div>\n'
        "  </aside>\n"
        '  <section class="stage">\n'
        '    <div id="timeline" class="timeline"></div>\n'
        '    <div class="viewer">\n'
        '      <div class="viewer__imgwrap"><img id="viewerImg" alt="当前步骤截图"/><div id="bboxOverlay" class="bbox-overlay"></div>'
        '<div id="viewerEmpty" class="viewer__empty">无截图</div></div>\n'
        '      <div class="viewer__panel">\n'
        '        <div class="panel__head"><span id="panelMethod" class="panel__method"></span><span id="panelFrame" class="panel__frame"></span></div>\n'
        '        <div id="panelBody" class="panel__scroll"></div>\n'
        '      </div>\n'
        '      <div id="playback" class="playback">\n'
        '        <button class="playback__btn" id="pbPrev" title="上一帧">\u23EE</button>\n'
        '        <button class="playback__btn playback__btn--play" id="pbPlay" title="播放/暂停">\u25B6</button>\n'
        '        <button class="playback__btn" id="pbNext" title="下一帧">\u23ED</button>\n'
        '        <span class="playback__counter" id="pbCounter">-</span>\n'
        '        <select class="playback__speed" id="pbSpeed"><option value="500">0.5s</option><option value="1000" selected>1s</option><option value="2000">2s</option></select>\n'
        '        <input type="range" class="playback__bar" id="pbBar" min="0" value="0" step="1" />\n'
        '      </div>\n'
        "    </div>\n"
        "  </section>\n"
        "</div>\n"
        "<script>window.__REPORT__ = " + data_json + ";</script>\n"
        "<script>" + _JS + "</script>\n"
        "</body>\n</html>\n"
    )


def _build_payload(run: ReportRun, shots_dir: str) -> dict[str, Any]:
    run_start = _parse_iso(run.started_at)
    steps: list[dict[str, Any]] = []
    for step in run.steps:
        data = step.to_dict()
        offset_s = _offset_seconds(run_start, step.started_at)
        # 计算每帧时间偏移 (线性内插)
        sub_count = len(step.sub_screenshot_ids)
        has_main = bool(step.screenshot_id)
        total_frames = sub_count + (1 if has_main else 0)
        duration_s = (step.duration_ms / 1000.0) if step.duration_ms else 0.0
        frame_offsets: list[float] = []
        if total_frames > 0:
            for j in range(total_frames):
                if total_frames == 1:
                    frame_offsets.append(round(offset_s, 2))
                else:
                    frame_offsets.append(round(offset_s + duration_s * j / (total_frames - 1), 2))
        # 时间轴缩略图: 优先主截图, 为空时取最后一张子截图兜底
        thumb_id = step.screenshot_id or (step.sub_screenshot_ids[-1] if step.sub_screenshot_ids else None)
        # 提取 bbox (来自 result_summary)
        bbox = None
        rs = step.result_summary
        if isinstance(rs, dict) and isinstance(rs.get("bbox"), list):
            bbox = [int(x) for x in rs["bbox"]]
        steps.append(
            {
                "index": data["index"],
                "action": data["action"],
                "status": data["status"],
                "target": data["target"],
                "params": data["params"],
                "duration_ms": data["duration_ms"],
                "token_usage": data["token_usage"],
                "offset_s": offset_s,
                "frame_offsets": frame_offsets,
                "result_summary": data["result_summary"],
                "error": data["error"],
                "screenshot": f"{shots_dir}/{thumb_id}.png" if thumb_id else "",
                "sub_screenshots": [
                    f"{shots_dir}/{sid}.png" for sid in step.sub_screenshot_ids
                ],
                "bbox": bbox,
                "sub_bboxes": data.get("sub_bboxes") or [],
                "sub_actions": data.get("sub_actions") or [],
            }
        )
    return {
        "run": {
            "run_id": run.run_id,
            "name": run.name,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "duration_ms": round(run.duration_ms, 1),
            "failure_reason": run.failure_reason,
            "step_count": len(run.steps),
            "failed_count": sum(1 for s in run.steps if s.status == "failed"),
            "token_usage": _sum_token_usage(run.steps),
        },
        "environment": run.environment.to_dict(),
        "steps": steps,
    }


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:  # noqa: BLE001
        return None


def _offset_seconds(run_start: datetime | None, step_started: str) -> float:
    step_start = _parse_iso(step_started)
    if run_start is None or step_start is None:
        return 0.0
    return max(0.0, (step_start - run_start).total_seconds())


def _sum_token_usage(steps: list[ReportStep]) -> dict[str, int]:
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for step in steps:
        usage = step.token_usage or {}
        for key in total:
            total[key] += int(usage.get(key) or 0)
    return total


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


_CSS = """
:root {
  --bg: #0f172a; --panel: #1e293b; --panel-soft: #263449; --border: #334155;
  --text: #e2e8f0; --muted: #94a3b8; --accent: #38bdf8; --highlight: #818cf8;
  --success: #34d399; --danger: #f87171;
}
body.theme-light {
  --bg: #f4f6fa; --panel: #ffffff; --panel-soft: #eef2f7; --border: #d7dee8;
  --text: #1e293b; --muted: #5b6b7f; --accent: #0284c7; --highlight: #6366f1;
  --success: #16a34a; --danger: #dc2626;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
  display: grid; grid-template-rows: auto 1fr; height: 100vh; overflow: hidden;
}
#topbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
  padding: 12px 20px; border-bottom: 1px solid var(--border); background: var(--panel);
}
#topbar h1 { margin: 0; font-size: 16px; }
#topbar .meta { color: var(--muted); font-size: 12px; display: flex; flex-wrap: wrap; gap: 12px; }
#topbar .fail-reason { flex-basis: 100%; color: var(--danger); font-size: 12px; }
.badge { display: inline-block; padding: 1px 9px; border-radius: 10px; font-size: 12px; font-weight: 600; }
.badge.ok { background: color-mix(in srgb, var(--success) 20%, transparent); color: var(--success); }
.badge.fail { background: color-mix(in srgb, var(--danger) 20%, transparent); color: var(--danger); }
.badge.other { background: color-mix(in srgb, var(--muted) 22%, transparent); color: var(--muted); }
.theme-select { margin-left: auto; padding: 5px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel-soft); color: var(--text); font-size: 12px; cursor: pointer; }
.theme-select:focus { outline: none; border-color: var(--accent); }

.report { display: grid; grid-template-columns: 360px minmax(0, 1fr); min-height: 0; overflow: hidden; }

/* 左栏: 步骤列表 */
.steps { display: grid; grid-template-rows: auto 1fr; border-right: 1px solid var(--border); background: var(--panel); min-height: 0; }
.steps__head { padding: 12px 16px; font-size: 13px; font-weight: 600; border-bottom: 1px solid var(--border); }
.steps__list { overflow: auto; padding: 10px; display: grid; gap: 8px; align-content: start; }
.step {
  display: grid; gap: 6px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--panel-soft); cursor: pointer; transition: border-color .16s, background .16s;
}
.step:hover { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
.step--active { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, var(--panel-soft)); }
.step__top { display: flex; align-items: center; gap: 8px; }
.step__idx { width: 22px; height: 22px; flex: none; display: grid; place-items: center; border-radius: 50%;
  background: var(--panel); border: 1px solid var(--border); font-size: 11px; color: var(--muted); }
.step--active .step__idx { border-color: var(--accent); color: var(--accent); }
.step__action { font-family: ui-monospace, Consolas, monospace; font-weight: 600; font-size: 13px; }
.step__time { margin-left: auto; font-size: 11px; color: var(--muted); }
.step__target { font-size: 12px; color: var(--text); word-break: break-word; }
.step__params { font-size: 11px; color: var(--muted); font-family: ui-monospace, Consolas, monospace; word-break: break-word; }
.step__result { font-size: 11px; color: var(--muted); }
.step__result code { color: var(--text); }
.step__result .kv b { color: var(--accent); font-weight: 600; }
.step__result .err { color: var(--danger); }

/* 右栏 */
.stage { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; min-width: 0; }

/* 运行时间刻度线 */
.timeline { display: grid; gap: 8px; padding: 10px 16px 8px; border-bottom: 1px solid var(--border); background: var(--panel); }
.ruler { position: relative; height: 28px; margin: 0; }
.ruler__line { position: absolute; left: 0; right: 0; top: 20px; height: 2px; background: var(--border); }
.ruler__tick { position: absolute; top: 0; transform: translateX(-50%); text-align: center; color: var(--muted); font-size: 10px; white-space: nowrap; }
.ruler__mark { position: absolute; top: 14px; transform: translateX(-50%); width: 12px; height: 12px; padding: 0;
  border-radius: 50%; border: 2px solid var(--border); background: var(--panel); cursor: pointer;
  transition: border-color .2s, background .2s, box-shadow .2s; z-index: 1; }
.ruler__mark:hover { border-color: var(--accent); }
.ruler__mark--active { border-color: var(--accent); background: var(--accent);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 18%, transparent); }
.ruler__mark--fail { border-color: var(--danger); }
.ruler__mark--fail.ruler__mark--active { background: var(--danger); box-shadow: 0 0 0 4px color-mix(in srgb, var(--danger) 18%, transparent); }
.ruler__mark--dense { width: 7px; height: 7px; top: 16px; border-width: 1px; }
.ruler__tick--dense { font-size: 9px; color: color-mix(in srgb, var(--muted) 70%, transparent); }
.tl-strip { display: flex; gap: 2px; overflow-x: auto; overflow-y: hidden; padding: 0 4px; justify-content: safe center; }
.tl-node { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center;
  flex: none; max-width: 100%; padding: 2px 2px; border: none; background: transparent; color: var(--muted); cursor: pointer; transition: none; }
.tl-node:hover, .tl-node--active {}
.tl-node--fail .tl-thumb { border-color: var(--danger); }
.tl-node--active .tl-thumb { border-color: var(--accent); }
.tl-thumbs { display: flex; gap: 3px; overflow-x: auto; scroll-behavior: smooth; scrollbar-width: none; -ms-overflow-style: none; }
.tl-thumbs::-webkit-scrollbar { display: none; }
.tl-carousel { display: flex; align-items: center; gap: 2px; }
.tl-carousel__btn { width: 22px; height: 38px; flex: none; display: grid; place-items: center;
  border: none; background: transparent; color: var(--muted); cursor: pointer; font-size: 10px; border-radius: 4px; transition: color .16s, background .16s; }
.tl-carousel__btn:hover { color: var(--text); background: color-mix(in srgb, var(--accent) 12%, transparent); }
.tl-carousel__btn--hidden { visibility: hidden; }
.tl-thumbs .tl-thumb { width: 62px; height: 38px; }
.tl-thumb--cur { border-color: var(--accent) !important; box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent); }
.tl-thumb { border-radius: 6px; border: 2px solid var(--border); background: var(--bg);
  object-fit: cover; transition: border-color .2s; }
.tl-thumb--empty { display: grid; place-items: center; width: 104px; height: 58px; font-size: 10px; color: var(--muted); }

/* 主题滚动条 */
.steps__list, .tl-strip { scrollbar-width: thin; scrollbar-color: color-mix(in srgb, var(--muted) 50%, transparent) transparent; }
.steps__list::-webkit-scrollbar, .tl-strip::-webkit-scrollbar { width: 10px; height: 10px; }
.steps__list::-webkit-scrollbar-track, .tl-strip::-webkit-scrollbar-track { background: transparent; }
.steps__list::-webkit-scrollbar-thumb, .tl-strip::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--muted) 42%, transparent); border-radius: 6px;
  border: 2px solid transparent; background-clip: padding-box; }
.steps__list::-webkit-scrollbar-thumb:hover, .tl-strip::-webkit-scrollbar-thumb:hover {
  background: color-mix(in srgb, var(--accent) 55%, var(--muted)); background-clip: padding-box; }
.steps__list::-webkit-scrollbar-corner, .tl-strip::-webkit-scrollbar-corner { background: transparent; }

/* 大图查看器: 左图右指令面板 */
.viewer { display: grid; grid-template-columns: minmax(0, 1fr) 340px; grid-template-rows: minmax(0, 1fr) auto; min-height: 0; }
.viewer__imgwrap { position: relative; min-height: 0; min-width: 0; overflow: hidden; }
.viewer__imgwrap img { position: absolute; inset: 12px; margin: auto; max-width: calc(100% - 24px); max-height: calc(100% - 24px); width: auto; height: auto; object-fit: contain; border: 1px solid var(--border); border-radius: 6px; }
.viewer__empty { display: none; color: var(--muted); }

/* 右侧指令面板 (ai_explore / ai_act 的操作指令与点击坐标) */
.viewer__panel { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; min-width: 0; border-left: 1px solid var(--border); background: var(--panel); }
.panel__head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 13px; }
.panel__method { font-family: ui-monospace, Consolas, monospace; font-weight: 700; color: var(--accent); }
.panel__frame { font-size: 11px; color: var(--muted); margin-left: auto; white-space: nowrap; }
.panel__scroll { overflow: auto; padding: 12px 14px; display: grid; gap: 12px; align-content: start; }
.panel__empty { color: var(--muted); font-size: 12px; padding: 10px 0; }
.panel__block { display: grid; gap: 8px; }
.panel__block-head { font-size: 11px; color: var(--muted); font-weight: 600; }
.panel__row { display: grid; gap: 4px; }
.panel__label { font-size: 11px; color: var(--muted); }
.panel__code { font-family: ui-monospace, Consolas, monospace; font-size: 12px; line-height: 1.5; background: var(--panel-soft); border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; word-break: break-all; white-space: pre-wrap; }
.panel__code--err { color: var(--danger); }
.panel__type { color: var(--accent); font-weight: 600; }
.panel__locate { color: var(--text); }
.panel__bbox { color: var(--muted); font-size: 11px; }
#playback { grid-column: 1 / -1; }

/* BBOX 叠加层 */
.bbox-overlay { position: absolute; inset: 0; pointer-events: none; z-index: 2; }
.bbox-rect { position: absolute; border: 2px solid var(--accent); border-radius: 3px;
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  box-shadow: 0 0 0 0 transparent; animation: bbox-pulse 1.6s ease-in-out infinite; }
@keyframes bbox-pulse {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 30%, transparent); }
  50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 12%, transparent); }
}

@media (max-width: 900px) {
  .viewer { grid-template-columns: 1fr; grid-template-rows: minmax(0, 1fr) auto auto; }
  .viewer__panel { border-left: none; border-top: 1px solid var(--border); max-height: 40vh; }
}

@media (max-width: 640px) {
  .report { grid-template-columns: 1fr; overflow: auto; }
  body { overflow: auto; height: auto; }
  .viewer__imgwrap { min-height: 60vh; }
  .viewer__imgwrap img { max-height: 60vh; }
}

/* 播放回放控件 */
.playback { display: none; gap: 8px; align-items: center; padding: 6px 14px; border-top: 1px solid var(--border); background: var(--panel); }
.playback--show { display: flex; }
.playback__btn { width: 32px; height: 28px; display: grid; place-items: center; border: 1px solid var(--border); border-radius: 6px; background: var(--panel-soft); color: var(--text); cursor: pointer; font-size: 14px; transition: border-color .16s, background .16s; }
.playback__btn:hover { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, var(--panel-soft)); }
.playback__btn--play { width: 36px; }
.playback__speed { width: 52px; height: 28px; border: 1px solid var(--border); border-radius: 6px; background: var(--panel-soft); color: var(--text); font-size: 11px; cursor: pointer; text-align: center; }
.playback__speed:focus { outline: none; border-color: var(--accent); }
.playback__counter { font-size: 11px; color: var(--muted); min-width: 56px; text-align: center; font-family: ui-monospace, Consolas, monospace; }
.playback__bar { flex: 1; height: 4px; -webkit-appearance: none; appearance: none; background: var(--border); border-radius: 2px; cursor: pointer; outline: none; }
.playback__bar::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%; background: var(--accent); cursor: pointer; border: 2px solid var(--panel); }
.playback__bar::-moz-range-thumb { width: 14px; height: 14px; border-radius: 50%; background: var(--accent); cursor: pointer; border: 2px solid var(--panel); }
"""

_JS = r"""
(function () {
  var R = window.__REPORT__ || { run: {}, environment: {}, steps: [] };
  var run = R.run || {}, env = R.environment || {}, steps = R.steps || [];
  var active = 0;

  function esc(v) { var d = document.createElement('div'); d.textContent = (v == null ? '' : String(v)); return d.innerHTML; }
  function statusCls(s) { return s === 'success' ? 'ok' : (s === 'failed' ? 'fail' : 'other'); }
  function fmtMs(ms) { ms = Number(ms) || 0; return ms >= 1000 ? (ms / 1000).toFixed(1) + 's' : ms.toFixed(0) + 'ms'; }
  function fmtOffset(s) { return '+' + (Number(s) || 0).toFixed(1) + 's'; }
  function num(n) { return (Number(n) || 0).toLocaleString(); }
  function fmtTokens(u) { u = u || {}; return num(u.total_tokens) + '（入 ' + num(u.prompt_tokens) + ' / 出 ' + num(u.completion_tokens) + '）'; }

  function summaryHtml(step) {
    if (step.error) { return '<span class="err">' + esc(step.error.type) + ': ' + esc(step.error.message) + '</span>'; }
    var r = step.result_summary;
    if (r == null) return '';
    if (typeof r === 'string') return esc(r);
    if (typeof r === 'object') {
      return '<span class="kv">' + Object.keys(r).map(function (k) {
        var v = r[k];
        if (v && typeof v === 'object') v = JSON.stringify(v);
        return '<b>' + esc(k) + '</b>: ' + esc(v);
      }).join(' &nbsp; ') + '</span>';
    }
    return esc(String(r));
  }

  // 顶栏
  var fr = run.failure_reason ? '<div class="fail-reason">失败原因: ' + esc(run.failure_reason) + '</div>' : '';
  document.getElementById('topbar').innerHTML =
    '<h1>' + esc(run.name || 'SDK 测试报告') + '</h1>' +
    '<span class="badge ' + statusCls(run.status) + '">' + esc(run.status) + '</span>' +
    '<div class="meta">' +
      '<span>run_id: ' + esc(run.run_id) + '</span>' +
      '<span>步骤: ' + esc(run.step_count) + '（失败 ' + esc(run.failed_count) + '）</span>' +
      '<span>耗时: ' + fmtMs(run.duration_ms) + '</span>' +
      '<span>Token: ' + fmtTokens(run.token_usage) + '</span>' +
      '<span>' + esc(env.device_type) + ' · ' + esc(env.vision_provider) + '/' + esc(env.vision_model) + '</span>' +
    '</div>' +
    '<select class="theme-select" id="themeSelect"><option value="dark">dark</option><option value="light">light</option></select>' + fr;

  var themeSelect = document.getElementById('themeSelect');
  function setTheme(mode) {
    document.body.classList.toggle('theme-light', mode === 'light');
    if (themeSelect) themeSelect.value = mode;
    try { localStorage.setItem('tisui-report-theme', mode); } catch (e) {}
  }
  if (themeSelect) themeSelect.addEventListener('change', function () { setTheme(this.value); });
  var savedTheme = 'dark';
  try { savedTheme = localStorage.getItem('tisui-report-theme') || 'dark'; } catch (e) {}
  setTheme(savedTheme);

  // 左栏步骤
  var list = document.getElementById('stepList');
  list.innerHTML = steps.map(function (s, i) {
    var params = (s.params && Object.keys(s.params).length) ? '<div class="step__params">' + esc(JSON.stringify(s.params)) + '</div>' : '';
    var target = s.target ? '<div class="step__target">' + esc(s.target) + '</div>' : '';
    return '<div class="step" data-i="' + i + '">' +
      '<div class="step__top">' +
        '<span class="step__idx">' + esc(s.index) + '</span>' +
        '<span class="step__action">' + esc(s.action) + '</span>' +
        '<span class="badge ' + statusCls(s.status) + '">' + esc(s.status) + '</span>' +
        '<span class="step__time">' + fmtOffset(s.offset_s) + ' · ' + fmtMs(s.duration_ms) + '</span>' +
      '</div>' + target + params +
      '<div class="step__result">' + summaryHtml(s) + '</div>' +
    '</div>';
  }).join('') || '<div class="step">无步骤记录</div>';

  // 运行时间刻度线 + 缩略图 (每帧一个刻度点, 标注各自时刻, 与下方缩略图对齐)
  var tl = document.getElementById('timeline');
  // 按帧生成刻度点: 遍历每个步骤的每一帧, 首个/末个用完整标记, 中间帧用小标记
  var rulerMarks = [];
  steps.forEach(function (s, si) {
    var offsets = s.frame_offsets || [];
    var subCount = (s.sub_screenshots || []).length;
    var hasMain = !!s.screenshot;
    var totalFrames = subCount + (hasMain ? 1 : 0);
    if (totalFrames === 0) return;
    var isFail = s.status === 'failed';
    for (var fi = 0; fi < totalFrames; fi++) {
      var t = offsets[fi] != null ? fmtOffset(offsets[fi]) : '';
      var isDense = totalFrames > 2 && fi > 0 && fi < totalFrames - 1;  // 中间帧用小标记
      var denseMC = isDense ? ' ruler__mark--dense' : '';
      var denseTC = isDense ? ' ruler__tick--dense' : '';
      var failC = isFail ? ' ruler__mark--fail' : '';
      rulerMarks.push(
        '<span class="ruler__tick' + denseTC + '" data-si="' + si + '" data-fi="' + fi + '">' + t + '</span>' +
        '<button type="button" class="ruler__mark' + failC + denseMC + '" data-si="' + si + '" data-fi="' + fi +
        '" title="#' + esc(s.index) + ' ' + esc(s.action) + ' 帧' + (fi + 1) + ' (' + t + ')"></button>'
      );
    }
  });
  var rulerMarksHtml = rulerMarks.join('');
  var stripHtml = steps.map(function (s, i) {
    // 收集所有帧
    var allFrames = (s.sub_screenshots || []).slice();
    if (s.screenshot) allFrames.push(s.screenshot);
    var thumbs = '';
    if (allFrames.length === 0) {
      thumbs = '<div class="tl-thumb tl-thumb--empty">无截图</div>';
    } else {
      thumbs = allFrames.map(function (src, fi) {
        return '<img class="tl-thumb" src="' + esc(src) + '" loading="lazy" data-fi="' + fi + '" alt=""/>';
      }).join('');
    }
    var failCls = s.status === 'failed' ? ' tl-node--fail' : '';
    return '<div class="tl-node' + failCls + '" data-i="' + i + '">' +
      '<div class="tl-carousel">' +
        '<button class="tl-carousel__btn tl-carousel__btn--hidden" data-dir="-1" aria-label="上一帧">◀</button>' +
        '<div class="tl-thumbs">' + thumbs + '</div>' +
        '<button class="tl-carousel__btn tl-carousel__btn--hidden" data-dir="1" aria-label="下一帧">▶</button>' +
      '</div>' +
    '</div>';
  }).join('');
  tl.innerHTML = '<div class="ruler"><div class="ruler__line"></div>' + rulerMarksHtml + '</div>' +
    '<div class="tl-strip">' + stripHtml + '</div>';
  var tlNodes = tl.querySelectorAll('.tl-node');
  var rulerEl = tl.querySelector('.ruler');
  var stripEl = tl.querySelector('.tl-strip');

  // 刻度点/时间标签横向位置 = 对应缩略图中心; 遍历所有 .tl-thumb, 与 marks/ticks 按同序一一对应
  function layoutRuler() {
    if (!rulerEl) return;
    var rr = rulerEl.getBoundingClientRect();
    var allThumbs = tl.querySelectorAll('.tl-thumb[data-fi]');
    var allMarks = tl.querySelectorAll('.ruler__mark');
    var allTicks = tl.querySelectorAll('.ruler__tick');
    Array.prototype.forEach.call(allThumbs, function (thumb, idx) {
      var tr = thumb.getBoundingClientRect();
      var x = tr.left + tr.width / 2 - rr.left;
      var visible = x >= -1 && x <= rr.width + 1;
      if (allMarks[idx]) { allMarks[idx].style.left = x.toFixed(1) + 'px'; allMarks[idx].style.visibility = visible ? '' : 'hidden'; }
      if (allTicks[idx]) { allTicks[idx].style.left = x.toFixed(1) + 'px'; allTicks[idx].style.visibility = visible ? '' : 'hidden'; }
    });
  }
  layoutRuler();
  if (stripEl) stripEl.addEventListener('scroll', layoutRuler);
  window.addEventListener('load', layoutRuler);

  var img = document.getElementById('viewerImg');
  var empty = document.getElementById('viewerEmpty');
  var bboxOverlay = document.getElementById('bboxOverlay');
  var pb = document.getElementById('playback');
  var pbCounter = document.getElementById('pbCounter');
  var pbBar = document.getElementById('pbBar');
  var pbSpeed = document.getElementById('pbSpeed');
  var pbPlay = document.getElementById('pbPlay');

  // 播放状态
  var frames = [];          // 当前步骤的所有帧 (sub_screenshots + main screenshot)
  var currentFrame = 0;     // 当前帧索引
  var playing = false;
  var playTimer = null;

  function stopPlayback() {
    playing = false;
    if (playTimer) { clearInterval(playTimer); playTimer = null; }
    pbPlay.textContent = '\u25B6';  // ▶
  }

  function gotoFrame(idx) {
    if (idx < 0 || idx >= frames.length) return;
    currentFrame = idx;
    var src = frames[idx];
    if (src) { img.src = src; img.style.display = ''; empty.style.display = 'none'; }
    else { img.removeAttribute('src'); img.style.display = 'none'; empty.style.display = 'grid'; bboxOverlay.innerHTML = ''; }
    pbCounter.textContent = (idx + 1) + ' / ' + frames.length;
    pbBar.value = idx;
    // 指令面板: 随帧切换联动
    renderActionPanel(idx);
    // BBOX: 图片加载后渲染
    if (src) { renderBBox(); }
    else { bboxOverlay.innerHTML = ''; }
    // 时间轴: 高亮当前帧缩略图 + 自动滚入可见区
    var node = document.querySelector('.tl-node[data-i="' + active + '"]');
    if (node) {
      var container = node.querySelector('.tl-thumbs');
      var allThumbs = node.querySelectorAll('.tl-thumb[data-fi]');
      Array.prototype.forEach.call(allThumbs, function (t) {
        t.classList.toggle('tl-thumb--cur', Number(t.dataset.fi) === idx);
      });
      // 滚动到当前缩略图可见
      var cur = node.querySelector('.tl-thumb--cur');
      if (cur && container) {
        var cLeft = container.scrollLeft, cW = container.clientWidth;
        var tLeft = cur.offsetLeft, tW = cur.offsetWidth;
        if (tLeft < cLeft || tLeft + tW > cLeft + cW) {
          container.scrollTo({ left: tLeft - cW / 2 + tW / 2, behavior: 'smooth' });
        }
      }
      // 更新箭头可见性
      toggleCarouselArrows(node);
    }
  }

  var THUMB_SCROLL_STEP = 65;  // 62px 缩略图 + 3px 间隙
  function scrollCarousel(container, dir) {
    container.scrollBy({ left: dir * THUMB_SCROLL_STEP, behavior: 'smooth' });
  }
  function toggleCarouselArrows(node) {
    var container = node.querySelector('.tl-thumbs');
    var prev = node.querySelector('.tl-carousel__btn[data-dir="-1"]');
    var next = node.querySelector('.tl-carousel__btn[data-dir="1"]');
    if (!container || !prev || !next) return;
    var canScroll = container.scrollWidth > container.clientWidth + 1;
    var atStart = container.scrollLeft <= 1;
    var atEnd = container.scrollLeft + container.clientWidth >= container.scrollWidth - 1;
    prev.classList.toggle('tl-carousel__btn--hidden', !canScroll || atStart);
    next.classList.toggle('tl-carousel__btn--hidden', !canScroll || atEnd);
  }

  // 右侧指令面板: 显示 ai_explore / ai_act 的操作指令、点击坐标与下一步规则
  var panelBody = document.getElementById('panelBody');
  var panelMethod = document.getElementById('panelMethod');
  var panelFrame = document.getElementById('panelFrame');

  function actionItemHtml(item) {
    if (!item || typeof item !== 'object') return '<div class="panel__empty">无动作</div>';
    var a = (item.action && typeof item.action === 'object') ? item.action : {};
    var html = '';
    // 操作指令
    var type = a.type || 'unknown';
    var locate = a.locate || a.query || '';
    var parts = ['<span class="panel__type">' + esc(type) + '</span>'];
    if (locate) parts.push('<span class="panel__locate">' + esc(locate) + '</span>');
    if (a.bbox && a.bbox.length >= 4) parts.push('<span class="panel__bbox">bbox [' + esc(a.bbox.join(', ')) + ']</span>');
    if (a.anomaly) parts.push('<span class="panel__bbox">⚠ ' + esc(a.anomaly) + '</span>');
    html += '<div class="panel__row"><span class="panel__label">操作指令</span><div class="panel__code">' + parts.join(' ') + '</div></div>';
    // 点击坐标
    var click = item.click;
    if (click && click.length >= 2) {
      html += '<div class="panel__row"><span class="panel__label">点击坐标</span><div class="panel__code">(' + esc(click[0]) + ', ' + esc(click[1]) + ')</div></div>';
    }
    // 下一步规则 (决策/规划说明)
    if (item.reason) {
      html += '<div class="panel__row"><span class="panel__label">下一步规则</span><div class="panel__code">' + esc(item.reason) + '</div></div>';
    }
    // 执行错误
    if (item.error) {
      html += '<div class="panel__row"><span class="panel__label">执行错误</span><div class="panel__code panel__code--err">' + esc(item.error) + '</div></div>';
    }
    return html || '<div class="panel__empty">无动作</div>';
  }

  function renderActItems(act) {
    // ai_act: 一轮可含多个动作 (数组); ai_explore: 单动作 (dict)
    if (Array.isArray(act)) {
      return act.map(function (it, i) {
        return '<div class="panel__block"><div class="panel__block-head">动作 ' + (i + 1) + '</div>' + actionItemHtml(it) + '</div>';
      }).join('') || '<div class="panel__empty">无动作</div>';
    }
    return actionItemHtml(act);
  }

  function renderActionPanel(frameIdx) {
    var step = steps[active];
    if (!step) return;
    var isCycle = step.action === 'ai_explore' || step.action === 'ai_act';
    panelMethod.textContent = isCycle ? step.action : (step.action || 'step');
    panelFrame.textContent = '帧 ' + (frameIdx + 1) + ' / ' + frames.length;
    var subActs = step.sub_actions || [];
    // 非空动作轮数 (排除 before 前缀与空占位)
    var actCount = 0;
    for (var k = 0; k < subActs.length; k++) { if (subActs[k]) actCount++; }
    if (!isCycle) {
      // 普通步骤: 显示目标与参数
      var t = step.target ? '<div class="panel__row"><span class="panel__label">目标</span><div class="panel__code">' + esc(step.target) + '</div></div>' : '';
      var p = (step.params && Object.keys(step.params).length) ? '<div class="panel__row"><span class="panel__label">参数</span><div class="panel__code">' + esc(JSON.stringify(step.params, null, 2)) + '</div></div>' : '';
      panelBody.innerHTML = (t + p) || '<div class="panel__empty">该步骤无指令信息</div>';
      return;
    }
    // ai_explore / ai_act: 当前帧对应 sub_actions 项 (与 sub_screenshots 一一对应)
    var act = (frameIdx < subActs.length) ? subActs[frameIdx] : null;
    if (act == null) {
      // 操作后帧: 沿用最后一轮动作信息并标注完成; 其余空帧为操作前状态
      if (frameIdx >= subActs.length && subActs.length && frameIdx === frames.length - 1) {
        panelBody.innerHTML =
          '<div class="panel__row"><span class="panel__label">操作完成</span><div class="panel__code">共 ' +
          actCount + ' 轮动作, 最终状态见截图</div></div>' + renderActItems(subActs[subActs.length - 1]);
        return;
      }
      panelBody.innerHTML = '<div class="panel__empty">操作前状态</div>';
      return;
    }
    panelBody.innerHTML = renderActItems(act);
  }

  // BBOX 叠加层渲染
  function renderBBox() {
    var step = steps[active];
    // 优先 sub_bboxes (ai_act 多帧), 其次 step.bbox (ai_tap 等单帧)
    var bboxes = [];
    if (step.sub_bboxes && step.sub_bboxes.length) {
      if (currentFrame < step.sub_bboxes.length) {
        // 子帧: bbox 与截图一一对应
        bboxes = step.sub_bboxes[currentFrame] || [];
      } else {
        // main 帧 (操作后, 索引越界): 回退到最后一组有效 bbox
        for (var k = step.sub_bboxes.length - 1; k >= 0; k--) {
          if (step.sub_bboxes[k] && step.sub_bboxes[k].length) { bboxes = step.sub_bboxes[k]; break; }
        }
      }
    } else if (step.bbox) {
      bboxes = [step.bbox];
    }
    if (!bboxes.length) { bboxOverlay.innerHTML = ''; return; }
    // 等图片渲染完成再计算坐标
    if (img.complete && img.naturalWidth) { drawBBoxes(bboxes); }
    else { img.addEventListener('load', function onLoad() { img.removeEventListener('load', onLoad); drawBBoxes(bboxes); }, { once: true }); }
  }
  function drawBBoxes(bboxes) {
    var r = img.getBoundingClientRect();
    var wrapR = img.parentElement.getBoundingClientRect();
    var scaleX = r.width / img.naturalWidth;
    var scaleY = r.height / img.naturalHeight;
    var offsetX = r.left - wrapR.left;
    var offsetY = r.top - wrapR.top;
    var html = '';
    for (var i = 0; i < bboxes.length; i++) {
      var b = bboxes[i];
      if (!b || b.length < 4) continue;
      var left = b[0] * scaleX + offsetX, top = b[1] * scaleY + offsetY;
      var width = (b[2] - b[0]) * scaleX, height = (b[3] - b[1]) * scaleY;
      if (width < 1 || height < 1) continue;
      html += '<div class="bbox-rect" style="left:' + left.toFixed(1) + 'px;top:' + top.toFixed(1) + 'px;width:' + width.toFixed(1) + 'px;height:' + height.toFixed(1) + 'px;"></div>';
    }
    bboxOverlay.innerHTML = html;
  }
  function drawBBox(b) {
    drawBBoxes([b]);
  }

  function nextFrame() {
    if (currentFrame < frames.length - 1) { gotoFrame(currentFrame + 1); return true; }
    return false;
  }

  function prevFrame() {
    if (currentFrame > 0) { gotoFrame(currentFrame - 1); return true; }
    return false;
  }

  function togglePlay() {
    if (playing) { stopPlayback(); return; }
    if (frames.length <= 1) return;
    // 如果已在最后一帧, 从头开始
    if (currentFrame >= frames.length - 1) gotoFrame(0);
    playing = true;
    pbPlay.textContent = '\u23F8';  // ⏸
    var interval = Number(pbSpeed.value || 1000);
    playTimer = setInterval(function () {
      if (!nextFrame()) { stopPlayback(); }
    }, interval);
  }

  function setupPlayback(step, startFrame) {
    stopPlayback();
    // 帧顺序: sub_screenshots (操作前/中) → main screenshot (操作后)
    frames = (step.sub_screenshots || []).slice();
    if (step.screenshot) frames.push(step.screenshot);
    // 配置进度条
    pbBar.max = Math.max(0, frames.length - 1);
    pbBar.value = 0;
    // 显示/隐藏播放栏
    pb.classList.toggle('playback--show', frames.length > 1);
    if (startFrame != null && startFrame >= 0 && startFrame < frames.length) gotoFrame(startFrame);
    else if (frames.length > 0) gotoFrame(frames.length - 1);  // 默认显示最后一帧 (操作后)
    else gotoFrame(0);
    // 刷新走马灯箭头
    var node = document.querySelector('.tl-node--active');
    if (node) toggleCarouselArrows(node);
  }

  function select(i, frameIdx) {
    if (i < 0 || i >= steps.length) return;
    active = i;
    var s = steps[i];
    Array.prototype.forEach.call(list.children, function (el, idx) {
      el.classList.toggle('step--active', idx === i);
    });
    Array.prototype.forEach.call(tlNodes, function (el, idx) {
      el.classList.toggle('tl-node--active', idx === i);
    });
    // 刻度点高亮: 当前选中帧的标记 (未指定帧时高亮最后一帧对应标记)
    var totalF = (s.sub_screenshots || []).length + (s.screenshot ? 1 : 0);
    var effectiveFi = (frameIdx != null) ? frameIdx : Math.max(0, totalF - 1);
    var allMarks = tl.querySelectorAll('.ruler__mark');
    Array.prototype.forEach.call(allMarks, function (el) {
      var match = Number(el.dataset.si) === i && Number(el.dataset.fi) === effectiveFi;
      el.classList.toggle('ruler__mark--active', match);
    });
    setupPlayback(s, frameIdx);
    var el = tlNodes[i];
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  list.addEventListener('click', function (e) {
    var node = e.target.closest('.step'); if (node && node.dataset.i != null) select(Number(node.dataset.i));
  });
  // 点击刻度点：选中对应步骤并切到该帧
  tl.addEventListener('click', function (e) {
    // 走马灯箭头
    var btn = e.target.closest('.tl-carousel__btn');
    if (btn && btn.dataset.dir != null) {
      var container = btn.parentElement.querySelector('.tl-thumbs');
      if (container) scrollCarousel(container, Number(btn.dataset.dir));
      return;
    }
    // 刻度点：si=步骤索引，fi=帧索引
    var mark = e.target.closest('.ruler__mark');
    if (mark && mark.dataset.si != null) {
      select(Number(mark.dataset.si), mark.dataset.fi != null ? Number(mark.dataset.fi) : null);
      return;
    }
    var thumb = e.target.closest('.tl-thumb[data-fi]');
    if (thumb && thumb.dataset.fi != null) {
      var node = thumb.closest('.tl-node');
      if (node && node.dataset.i != null) select(Number(node.dataset.i), Number(thumb.dataset.fi));
      return;
    }
    var node = e.target.closest('.tl-node');
    if (node && tl.contains(node) && node.dataset.i != null) select(Number(node.dataset.i));
  });
  // 走马灯滚动后更新箭头状态
  tl.addEventListener('scroll', function (e) {
    var container = e.target.closest('.tl-thumbs');
    if (container) {
      var node = container.closest('.tl-node');
      if (node) toggleCarouselArrows(node);
    }
  }, true);

  // 播放控件
  document.getElementById('pbPrev').addEventListener('click', function () { stopPlayback(); prevFrame(); });
  pbPlay.addEventListener('click', togglePlay);
  document.getElementById('pbNext').addEventListener('click', function () { stopPlayback(); nextFrame(); });
  pbSpeed.addEventListener('change', function () {
    if (playing) { stopPlayback(); togglePlay(); }  // 重启以新速度
  });
  pbBar.addEventListener('input', function () {
    stopPlayback();
    gotoFrame(Number(this.value));
  });
  // 键盘快捷键
  document.addEventListener('keydown', function (e) {
    if (frames.length <= 1) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); stopPlayback(); prevFrame(); }
    if (e.key === 'ArrowRight') { e.preventDefault(); stopPlayback(); nextFrame(); }
    if (e.key === ' ') { e.preventDefault(); togglePlay(); }
  });
  // 窗口缩放时重绘 BBOX + 重算刻度对齐
  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { layoutRuler(); renderBBox(); }, 150);
  });

  if (steps.length) select(0);
})();
"""


__all__ = ["render_html"]
