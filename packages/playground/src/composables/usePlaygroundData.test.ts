import { describe, expect, it } from 'vitest'
import { convertVisionData, parseVisionPayload } from './usePlaygroundData'
import type { VisionControlExportResult } from '@/types/playground'

describe('convertVisionData', () => {
  it('应将 vision 结果转换为可展示的节点和关系', () => {
    const payload: VisionControlExportResult = {
      version: '1.0',
      generated_at: '2026-06-17T00:00:00Z',
      platform: 'web',
      image: {
        raw_width: 1000,
        raw_height: 800,
        context_width: 1000,
        context_height: 800,
        screenshot_shrink_factor: 1,
        raw_to_context_ratio: 1,
        context_to_logical_ratio: 1,
      },
      source: {
        kind: 'path',
        uri: 'demo.png',
        image_hash: 'hash',
      },
      controls: [
        {
          id: 'control-1',
          node_role: 'control',
          text: '登录',
          confidence: 0.95,
          bbox_context: {
            left: 10,
            top: 20,
            right: 210,
            bottom: 80,
            width: 200,
            height: 60,
          },
          bbox_logical: {
            left: 10,
            top: 20,
            right: 210,
            bottom: 80,
            width: 200,
            height: 60,
          },
          center_context: { x: 110, y: 50 },
          center_logical: { x: 110, y: 50 },
          source: { kind: 'vision' },
          type: 'button',
          control_type: 'button',
          attributes: { role: 'button' },
        },
      ],
      labels: [
        {
          id: 'label-1',
          node_role: 'label',
          text: '欢迎回来',
          confidence: 0.88,
          bbox_context: {
            left: 20,
            top: 120,
            right: 220,
            bottom: 160,
            width: 200,
            height: 40,
          },
          bbox_logical: {
            left: 20,
            top: 120,
            right: 220,
            bottom: 160,
            width: 200,
            height: 40,
          },
          center_context: { x: 120, y: 140 },
          center_logical: { x: 120, y: 140 },
          source: { kind: 'vision' },
        },
      ],
      relations: [
        {
          kind: 'describes',
          from_id: 'label-1',
          to_id: 'control-1',
          confidence: 0.7,
        },
      ],
    }

    const result = convertVisionData(payload)

    expect(result.nodes).toHaveLength(2)
    expect(result.relations).toHaveLength(1)
    expect(result.nodes[0]).toMatchObject({
      id: 'control-1',
      nodeRole: 'control',
      name: '登录',
      controlType: 'button',
    })
    expect(result.nodes[1]).toMatchObject({
      id: 'label-1',
      nodeRole: 'label',
      name: '欢迎回来',
    })
    expect(result.relations[0]).toMatchObject({
      kind: 'describes',
      fromId: 'label-1',
      toId: 'control-1',
    })
  })
})

describe('parseVisionPayload', () => {
  it('应识别并适配 google.json 格式', () => {
    const payload = {
      image: { width: 1280, height: 720 },
      elements: [
        {
          type: 'searchbox',
          control_type: 'input',
          text: '搜索',
          bbox: [100, 200, 500, 260],
          relative_bbox: [0.078125, 0.277778, 0.390625, 0.361111],
          action_capablilities: ['click', 'input'],
          attributes: { enabled: true },
        },
      ],
    }

    const parsed = parseVisionPayload(payload)
    expect(parsed).not.toBeNull()
    expect(parsed?.controls).toHaveLength(1)
    expect(parsed?.controls[0]).toMatchObject({
      node_role: 'control',
      text: '搜索',
      type: 'searchbox',
      control_type: 'input',
    })
    expect(parsed?.image).toMatchObject({
      context_width: 1280,
      context_height: 720,
    })
  })

  it('应识别并适配 regions_identify.json 格式', () => {
    const payload = {
      image: { width: 1920, height: 1080 },
      regions: [
        {
          name: 'main-content',
          description: '主内容区',
          bbox: [0, 65, 1920, 1011],
          relative_bbox: [0, 0.06, 1, 0.936],
        },
      ],
    }

    const parsed = parseVisionPayload(payload)
    expect(parsed).not.toBeNull()
    expect(parsed?.controls).toHaveLength(1)
    expect(parsed?.controls[0]).toMatchObject({
      node_role: 'control',
      text: 'main-content',
      type: 'region',
      control_type: 'region',
      attributes: {
        description: '主内容区',
      },
    })
    expect(parsed?.controls[0].bbox_context).toMatchObject({
      left: 0,
      top: 65,
      right: 1920,
      bottom: 1011,
    })
  })
})
