"""
区域感知 · 多尺度视觉定位 (v2) — E2E 验证用例

使用真实 VLM/LLM 调用, 验证 五阶段链路:
① 预处理 → ② 布局分区 → ③ 意图选区 → ④ 聚焦精定位 → ⑤ 后处理。
需要配置有效的 vision + text model API key 才能运行。
"""

from __future__ import annotations

import importlib
import importlib.machinery
import json
import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

# ---- 路径设置 ----
_core_src = Path(__file__).resolve().parents[1] / "src"
_shared_src = Path(__file__).resolve().parents[3] / "shared" / "src"
sys.path.insert(0, str(_core_src))
sys.path.insert(0, str(_shared_src))


def _setup_locate_modules():
    """绕过 agent/__init__.py 直接加载所有 locate 子模块"""
    for parent in ("agent", "agent.locate"):
        if parent not in sys.modules:
            parent_spec = importlib.machinery.ModuleSpec(parent, None, is_package=True)
            parent_mod = importlib.util.module_from_spec(parent_spec)
            sys.modules[parent] = parent_mod

    # 按依赖顺序加载 v2 模块
    module_order = (
        "types",
        "coords",
        "preprocess",
        "layout",
        "region_select",
        "fine",
        "postprocess",
        "pipeline",
    )
    for name in module_order:
        full_name = f"agent.locate.{name}"
        file_path = _core_src / "tisui" / "agent" / "locate" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(full_name, str(file_path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)

    return {name: sys.modules[f"agent.locate.{name}"] for name in module_order}


# ---- 加载 locate 模块 ----
_mods = _setup_locate_modules()

LocateOptions = _mods["types"].LocateOptions
LocateResult = _mods["types"].LocateResult
run_pipeline = _mods["pipeline"].run_pipeline
clear_caches = _mods["pipeline"].clear_caches


# =============================================================================
# 辅助函数
# =============================================================================

def _load_test_image(name: str) -> bytes:
    tests_dir = Path(__file__).resolve().parent
    input_path = tests_dir / "input" / name
    if input_path.exists():
        return input_path.read_bytes()
    root_path = tests_dir / name
    if root_path.exists():
        return root_path.read_bytes()
    raise FileNotFoundError(f"测试图片未找到: {name}")


def _save_result(result: LocateResult, output_name: str) -> None:
    tests_dir = Path(__file__).resolve().parent
    output_dir = tests_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "status": result.status,
        "error": result.error,
        "version": result.version,
        "total_duration_ms": result.total_duration_ms,
        "layout_type": result.layout_type,
        "cache_hit": result.cache_hit,
        "raw_size": list(result.raw_size),
        "base_size": list(result.base_size),
        "primary_index": result.primary_index,
        "elements": [],
        "fallbacks": [],
        "trace": [],
    }
    for elem in result.elements:
        payload["elements"].append({
            "element_id": elem.element_id,
            "type": elem.type,
            "refine_type": elem.refine_type,
            "text": elem.text,
            "description": elem.description,
            "bbox": elem.bbox,
            "bbox_relative": elem.bbox_relative,
            "action_point": elem.action_point,
            "action_point_hint": elem.action_point_hint,
            "confidence": elem.confidence,
            "enabled": elem.enabled,
            "action_capabilities": elem.action_capabilities,
            "locator_way": elem.locator_way,
            "source_region_id": elem.source_region_id,
            "is_fallback": elem.is_fallback,
        })
    for f in result.fallbacks:
        payload["fallbacks"].append({
            "stage": f.stage,
            "reason": f.reason,
            "fallback_to": f.fallback_to,
        })
    for t in result.trace:
        payload["trace"].append({
            "stage": t.stage_name,
            "duration_ms": t.duration_ms,
            "model_calls": t.model_calls,
            "model_name": t.model_name,
            "input_size": list(t.input_size),
            "output_count": t.output_count,
            "decisions": t.decisions,
            "errors": t.errors,
        })

    output_path = output_dir / output_name
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# =============================================================================
# E2E 测试用例
# =============================================================================

