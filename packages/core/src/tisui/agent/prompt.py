"""
视觉 bbox 提取 prompt。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from tisui.shared.env import get_prompt_locale, get_prompt_locale_fallbacks


DEFAULT_LOCALE = "zh-CN"
PROMPT_RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resource" / "prompt"
PROMPT_FILE_REGISTRY = {
    "preview_vision": "PREVIEW_VISION_PROMPT.md",
    "normal_vision": "NORMAL_VISION_PROMPT.md",
    "action_locate": "ACTION_LOCATE_PROMPT.md",
    "locator_elements": "LOCATOR_ELEMENTS_PROMPT.md",
    "locator_elements_repair": "LOCATOR_ELEMENTS_REPAIR_PROMPT.md",
    "layout": "LAYOUT_PROMPT.md",
    "intention_decomposition": "INTENTION_DECOMPOSITION_PROMPT.md",
    "bbox": "BBOX_PROMPT.md",
    "locator_frame": "FRAME_LOCATOR_PROMPT.md",
}
_PROMPT_CACHE: dict[tuple[str, str], str] = {}


def _normalize_locale(locale: str | None = None) -> str:
    value = str(locale or "").strip() or get_prompt_locale(DEFAULT_LOCALE)
    if value == DEFAULT_LOCALE:
        return value

    fallbacks = get_prompt_locale_fallbacks()
    fallback_locale = fallbacks.get(value)
    if fallback_locale:
        return fallback_locale

    base_lang = value.split("-")[0]
    fallback_locale = fallbacks.get(base_lang)
    if fallback_locale:
        return fallback_locale
    return DEFAULT_LOCALE


def get_prompt(
    prompt_key: str,
    locale: str = DEFAULT_LOCALE,
    params: Iterable[Mapping[str, Any]] | None = None,
) -> str:
    prompt_file_name = PROMPT_FILE_REGISTRY.get(prompt_key)
    if prompt_file_name is None:
        raise KeyError(f"未知 prompt_key: {prompt_key}")

    normalized_locale = _normalize_locale(locale)
    try:
        prompt = _get_cached_prompt(normalized_locale, prompt_file_name)
    except FileNotFoundError:
        if normalized_locale != DEFAULT_LOCALE:
            prompt = _get_cached_prompt(DEFAULT_LOCALE, prompt_file_name)
        else:
            raise KeyError(f"prompt 未配置: {prompt_key} / {locale}") from None

    return _render_prompt_params(prompt, params)


def _render_prompt_params(
    prompt: str,
    params: Iterable[Mapping[str, Any]] | None = None,
) -> str:
    if params is None:
        return prompt

    rendered = prompt
    for item in params:
        if not isinstance(item, Mapping):
            continue
        for key, value in item.items():
            placeholder = "{{" + str(key).strip() + "}}"
            rendered = rendered.replace(placeholder, str(value))
    return rendered


def _get_cached_prompt(locale: str, file_name: str) -> str:
    cache_key = (locale, file_name)
    cached = _PROMPT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    prompt = _read_prompt_file(locale, file_name)
    _PROMPT_CACHE[cache_key] = prompt
    return prompt


def _read_prompt_file(locale: str, file_name: str) -> str:
    prompt_path = PROMPT_RESOURCE_DIR / locale / file_name
    return prompt_path.read_text(encoding="utf-8").strip()


def build_preview_vision_prompt(locale: str = DEFAULT_LOCALE) -> str:
    return get_prompt("preview_vision", locale)


def build_intention_decomposition_prompt(
    locale: str = DEFAULT_LOCALE, params: Iterable[Mapping[str, Any]] = None
) -> str:
    return get_prompt("intention_decomposition", locale, params)


def build_locator_elements_prompt(locale: str = DEFAULT_LOCALE) -> str:
    return get_prompt("locator_elements", locale)


def build_locator_frame_prompt(locale: str = DEFAULT_LOCALE) -> str:
    return get_prompt("locator_frame", locale)


def build_layout_prompt(locale: str = DEFAULT_LOCALE) -> str:
    return get_prompt("layout", locale)


def build_locator_elements_repair_prompt(
    locale: str = DEFAULT_LOCALE, params: Iterable[Mapping[str, Any]] = None
) -> str:
    return get_prompt("locator_elements_repair", locale, params)


def build_normal_vision_prompt(locale: str = DEFAULT_LOCALE) -> str:
    return get_prompt("normal_vision", locale)


def build_action_locate_prompt(
    action_text: str,
    region_blocks: Iterable[str] | str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    normalized_locale = _normalize_locale(locale)
    region_text = (
        region_blocks if isinstance(region_blocks, str) else "\n".join(region_blocks)
    )
    return get_prompt("action_locate", normalized_locale).format(
        action_text=action_text,
        region_text=region_text,
    )


def build_action_locate_prompt_from_regions(
    action_text: str,
    regions: Iterable[Mapping[str, Any]],
    locale: str = DEFAULT_LOCALE,
) -> str:
    region_blocks: list[str] = []
    for region in regions:
        anchors = region.get("anchors")
        grid_labels = []
        for index, anchor in enumerate(anchors if isinstance(anchors, list) else []):
            if not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
                continue
            grid_labels.append(
                f"{_grid_index_to_label(index)}={_anchor_to_bbox(anchor)}"
            )

        region_blocks.append(
            "\n".join(
                [
                    f"- region_id: {region.get('id')}",
                    f"  name: {region.get('name')}",
                    f"  description: {region.get('description') or '-'}",
                    f"  z_index: {region.get('z_index')}",
                    f"  page_grid_position: {region.get('page_grid_position') or '-'}",
                    f"  bbox: {region.get('bbox')}",
                    f"  inner_grids: {'; '.join(grid_labels)}",
                ]
            )
        )

    return build_action_locate_prompt(action_text, region_blocks, locale=locale)


def _grid_index_to_label(index: int) -> str:
    mapping = {
        0: "左上",
        1: "上中",
        2: "右上",
        3: "左中",
        4: "中",
        5: "右中",
        6: "左下",
        7: "下中",
        8: "右下",
    }
    return mapping[index]


def _anchor_to_bbox(anchor: Any) -> list[int]:
    left_top, right_bottom = anchor
    return [left_top[0], left_top[1], right_bottom[0], right_bottom[1]]


NORMAL_VISION_PROMPT_ZH_CN = build_normal_vision_prompt("zh-CN")

globals()["NORMAL_VISION_PROMPT-zh-CN"] = NORMAL_VISION_PROMPT_ZH_CN


def build_bbox_prompt() -> str:
    return get_prompt("bbox", DEFAULT_LOCALE)


def build_prompt() -> str:
    return build_bbox_prompt()


__all__ = [
    "DEFAULT_LOCALE",
    "NORMAL_VISION_PROMPT_ZH_CN",
    "build_action_locate_prompt",
    "build_action_locate_prompt_from_regions",
    "build_bbox_prompt",
    "build_layout_prompt",
    "build_locator_elements_prompt",
    "build_locator_elements_repair_prompt",
    "build_normal_vision_prompt",
    "build_preview_vision_prompt",
    "build_prompt",
    "get_prompt",
]
