import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import fs from 'fs/promises'
import { existsSync, readFileSync } from 'fs'
import os from 'os'
import { spawn } from 'child_process'
import { fileURLToPath } from 'url'
import Inspector from 'unplugin-vue-dev-locator/vite'
import traeBadgePlugin from 'vite-plugin-trae-solo-badge'

const filename = fileURLToPath(import.meta.url)
const playgroundRoot = path.dirname(filename)
const coreRoot = path.resolve(playgroundRoot, '..', 'core')
const workspaceRoot = path.resolve(playgroundRoot, '..', '..')
const configYamlPath = path.join(workspaceRoot, 'config.yaml')
const cacheDir = resolveRuntimeCacheDir()
const currentFrameImagePath = path.join(cacheDir, 'playground.png')

function resolveRuntimeCacheDir(): string {
  const defaultCacheDir = path.join(workspaceRoot, '.cache')
  if (!existsSync(configYamlPath)) {
    return defaultCacheDir
  }

  const content = readFileSync(configYamlPath, 'utf-8')
  const runtimeBlockMatch = content.match(/(^|\r?\n)runtime:\s*\r?\n((?:[ \t]+.*(?:\r?\n|$))*)/)
  const runtimeBlock = runtimeBlockMatch?.[2] || ''
  const cachePathMatch = runtimeBlock.match(/^[ \t]+cache_path:\s*(.+?)\s*$/m)
  const rawCachePath = cachePathMatch?.[1]?.trim().replace(/^['"]|['"]$/g, '')
  if (!rawCachePath) {
    return defaultCacheDir
  }

  if (path.isAbsolute(rawCachePath)) {
    return path.normalize(rawCachePath)
  }
  return path.resolve(path.dirname(configYamlPath), rawCachePath)
}

function visionBridgePlugin() {
  return {
    name: 'vision-core-bridge',
    configureServer(server: { middlewares: { use: (path: string, handler: Function) => void } }) {
      server.middlewares.use('/api/vision/extract', async (req: any, res: any, next: Function) => {
        if (req.method !== 'POST') {
          next()
          return
        }

        try {
          const body = await readJsonBody(req)
          const fileName = String(body?.fileName || 'upload.png')
          const imageBase64 = String(body?.imageBase64 || '')
          if (!imageBase64) {
            throw new Error('缺少 imageBase64')
          }

          const payload = await runVisionExtraction({
            fileName,
            imageBase64,
          })

          res.statusCode = 200
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.end(JSON.stringify(payload))
        } catch (error) {
          res.statusCode = 500
          res.setHeader('Content-Type', 'application/json; charset=utf-8')
          res.end(
            JSON.stringify({
              error: error instanceof Error ? error.message : '调用 core 生成 control.json 失败',
            }),
          )
        }
      })
    },
  }
}

async function readJsonBody(req: NodeJS.ReadableStream): Promise<any> {
  const chunks: Buffer[] = []
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))
  }
  const raw = Buffer.concat(chunks).toString('utf-8').trim()
  if (!raw) {
    return {}
  }
  return JSON.parse(raw)
}

function decodeImagePayload(imageBase64: string): Buffer {
  const normalized = imageBase64.startsWith('data:')
    ? imageBase64.slice(imageBase64.indexOf(',') + 1)
    : imageBase64
  return Buffer.from(normalized, 'base64')
}

function inferFileExtension(fileName: string): string {
  const ext = path.extname(fileName).toLowerCase()
  return ext || '.png'
}

async function runVisionExtraction(options: {
  fileName: string
  imageBase64: string
}) {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'playground-vision-'))
  const imagePath = path.join(tempDir, `input${inferFileExtension(options.fileName)}`)
  const outputPath = path.join(tempDir, 'control.json')
  const imageBuffer = decodeImagePayload(options.imageBase64)

  try {
    await fs.mkdir(cacheDir, { recursive: true })
    await fs.writeFile(currentFrameImagePath, imageBuffer)
    await fs.writeFile(imagePath, imageBuffer)
    await runPythonVisionCommand(imagePath, outputPath)
    const content = await fs.readFile(outputPath, 'utf-8')
    const payload = JSON.parse(content)
    payload.source = payload.source || {}
    payload.source.uri = payload.source.uri || ''
    return payload
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true })
  }
}

async function runPythonVisionCommand(imagePath: string, outputPath: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const child = spawn(
      'python',
      ['tests/generate_control_json.py', '--image', imagePath, '--output', outputPath],
      {
        cwd: coreRoot,
        env: process.env,
        shell: false,
      },
    )

    let stderr = ''
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString()
    })
    child.on('error', (error) => {
      reject(error)
    })
    child.on('close', (code) => {
      if (code === 0) {
        resolve()
        return
      }
      reject(new Error(stderr.trim() || `core 识别脚本执行失败，退出码 ${code}`))
    })
  })
}

// https://vite.dev/config/
export default defineConfig({
  build: {
    sourcemap: 'hidden',
  },
  server: {
    proxy: {
      '/ws': {
        target: 'http://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
      '/locator': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  plugins: [
    vue(),
    visionBridgePlugin(),
    Inspector(),
    traeBadgePlugin({
      variant: 'dark',
      position: 'bottom-right',
      prodOnly: true,
      clickable: true,
      clickUrl: 'https://www.trae.ai/solo?showJoin=1',
      autoTheme: true,
      autoThemeTarget: '#app',
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(playgroundRoot, './src'), // ✅ 定义 @ = src
    },
  },
})
