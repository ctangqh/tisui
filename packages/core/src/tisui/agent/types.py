"""
Locator 输入/输出协议（JSON 定义）

输入（JSON）

```json
{
  "image_bytes": "<base64>",
  "action_text": "点击右上角发送按钮"
}
```

输出（JSON）- 我的定义

```json
{
  "input_image": {
    "start_coordinate": [0, 0],
    "width": 900,
    "height": 800,
    "zoom_ratio": 1
  },
  "elements": [
    {
      "action_text": "点击右上角发送按钮",
      "locator_way": "coarse|fine",
      "reasoning": "目标位于右上操作栏，局部裁剪后识别为发送按钮。",
      "type": "button",
      "refine_type": "search_button",
      "attributes": {
        "label": "",
        "text": "搜索",
        "enabled": true,
        "color_value": "#ffffff",
        "color": "黑色",
        "capabilities": ["click", "input"]
      },
      "action_regions": [
        {
          "absolute_bbox": [1184, 34, 1248, 86],
          "relative_bbox": [0.925, 0.031, 0.975, 0.079],
          "action_point": [1216, 60],
          "action": "click",
          "confidence": 0.93,
          "adopt_strategy": "primary"
        },
        {
          "absolute_bbox": [1184, 34, 1248, 86],
          "relative_bbox": [0.925, 0.031, 0.975, 0.079],
          "action_point": [1216, 60],
          "action": "click",
          "confidence": 0.9,
          "adopt_strategy": "candidate"
        }
      ]
    }
  ],
  "raw_model_response": {},
  "normalized_summary": {},
  "errors": []
}
```
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired, TypedDict

BBox = list[int]
RelativeBBox = list[float]
# x, y 坐标
Coordinate = list[int]
RelativeCoordinate = list[float]
# 长，宽
Rect = list[int]

LocatorWay = Literal["coarse", "fine"]
AdoptStrategy = Literal["primary", "candidate"]
ImageFormat = Literal["PNG", "JPG", "WEBP"]


class LocatorAttributes(TypedDict, total=False):
    label: str
    text: str
    enabled: bool
    color: str
    capabilities: list[str]


class LocatorActionRegion(TypedDict):
    absolute_bbox: BBox
    relative_bbox: NotRequired[RelativeBBox]
    action_point: BBox
    action: str
    confidence: float
    adopt_strategy: AdoptStrategy


class LocatorElement(TypedDict):
    action_text: str
    locator_way: LocatorWay
    reasoning: NotRequired[str]
    type: str
    refine_type: str
    attributes: NotRequired[LocatorAttributes]
    action_regions: list[LocatorActionRegion]
    raw_model_response: NotRequired[dict[str, Any]]
    normalized_summary: NotRequired[dict[str, Any]]


class LocatorElementsList(TypedDict):
    elements: list[LocatorElement]


# 选择区域
class Region(TypedDict):
    region_id: str
    region_name: str
    z_index: int
    description: str
    absolute_bbox: BBox
    relative_bbox: RelativeBBox

class RegionsList(TypedDict):
    regions: list[Region]

class ImageInfo(TypedDict):
    height: int
    width: int
    image_format: ImageFormat
    byte_size: int
    image_bytes: bytes
    zoom_ratio: float

class BBoxConversionResult(TypedDict):
    absolute_bbox: BBox
    relative_bbox: RelativeBBox

__all__ = [
    "BBox",
    "RelativeBBox",
    "Coordinate",
    "RelativeCoordinate",
    "LocatorWay",
    "AdoptStrategy",
    "LocatorAttributes",
    "LocatorActionRegion",
    "LocatorElement",
    "LocatorElementsList",
    "Region",
    "RegionsList",
    "ImageInfo",
    "BBoxConversionResult"
]