@pytest.mark.e2e
class TestE2ERegionPipeline:
    """端到端 v2 五阶段管道测试 (需要 VLM + text LLM API)"""

    @pytest.fixture(autouse=True)
    def _check_config(self):
        from tisui.shared.config import settings
        config = settings.vision_config
        if not (config.api_key and config.base_url and config.model):
            pytest.skip("缺少 vision 模型配置，跳过 E2E 用例")
        clear_caches()

    # ---- 用例 1: 完整五阶段链路 ----

    def test_region_pipeline_google_search(self):
        """在 Google 首页定位搜索框, 验证五阶段轨迹"""
        image_bytes = _load_test_image("google.png")
        action_text = "搜索 pymidscene"

        result = run_pipeline(
            image_bytes,
            action_text,
            options=LocateOptions(debug_mode=True),
        )

        _save_result(result, "pipeline_e2e_google_search.json")

        assert isinstance(result, LocateResult)
        assert result.version == "2.0"

        # 五阶段轨迹验证 (debug_mode=True 时填充)
        stage_names = [t.stage_name for t in result.trace]
        for expected in ("preprocess", "layout", "region_select", "fine", "postprocess"):
            assert expected in stage_names, f"缺少阶段: {expected}"

        # 结果验证
        if result.status == "success":
            assert len(result.elements) > 0
            assert result.primary_index < len(result.elements)
            primary = result.elements[result.primary_index]
            w, h = result.raw_size
            assert primary.bbox[0] >= 0 and primary.bbox[1] >= 0
            assert primary.bbox[2] <= w and primary.bbox[3] <= h
            assert 0.0 <= primary.confidence <= 1.0
            assert len(primary.bbox_relative) == 4
            for v in primary.bbox_relative:
                assert 0.0 <= v <= 1.0
            assert len(primary.action_point) == 2
        else:
            assert result.status in ("fallback", "partial", "failed")
            if result.status == "failed":
                assert result.error is not None

        print(f"\n[E2E v2] status={result.status}, elements={len(result.elements)}, "
              f"layout={result.layout_type}, total_ms={result.total_duration_ms:.0f}")

    # ---- 用例 2: 状态取值合法 ----

    def test_status_is_valid(self):
        """status 必须是四个合法取值之一"""
        image_bytes = _load_test_image("google.png")
        result = run_pipeline(
            image_bytes,
            "点击 Google 搜索按钮",
            options=LocateOptions(debug_mode=True),
        )
        _save_result(result, "pipeline_e2e_google_status.json")

        assert result.status in ("success", "partial", "fallback", "failed")
        # 非 failed 时至少保留了一个候选 (后处理绝不清空)
        if result.status != "failed":
            assert len(result.elements) >= 1

        print(f"\n[E2E v2 Status] status={result.status}, elements={len(result.elements)}")

    # ---- 用例 3: L1 缓存命中 ----

    def test_l1_cache_hit(self):
        """相同 图像+意图 第二次命中 L1 缓存"""
        image_bytes = _load_test_image("google.png")
        action_text = "搜索框"

        clear_caches()
        first = run_pipeline(image_bytes, action_text, options=LocateOptions())
        assert first.cache_hit is None

        second = run_pipeline(image_bytes, action_text, options=LocateOptions())
        assert second.cache_hit == "l1"
        assert second.status == first.status
        assert len(second.elements) == len(first.elements)

        print(f"\n[E2E v2 Cache] first={first.cache_hit}, second={second.cache_hit}")

    # ---- 用例 4: 不同 action_text ----

    @pytest.mark.parametrize("action_text", [
        "搜索 pymidscene",
        "点击 Google 搜索按钮",
        "在输入框中输入关键词",
    ])
    def test_various_action_texts(self, action_text):
        """不同 action_text 的定位结果"""
        image_bytes = _load_test_image("google.png")
        result = run_pipeline(image_bytes, action_text, options=LocateOptions(debug_mode=True))
        _save_result(result, f"pipeline_e2e_google_{action_text[:10].replace(' ', '_')}.json")

        assert isinstance(result, LocateResult)
        if result.elements:
            primary = result.elements[result.primary_index]
            print(f"\n[E2E v2] action='{action_text}' → type={primary.type}, "
                  f"confidence={primary.confidence:.2f}, way={primary.locator_way}")

    # ---- 用例 5: 坐标映射正确性 ----

    def test_coordinate_validity(self):
        """验证最终输出坐标在 raw 范围内且自洽"""
        image_bytes = _load_test_image("google.png")
        with Image.open(BytesIO(image_bytes)) as img:
            w, h = img.size

        result = run_pipeline(image_bytes, "点击搜索按钮", options=LocateOptions())

        # raw_size 应与原图一致 (无 EXIF 旋转时)
        assert result.raw_size == (w, h) or result.raw_size[0] > 0

        rw, rh = result.raw_size
        for elem in result.elements:
            assert 0 <= elem.bbox[0] < elem.bbox[2] <= rw, f"bbox x 越界: {elem.bbox}"
            assert 0 <= elem.bbox[1] < elem.bbox[3] <= rh, f"bbox y 越界: {elem.bbox}"
            # action_point 在 bbox 内
            assert elem.bbox[0] <= elem.action_point[0] <= elem.bbox[2], \
                f"action_point x 不在 bbox 内: {elem.action_point} vs {elem.bbox}"
            assert elem.bbox[1] <= elem.action_point[1] <= elem.bbox[3], \
                f"action_point y 不在 bbox 内: {elem.action_point} vs {elem.bbox}"
            # bbox_relative 与 bbox 一致 (按 raw 归一化)
            assert abs(elem.bbox_relative[0] * rw - elem.bbox[0]) < 2, "bbox_relative left 不一致"
            assert abs(elem.bbox_relative[2] * rw - elem.bbox[2]) < 2, "bbox_relative right 不一致"

        print(f"\n[E2E v2 Coord] 验证了 {len(result.elements)} 个元素的坐标正确性")


__all__ = ["TestE2ERegionPipeline"]
