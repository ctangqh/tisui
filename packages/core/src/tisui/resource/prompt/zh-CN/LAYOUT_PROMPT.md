你正在分析一张 UI 截图（已缩小的概览图）。
把页面划分为少量高层级区域。不要枚举单个控件。

输出 JSON：
{
  "layout_type": "simple_form / long_list / dashboard / modal_dialog / unknown",
  "regions": [
    {
      "region_type": "header/content/list/form/sidebar/toolbar/modal/nav/footer/unknown",
      "relative_bbox": [x1, y1, x2, y2],
      "z_index": 0,
      "semantic_tags": ["简短", "有区分度", "的标签"],
      "description": "该区域的具体用途，要足够具体以便与其他区域区分",
      "confidence": 0.9
    }
  ]
}

规则：
1. relative_bbox 使用 [0,1] 的相对比率：x1=left/width, y1=top/height, x2=right/width, y2=bottom/height。保留 6 位小数。不要输出绝对像素坐标。
2. 建议 3-8 个区域。保持粗粒度；不要枚举按钮/输入框。
3. 每个区域的 description/semantic_tags 必须各不相同且具体。
4. z_index 表示堆叠层级，且仅为附加标注：它不得改变你对区域的划分方式。请像没有该字段时一样划分区域，再为每个区域填写 z_index。
5. 普通页面内容默认 z_index = 0。仅当某区域是确实覆盖在其他内容之上的浮层时才设为 z_index >= 1（半透明遮罩、置顶弹窗、下拉/菜单浮层、toast/通知、抽屉/侧边面板、tooltip/气泡、加载遮罩）。不要把普通布局区域（header/content/list/form/sidebar 等）标为覆盖层。若没有任何浮层覆盖页面，所有区域的 z_index 保持 0。若多个浮层堆叠，z_index 越大层级越靠上。
