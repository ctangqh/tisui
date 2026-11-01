You are analyzing a UI screenshot (downscaled overview).
Divide the page into a SMALL number of high-level regions. DO NOT list individual controls.

Output JSON:
{
  "layout_type": "simple_form / long_list / dashboard / modal_dialog / unknown",
  "regions": [
    {
      "region_type": "header/content/list/form/sidebar/toolbar/modal/nav/footer/unknown",
      "relative_bbox": [x1, y1, x2, y2],
      "z_index": 0,
      "semantic_tags": ["short", "discriminative", "tags"],
      "description": "concrete purpose of this region, be specific so it can be told apart from others",
      "confidence": 0.9
    }
  ]
}

Rules:
1. relative_bbox uses RELATIVE ratios in [0,1]: x1=left/width, y1=top/height, x2=right/width, y2=bottom/height. Keep 6 decimals. DO NOT output absolute pixel coordinates.
2. Prefer 3-8 regions. Keep it coarse; do NOT enumerate buttons/inputs.
3. Make each region's description/semantic_tags DISTINCT and specific.
4. z_index marks the stacking layer and is ONLY an extra annotation: it MUST NOT change how you divide regions. Divide regions exactly as you would without this field, then fill z_index for each.
5. Default z_index = 0 for normal page content. Set z_index >= 1 ONLY when a region is a GENUINE floating layer that visually covers other content (semi-transparent mask, dialog/popup on top, dropdown/menu overlay, toast/notification, drawer/side panel, tooltip/popover, loading mask). Do NOT mark ordinary layout regions (header/content/list/form/sidebar/etc.) as overlays. If nothing floats above the page, every region keeps z_index = 0. If several overlays stack, larger z_index sits higher.
