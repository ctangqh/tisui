"""
区域感知 · 多尺度视觉定位 (v2) — 单元测试

验证坐标映射、区域裁剪、NMS/状态判定、预处理等核心逻辑。
不依赖 VLM/LLM 调用 (纯数学 + 图像几何验证)。
"""

import importlib
import importlib.machinery
import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

# 添加项目路径
_core_src = Path(__file__).resolve().parents[1] / "src"
_shared_src = Path(__file__).resolve().parents[3] / "shared" / "src"
sys.path.insert(0, str(_core_src))
sys.path.insert(0, str(_shared_src))


def _import_module(module_name: str):
    """从文件路径直接导入 locate 子模块，绕过父包 __init__.py"""
    file_path = _core_src / "tisui" / "agent" / "locate" / f"{module_name}.py"
    full_name = f"agent.locate.{module_name}"
    for parent in ("agent", "agent.locate"):
        if parent not in sys.modules:
            parent_spec = importlib.machinery.ModuleSpec(parent, None, is_package=True)
            parent_mod = importlib.util.module_from_spec(parent_spec)
            sys.modules[parent] = parent_mod

    spec = importlib.util.spec_from_file_location(full_name, str(file_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


# 依赖顺序: types → coords → preprocess/postprocess (纯函数, 无 VLM)
types_mod = _import_module("types")
coords_mod = _import_module("coords")
preprocess_mod = _import_module("preprocess")
postprocess_mod = _import_module("postprocess")

LocateOptions = types_mod.LocateOptions
LocateResult = types_mod.LocateResult
LocatedElement = types_mod.LocatedElement
LayoutRegion = types_mod.LayoutRegion

normalize_bbox = coords_mod.normalize_bbox
to_relative = coords_mod.to_relative
normalize_relative_bbox = coords_mod.normalize_relative_bbox
relative_to_abs = coords_mod.relative_to_abs
map_region_base_to_raw = coords_mod.map_region_base_to_raw
map_overview_bbox_to_base = coords_mod.map_overview_bbox_to_base
expand_bbox_by_image = coords_mod.expand_bbox_by_image
crop_patch_from_raw = coords_mod.crop_patch_from_raw
map_patch_bbox_to_raw = coords_mod.map_patch_bbox_to_raw
compute_action_point = coords_mod.compute_action_point
compute_iou = coords_mod.compute_iou

perform_preprocessing = preprocess_mod.perform_preprocessing
postprocess_elements = postprocess_mod.postprocess_elements
decide_status = postprocess_mod.decide_status


# =============================================================================
# 1. normalize_bbox
# =============================================================================

class TestNormalizeBbox:
    def test_valid(self):
        assert normalize_bbox([10, 20, 30, 40]) == [10, 20, 30, 40]

    def test_float_rounded(self):
        assert normalize_bbox([10.4, 20.6, 30.5, 40.1]) == [10, 21, 30, 40]

    def test_reversed_swapped(self):
        assert normalize_bbox([30, 40, 10, 20]) == [10, 20, 30, 40]

    def test_degenerate_none(self):
        assert normalize_bbox([10, 20, 10, 40]) is None
        assert normalize_bbox([10, 20, 30, 20]) is None

    def test_wrong_length_none(self):
        assert normalize_bbox([1, 2, 3]) is None
        assert normalize_bbox("bad") is None


# =============================================================================
# 2. to_relative — 按 raw 归一化
# =============================================================================

class TestToRelative:
    def test_basic(self):
        rel = to_relative([100, 50, 200, 150], (1000, 500))
        assert rel == [0.1, 0.1, 0.2, 0.3]

    def test_range(self):
        rel = to_relative([0, 0, 1920, 1080], (1920, 1080))
        for v in rel:
            assert 0.0 <= v <= 1.0


# =============================================================================
# 2b. 相对坐标 ↔ 绝对像素
# =============================================================================

class TestRelativeBbox:
    def test_normalize_ok(self):
        assert normalize_relative_bbox([0.1, 0.2, 0.3, 0.4]) == [0.1, 0.2, 0.3, 0.4]

    def test_normalize_reorders(self):
        assert normalize_relative_bbox([0.3, 0.4, 0.1, 0.2]) == [0.1, 0.2, 0.3, 0.4]

    def test_normalize_clamps_range(self):
        assert normalize_relative_bbox([-0.1, 0.0, 1.2, 1.0]) == [0.0, 0.0, 1.0, 1.0]

    def test_normalize_rejects_degenerate(self):
        assert normalize_relative_bbox([0.5, 0.2, 0.5, 0.4]) is None
        assert normalize_relative_bbox([0.1, 0.2, 0.3]) is None
        assert normalize_relative_bbox("bad") is None

    def test_relative_to_abs(self):
        # 0-1 相对 → 按 1000x500 图绝对像素
        assert relative_to_abs([0.1, 0.2, 0.3, 0.4], (1000, 500)) == [100, 100, 300, 200]


# =============================================================================
# 3. 坐标空间映射
# =============================================================================

class TestCoordinateMapping:
    def test_region_base_to_raw(self):
        # base 800x600 → raw 1600x1200 (2x)
        out = map_region_base_to_raw([100, 100, 200, 200], (800, 600), (1600, 1200))
        assert out == [200, 200, 400, 400]

    def test_overview_to_base(self):
        # overview 400x300 → base 800x600 (2x)
        out = map_overview_bbox_to_base([50, 60, 100, 120], (400, 300), (800, 600))
        assert out == [100, 120, 200, 240]

    def test_patch_to_raw_translation(self):
        out = map_patch_bbox_to_raw([10, 20, 50, 60], (100, 100))
        assert out == [110, 120, 150, 160]


# =============================================================================
# 4. expand_bbox_by_image — 按图像尺寸外扩并 clamp
# =============================================================================

class TestExpandBbox:
    def test_expand_and_clamp(self):
        # 图 1000x1000, ratio 0.1 → 外扩 100px, clamp 到 [0,1000]
        out = expand_bbox_by_image([50, 50, 200, 200], (1000, 1000), 0.1)
        assert out == [0, 0, 300, 300]

    def test_clamp_right_bottom(self):
        out = expand_bbox_by_image([900, 900, 990, 990], (1000, 1000), 0.1)
        assert out[2] == 1000
        assert out[3] == 1000

    def test_no_expand_when_zero_ratio(self):
        out = expand_bbox_by_image([100, 100, 200, 200], (1000, 1000), 0.0)
        assert out == [100, 100, 200, 200]


# =============================================================================
# 5. crop_patch_from_raw + 坐标回环
# =============================================================================

class TestCropPatch:
    def test_crop_no_expand_base_equals_raw(self):
        raw = Image.new("RGB", (800, 600), color=(200, 200, 200))
        patch = crop_patch_from_raw(
            raw, [100, 100, 300, 200],
            base_size=(800, 600), raw_size=(800, 600),
            expand_ratio=0.0, source_region_id="region_0",
        )
        assert patch.bbox_in_raw == [100, 100, 300, 200]
        assert patch.patch_image.size == (200, 100)
        assert patch.source_region_id == "region_0"

    def test_crop_scales_base_to_raw(self):
        # base 400x300, raw 800x600 (2x): region base [50,50,150,100] → raw [100,100,300,200]
        raw = Image.new("RGB", (800, 600), color=(200, 200, 200))
        patch = crop_patch_from_raw(
            raw, [50, 50, 150, 100],
            base_size=(400, 300), raw_size=(800, 600),
            expand_ratio=0.0,
        )
        assert patch.bbox_in_raw == [100, 100, 300, 200]

    def test_patch_bbox_roundtrip_to_raw(self):
        """patch 内定位 bbox +origin 回 raw, 应映射自洽"""
        raw = Image.new("RGB", (800, 600), color=(200, 200, 200))
        patch = crop_patch_from_raw(
            raw, [100, 100, 300, 200],
            base_size=(800, 600), raw_size=(800, 600),
            expand_ratio=0.0,
        )
        origin = (patch.bbox_in_raw[0], patch.bbox_in_raw[1])
        raw_bbox = map_patch_bbox_to_raw([10, 20, 50, 60], origin)
        assert raw_bbox == [110, 120, 150, 160]


# =============================================================================
# 6. compute_action_point
# =============================================================================

class TestComputeActionPoint:
    def test_center(self):
        assert compute_action_point([0, 0, 100, 60], "center") == [50, 30]

    def test_left_side(self):
        assert compute_action_point([0, 0, 100, 60], "left_side") == [25, 30]

    def test_right_side(self):
        assert compute_action_point([0, 0, 100, 60], "right_side") == [75, 30]

    def test_unknown_hint_defaults_center(self):
        assert compute_action_point([0, 0, 100, 60], "???") == [50, 30]


# =============================================================================
# 7. compute_iou
# =============================================================================

class TestComputeIou:
    def test_identical(self):
        assert compute_iou([0, 0, 100, 100], [0, 0, 100, 100]) == 1.0

    def test_disjoint(self):
        assert compute_iou([0, 0, 50, 50], [60, 60, 100, 100]) == 0.0

    def test_half_overlap(self):
        iou = compute_iou([0, 0, 100, 100], [50, 0, 150, 100])
        assert abs(iou - 1 / 3) < 0.01

    def test_zero_size(self):
        assert compute_iou([0, 0, 0, 0], [0, 0, 100, 100]) == 0.0


# =============================================================================
# 8. postprocess_elements — NMS / 过滤 / 状态
# =============================================================================

def _elem(bbox, conf, **kw):
    return LocatedElement(bbox=bbox, confidence=conf, **kw)


class TestPostprocess:
    def test_empty_failed(self):
        elements, status, primary = postprocess_elements([], LocateOptions(), fallback_used=False)
        assert elements == []
        assert status == "failed"
        assert primary == 0

    def test_nms_keeps_higher_confidence(self):
        a = _elem([0, 0, 100, 100], 0.9)
        b = _elem([10, 10, 90, 90], 0.5)
        opts = LocateOptions(nms_iou_threshold=0.5, confidence_threshold=0.3)
        elements, status, _ = postprocess_elements([a, b], opts, fallback_used=False)
        assert len(elements) == 1
        assert elements[0].confidence == 0.9
        assert status == "success"

    def test_nms_keeps_disjoint(self):
        a = _elem([0, 0, 50, 50], 0.6)
        b = _elem([60, 60, 100, 100], 0.55)
        opts = LocateOptions(nms_iou_threshold=0.5, confidence_threshold=0.3)
        elements, _, _ = postprocess_elements([a, b], opts, fallback_used=False)
        assert len(elements) == 2

    def test_low_confidence_not_emptied_partial(self):
        """全部低于阈值时保留最高分, 状态 partial (绝不清空)"""
        a = _elem([0, 0, 100, 100], 0.1)
        b = _elem([200, 200, 300, 300], 0.05)
        opts = LocateOptions(confidence_threshold=0.3, nms_iou_threshold=0.7)
        elements, status, _ = postprocess_elements([a, b], opts, fallback_used=False)
        assert len(elements) == 1
        assert elements[0].confidence == 0.1
        assert status == "partial"

    def test_fallback_used_status(self):
        a = _elem([0, 0, 100, 100], 0.9)
        elements, status, _ = postprocess_elements([a], LocateOptions(), fallback_used=True)
        assert status == "fallback"

    def test_element_id_assigned(self):
        a = _elem([0, 0, 50, 50], 0.8)
        b = _elem([60, 60, 100, 100], 0.7)
        elements, _, _ = postprocess_elements([a, b], LocateOptions(), fallback_used=False)
        assert elements[0].element_id == "elem_0"
        assert elements[1].element_id == "elem_1"

    def test_max_candidates_truncation(self):
        elems = [_elem([i * 100, 0, i * 100 + 50, 50], 0.9 - i * 0.05) for i in range(8)]
        opts = LocateOptions(max_candidates=3, confidence_threshold=0.1, nms_iou_threshold=0.7)
        elements, _, _ = postprocess_elements(elems, opts, fallback_used=False)
        assert len(elements) == 3


# =============================================================================
# 9. decide_status — 顺序敏感, partial 可达
# =============================================================================

class TestDecideStatus:
    def test_failed_when_empty(self):
        assert decide_status([], threshold=0.3, fallback_used=False, low_confidence=False) == "failed"

    def test_fallback_priority(self):
        e = [_elem([0, 0, 10, 10], 0.9)]
        assert decide_status(e, threshold=0.3, fallback_used=True, low_confidence=False) == "fallback"

    def test_partial_low_confidence(self):
        e = [_elem([0, 0, 10, 10], 0.9)]
        assert decide_status(e, threshold=0.3, fallback_used=False, low_confidence=True) == "partial"

    def test_partial_below_threshold(self):
        e = [_elem([0, 0, 10, 10], 0.2)]
        assert decide_status(e, threshold=0.3, fallback_used=False, low_confidence=False) == "partial"

    def test_success(self):
        e = [_elem([0, 0, 10, 10], 0.8)]
        assert decide_status(e, threshold=0.3, fallback_used=False, low_confidence=False) == "success"


# =============================================================================
# 10. perform_preprocessing — 无 VLM, 纯图像处理
# =============================================================================

def _png_bytes(size, color=(123, 222, 111)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


class TestPreprocessing:
    def test_sizes(self):
        data = _png_bytes((1000, 700))
        pre = perform_preprocessing(data, LocateOptions(max_image_size=(2048, 2048)))
        assert pre.raw_size == (1000, 700)
        assert pre.base_size == (1000, 700)          # 未超过 max_image_size, 不缩放
        assert max(pre.overview_size) <= 500         # 概览图长边受限

    def test_base_downscaled(self):
        data = _png_bytes((4096, 2048))
        pre = perform_preprocessing(data, LocateOptions(max_image_size=(2048, 2048)))
        assert pre.base_size[0] <= 2048 and pre.base_size[1] <= 2048
        assert pre.raw_size == (4096, 2048)          # raw 保持原始

    def test_hash_deterministic(self):
        data = _png_bytes((800, 600))
        h1 = perform_preprocessing(data, LocateOptions()).image_hash
        h2 = perform_preprocessing(data, LocateOptions()).image_hash
        assert h1 == h2
        assert len(h1) == 64                          # sha256 hex

    def test_hash_differs_by_content(self):
        a = perform_preprocessing(_png_bytes((800, 600), (10, 20, 30)), LocateOptions()).image_hash
        b = perform_preprocessing(_png_bytes((800, 600), (200, 100, 50)), LocateOptions()).image_hash
        assert a != b

    def test_rgb_mode(self):
        pre = perform_preprocessing(_png_bytes((300, 200)), LocateOptions())
        assert pre.raw_image.mode == "RGB"


# =============================================================================
# 11. 数据结构默认值
# =============================================================================

class TestDataStructures:
    def test_locate_options_defaults(self):
        opts = LocateOptions()
        assert opts.max_regions_to_fine == 2
        assert opts.confidence_threshold == 0.3
        assert opts.enable_cache is True
        assert opts.debug_mode is None

    def test_located_element_defaults(self):
        e = LocatedElement()
        assert e.locator_way == "fine"
        assert e.is_fallback is False
        assert e.confidence == 0.0
        assert e.action_point_hint == "center"

    def test_layout_region_defaults(self):
        r = LayoutRegion(region_id="region_0", region_type="content")
        assert r.bbox == [0, 0, 0, 0]
        assert r.semantic_tags == []
        assert r.confidence == 0.5

    def test_locate_result_defaults(self):
        r = LocateResult(status="success")
        assert r.status == "success"
        assert r.elements == []
        assert r.primary_index == 0
        assert r.version == "2.0"
        assert r.cache_hit is None
