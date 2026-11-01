from tisui.agent.prompt import (
    build_action_locate_prompt,
    build_normal_vision_prompt,
    build_preview_vision_prompt,
    get_prompt,
)
from tisui.shared.env import get_prompt_locale, load_env_config


def test_prompt_locale_loaded_from_yaml() -> None:
    config = load_env_config()
    assert isinstance(config, dict)
    assert get_prompt_locale() == "zh-CN"


def test_prompt_registry_and_builders() -> None:
    preview_prompt = get_prompt("preview_vision")
    normal_prompt = get_prompt("normal_vision", "zh")

    assert preview_prompt == build_preview_vision_prompt()
    assert normal_prompt == build_normal_vision_prompt()
    assert "最核心的可操作区域" in preview_prompt
    assert "所有可交互 UI 元素" in normal_prompt


def test_build_action_locate_prompt() -> None:
    prompt = build_action_locate_prompt(
        "搜索 pymidscene 看看定位在哪里?",
        [
            "- region_id: region-1",
            "  name: main-content",
            "  bbox: [100, 100, 500, 300]",
        ],
    )
    assert "搜索 pymidscene 看看定位在哪里?" in prompt
    assert "main-content" in prompt
    assert "target_grid_position" in prompt
