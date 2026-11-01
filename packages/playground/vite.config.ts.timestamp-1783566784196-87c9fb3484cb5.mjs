// vite.config.ts
import { defineConfig } from "file:///D:/code/tisui/packages/playground/node_modules/vite/dist/node/index.js";
import vue from "file:///D:/code/tisui/packages/playground/node_modules/@vitejs/plugin-vue/dist/index.mjs";
import path from "path";
import fs from "fs/promises";
import { existsSync, readFileSync } from "fs";
import os from "os";
import { spawn } from "child_process";
import { fileURLToPath } from "url";
import Inspector from "file:///D:/code/tisui/packages/playground/node_modules/unplugin-vue-dev-locator/dist/vite.mjs";
import traeBadgePlugin from "file:///D:/code/tisui/packages/playground/node_modules/vite-plugin-trae-solo-badge/dist/vite-plugin.esm.js";
var __vite_injected_original_import_meta_url = "file:///D:/code/tisui/packages/playground/vite.config.ts";
var filename = fileURLToPath(__vite_injected_original_import_meta_url);
var playgroundRoot = path.dirname(filename);
var coreRoot = path.resolve(playgroundRoot, "..", "core");
var workspaceRoot = path.resolve(playgroundRoot, "..", "..");
var configYamlPath = path.join(workspaceRoot, "config.yaml");
var cacheDir = resolveRuntimeCacheDir();
var currentFrameImagePath = path.join(cacheDir, "playground.png");
function resolveRuntimeCacheDir() {
  const defaultCacheDir = path.join(workspaceRoot, ".cache");
  if (!existsSync(configYamlPath)) {
    return defaultCacheDir;
  }
  const content = readFileSync(configYamlPath, "utf-8");
  const runtimeBlockMatch = content.match(/(^|\r?\n)runtime:\s*\r?\n((?:[ \t]+.*(?:\r?\n|$))*)/);
  const runtimeBlock = runtimeBlockMatch?.[2] || "";
  const cachePathMatch = runtimeBlock.match(/^[ \t]+cache_path:\s*(.+?)\s*$/m);
  const rawCachePath = cachePathMatch?.[1]?.trim().replace(/^['"]|['"]$/g, "");
  if (!rawCachePath) {
    return defaultCacheDir;
  }
  if (path.isAbsolute(rawCachePath)) {
    return path.normalize(rawCachePath);
  }
  return path.resolve(path.dirname(configYamlPath), rawCachePath);
}
function visionBridgePlugin() {
  return {
    name: "vision-core-bridge",
    configureServer(server) {
      server.middlewares.use("/api/vision/extract", async (req, res, next) => {
        if (req.method !== "POST") {
          next();
          return;
        }
        try {
          const body = await readJsonBody(req);
          const fileName = String(body?.fileName || "upload.png");
          const imageBase64 = String(body?.imageBase64 || "");
          if (!imageBase64) {
            throw new Error("\u7F3A\u5C11 imageBase64");
          }
          const payload = await runVisionExtraction({
            fileName,
            imageBase64
          });
          res.statusCode = 200;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(JSON.stringify(payload));
        } catch (error) {
          res.statusCode = 500;
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(
            JSON.stringify({
              error: error instanceof Error ? error.message : "\u8C03\u7528 core \u751F\u6210 control.json \u5931\u8D25"
            })
          );
        }
      });
    }
  };
}
async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const raw = Buffer.concat(chunks).toString("utf-8").trim();
  if (!raw) {
    return {};
  }
  return JSON.parse(raw);
}
function decodeImagePayload(imageBase64) {
  const normalized = imageBase64.startsWith("data:") ? imageBase64.slice(imageBase64.indexOf(",") + 1) : imageBase64;
  return Buffer.from(normalized, "base64");
}
function inferFileExtension(fileName) {
  const ext = path.extname(fileName).toLowerCase();
  return ext || ".png";
}
async function runVisionExtraction(options) {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "playground-vision-"));
  const imagePath = path.join(tempDir, `input${inferFileExtension(options.fileName)}`);
  const outputPath = path.join(tempDir, "control.json");
  const imageBuffer = decodeImagePayload(options.imageBase64);
  try {
    await fs.mkdir(cacheDir, { recursive: true });
    await fs.writeFile(currentFrameImagePath, imageBuffer);
    await fs.writeFile(imagePath, imageBuffer);
    await runPythonVisionCommand(imagePath, outputPath);
    const content = await fs.readFile(outputPath, "utf-8");
    const payload = JSON.parse(content);
    payload.source = payload.source || {};
    payload.source.uri = payload.source.uri || "";
    return payload;
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
}
async function runPythonVisionCommand(imagePath, outputPath) {
  await new Promise((resolve, reject) => {
    const child = spawn(
      "python",
      ["tests/generate_control_json.py", "--image", imagePath, "--output", outputPath],
      {
        cwd: coreRoot,
        env: process.env,
        shell: false
      }
    );
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      reject(error);
    });
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(stderr.trim() || `core \u8BC6\u522B\u811A\u672C\u6267\u884C\u5931\u8D25\uFF0C\u9000\u51FA\u7801 ${code}`));
    });
  });
}
var vite_config_default = defineConfig({
  build: {
    sourcemap: "hidden"
  },
  server: {
    proxy: {
      "/ws": {
        target: "http://127.0.0.1:8000",
        ws: true,
        changeOrigin: true
      }
    }
  },
  plugins: [
    vue(),
    visionBridgePlugin(),
    Inspector(),
    traeBadgePlugin({
      variant: "dark",
      position: "bottom-right",
      prodOnly: true,
      clickable: true,
      clickUrl: "https://www.trae.ai/solo?showJoin=1",
      autoTheme: true,
      autoThemeTarget: "#app"
    })
  ],
  resolve: {
    alias: {
      "@": path.resolve(playgroundRoot, "./src")
      // ✅ 定义 @ = src
    }
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCJEOlxcXFxjb2RlXFxcXHRpc3VpXFxcXHBhY2thZ2VzXFxcXHBsYXlncm91bmRcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfZmlsZW5hbWUgPSBcIkQ6XFxcXGNvZGVcXFxcdGlzdWlcXFxccGFja2FnZXNcXFxccGxheWdyb3VuZFxcXFx2aXRlLmNvbmZpZy50c1wiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9pbXBvcnRfbWV0YV91cmwgPSBcImZpbGU6Ly8vRDovY29kZS90aXN1aS9wYWNrYWdlcy9wbGF5Z3JvdW5kL3ZpdGUuY29uZmlnLnRzXCI7aW1wb3J0IHsgZGVmaW5lQ29uZmlnIH0gZnJvbSAndml0ZSdcbmltcG9ydCB2dWUgZnJvbSAnQHZpdGVqcy9wbHVnaW4tdnVlJ1xuaW1wb3J0IHBhdGggZnJvbSAncGF0aCdcbmltcG9ydCBmcyBmcm9tICdmcy9wcm9taXNlcydcbmltcG9ydCB7IGV4aXN0c1N5bmMsIHJlYWRGaWxlU3luYyB9IGZyb20gJ2ZzJ1xuaW1wb3J0IG9zIGZyb20gJ29zJ1xuaW1wb3J0IHsgc3Bhd24gfSBmcm9tICdjaGlsZF9wcm9jZXNzJ1xuaW1wb3J0IHsgZmlsZVVSTFRvUGF0aCB9IGZyb20gJ3VybCdcbmltcG9ydCBJbnNwZWN0b3IgZnJvbSAndW5wbHVnaW4tdnVlLWRldi1sb2NhdG9yL3ZpdGUnXG5pbXBvcnQgdHJhZUJhZGdlUGx1Z2luIGZyb20gJ3ZpdGUtcGx1Z2luLXRyYWUtc29sby1iYWRnZSdcblxuY29uc3QgZmlsZW5hbWUgPSBmaWxlVVJMVG9QYXRoKGltcG9ydC5tZXRhLnVybClcbmNvbnN0IHBsYXlncm91bmRSb290ID0gcGF0aC5kaXJuYW1lKGZpbGVuYW1lKVxuY29uc3QgY29yZVJvb3QgPSBwYXRoLnJlc29sdmUocGxheWdyb3VuZFJvb3QsICcuLicsICdjb3JlJylcbmNvbnN0IHdvcmtzcGFjZVJvb3QgPSBwYXRoLnJlc29sdmUocGxheWdyb3VuZFJvb3QsICcuLicsICcuLicpXG5jb25zdCBjb25maWdZYW1sUGF0aCA9IHBhdGguam9pbih3b3Jrc3BhY2VSb290LCAnY29uZmlnLnlhbWwnKVxuY29uc3QgY2FjaGVEaXIgPSByZXNvbHZlUnVudGltZUNhY2hlRGlyKClcbmNvbnN0IGN1cnJlbnRGcmFtZUltYWdlUGF0aCA9IHBhdGguam9pbihjYWNoZURpciwgJ3BsYXlncm91bmQucG5nJylcblxuZnVuY3Rpb24gcmVzb2x2ZVJ1bnRpbWVDYWNoZURpcigpOiBzdHJpbmcge1xuICBjb25zdCBkZWZhdWx0Q2FjaGVEaXIgPSBwYXRoLmpvaW4od29ya3NwYWNlUm9vdCwgJy5jYWNoZScpXG4gIGlmICghZXhpc3RzU3luYyhjb25maWdZYW1sUGF0aCkpIHtcbiAgICByZXR1cm4gZGVmYXVsdENhY2hlRGlyXG4gIH1cblxuICBjb25zdCBjb250ZW50ID0gcmVhZEZpbGVTeW5jKGNvbmZpZ1lhbWxQYXRoLCAndXRmLTgnKVxuICBjb25zdCBydW50aW1lQmxvY2tNYXRjaCA9IGNvbnRlbnQubWF0Y2goLyhefFxccj9cXG4pcnVudGltZTpcXHMqXFxyP1xcbigoPzpbIFxcdF0rLiooPzpcXHI/XFxufCQpKSopLylcbiAgY29uc3QgcnVudGltZUJsb2NrID0gcnVudGltZUJsb2NrTWF0Y2g/LlsyXSB8fCAnJ1xuICBjb25zdCBjYWNoZVBhdGhNYXRjaCA9IHJ1bnRpbWVCbG9jay5tYXRjaCgvXlsgXFx0XStjYWNoZV9wYXRoOlxccyooLis/KVxccyokL20pXG4gIGNvbnN0IHJhd0NhY2hlUGF0aCA9IGNhY2hlUGF0aE1hdGNoPy5bMV0/LnRyaW0oKS5yZXBsYWNlKC9eWydcIl18WydcIl0kL2csICcnKVxuICBpZiAoIXJhd0NhY2hlUGF0aCkge1xuICAgIHJldHVybiBkZWZhdWx0Q2FjaGVEaXJcbiAgfVxuXG4gIGlmIChwYXRoLmlzQWJzb2x1dGUocmF3Q2FjaGVQYXRoKSkge1xuICAgIHJldHVybiBwYXRoLm5vcm1hbGl6ZShyYXdDYWNoZVBhdGgpXG4gIH1cbiAgcmV0dXJuIHBhdGgucmVzb2x2ZShwYXRoLmRpcm5hbWUoY29uZmlnWWFtbFBhdGgpLCByYXdDYWNoZVBhdGgpXG59XG5cbmZ1bmN0aW9uIHZpc2lvbkJyaWRnZVBsdWdpbigpIHtcbiAgcmV0dXJuIHtcbiAgICBuYW1lOiAndmlzaW9uLWNvcmUtYnJpZGdlJyxcbiAgICBjb25maWd1cmVTZXJ2ZXIoc2VydmVyOiB7IG1pZGRsZXdhcmVzOiB7IHVzZTogKHBhdGg6IHN0cmluZywgaGFuZGxlcjogRnVuY3Rpb24pID0+IHZvaWQgfSB9KSB7XG4gICAgICBzZXJ2ZXIubWlkZGxld2FyZXMudXNlKCcvYXBpL3Zpc2lvbi9leHRyYWN0JywgYXN5bmMgKHJlcTogYW55LCByZXM6IGFueSwgbmV4dDogRnVuY3Rpb24pID0+IHtcbiAgICAgICAgaWYgKHJlcS5tZXRob2QgIT09ICdQT1NUJykge1xuICAgICAgICAgIG5leHQoKVxuICAgICAgICAgIHJldHVyblxuICAgICAgICB9XG5cbiAgICAgICAgdHJ5IHtcbiAgICAgICAgICBjb25zdCBib2R5ID0gYXdhaXQgcmVhZEpzb25Cb2R5KHJlcSlcbiAgICAgICAgICBjb25zdCBmaWxlTmFtZSA9IFN0cmluZyhib2R5Py5maWxlTmFtZSB8fCAndXBsb2FkLnBuZycpXG4gICAgICAgICAgY29uc3QgaW1hZ2VCYXNlNjQgPSBTdHJpbmcoYm9keT8uaW1hZ2VCYXNlNjQgfHwgJycpXG4gICAgICAgICAgaWYgKCFpbWFnZUJhc2U2NCkge1xuICAgICAgICAgICAgdGhyb3cgbmV3IEVycm9yKCdcdTdGM0FcdTVDMTEgaW1hZ2VCYXNlNjQnKVxuICAgICAgICAgIH1cblxuICAgICAgICAgIGNvbnN0IHBheWxvYWQgPSBhd2FpdCBydW5WaXNpb25FeHRyYWN0aW9uKHtcbiAgICAgICAgICAgIGZpbGVOYW1lLFxuICAgICAgICAgICAgaW1hZ2VCYXNlNjQsXG4gICAgICAgICAgfSlcblxuICAgICAgICAgIHJlcy5zdGF0dXNDb2RlID0gMjAwXG4gICAgICAgICAgcmVzLnNldEhlYWRlcignQ29udGVudC1UeXBlJywgJ2FwcGxpY2F0aW9uL2pzb247IGNoYXJzZXQ9dXRmLTgnKVxuICAgICAgICAgIHJlcy5lbmQoSlNPTi5zdHJpbmdpZnkocGF5bG9hZCkpXG4gICAgICAgIH0gY2F0Y2ggKGVycm9yKSB7XG4gICAgICAgICAgcmVzLnN0YXR1c0NvZGUgPSA1MDBcbiAgICAgICAgICByZXMuc2V0SGVhZGVyKCdDb250ZW50LVR5cGUnLCAnYXBwbGljYXRpb24vanNvbjsgY2hhcnNldD11dGYtOCcpXG4gICAgICAgICAgcmVzLmVuZChcbiAgICAgICAgICAgIEpTT04uc3RyaW5naWZ5KHtcbiAgICAgICAgICAgICAgZXJyb3I6IGVycm9yIGluc3RhbmNlb2YgRXJyb3IgPyBlcnJvci5tZXNzYWdlIDogJ1x1OEMwM1x1NzUyOCBjb3JlIFx1NzUxRlx1NjIxMCBjb250cm9sLmpzb24gXHU1OTMxXHU4RDI1JyxcbiAgICAgICAgICAgIH0pLFxuICAgICAgICAgIClcbiAgICAgICAgfVxuICAgICAgfSlcbiAgICB9LFxuICB9XG59XG5cbmFzeW5jIGZ1bmN0aW9uIHJlYWRKc29uQm9keShyZXE6IE5vZGVKUy5SZWFkYWJsZVN0cmVhbSk6IFByb21pc2U8YW55PiB7XG4gIGNvbnN0IGNodW5rczogQnVmZmVyW10gPSBbXVxuICBmb3IgYXdhaXQgKGNvbnN0IGNodW5rIG9mIHJlcSkge1xuICAgIGNodW5rcy5wdXNoKEJ1ZmZlci5pc0J1ZmZlcihjaHVuaykgPyBjaHVuayA6IEJ1ZmZlci5mcm9tKGNodW5rKSlcbiAgfVxuICBjb25zdCByYXcgPSBCdWZmZXIuY29uY2F0KGNodW5rcykudG9TdHJpbmcoJ3V0Zi04JykudHJpbSgpXG4gIGlmICghcmF3KSB7XG4gICAgcmV0dXJuIHt9XG4gIH1cbiAgcmV0dXJuIEpTT04ucGFyc2UocmF3KVxufVxuXG5mdW5jdGlvbiBkZWNvZGVJbWFnZVBheWxvYWQoaW1hZ2VCYXNlNjQ6IHN0cmluZyk6IEJ1ZmZlciB7XG4gIGNvbnN0IG5vcm1hbGl6ZWQgPSBpbWFnZUJhc2U2NC5zdGFydHNXaXRoKCdkYXRhOicpXG4gICAgPyBpbWFnZUJhc2U2NC5zbGljZShpbWFnZUJhc2U2NC5pbmRleE9mKCcsJykgKyAxKVxuICAgIDogaW1hZ2VCYXNlNjRcbiAgcmV0dXJuIEJ1ZmZlci5mcm9tKG5vcm1hbGl6ZWQsICdiYXNlNjQnKVxufVxuXG5mdW5jdGlvbiBpbmZlckZpbGVFeHRlbnNpb24oZmlsZU5hbWU6IHN0cmluZyk6IHN0cmluZyB7XG4gIGNvbnN0IGV4dCA9IHBhdGguZXh0bmFtZShmaWxlTmFtZSkudG9Mb3dlckNhc2UoKVxuICByZXR1cm4gZXh0IHx8ICcucG5nJ1xufVxuXG5hc3luYyBmdW5jdGlvbiBydW5WaXNpb25FeHRyYWN0aW9uKG9wdGlvbnM6IHtcbiAgZmlsZU5hbWU6IHN0cmluZ1xuICBpbWFnZUJhc2U2NDogc3RyaW5nXG59KSB7XG4gIGNvbnN0IHRlbXBEaXIgPSBhd2FpdCBmcy5ta2R0ZW1wKHBhdGguam9pbihvcy50bXBkaXIoKSwgJ3BsYXlncm91bmQtdmlzaW9uLScpKVxuICBjb25zdCBpbWFnZVBhdGggPSBwYXRoLmpvaW4odGVtcERpciwgYGlucHV0JHtpbmZlckZpbGVFeHRlbnNpb24ob3B0aW9ucy5maWxlTmFtZSl9YClcbiAgY29uc3Qgb3V0cHV0UGF0aCA9IHBhdGguam9pbih0ZW1wRGlyLCAnY29udHJvbC5qc29uJylcbiAgY29uc3QgaW1hZ2VCdWZmZXIgPSBkZWNvZGVJbWFnZVBheWxvYWQob3B0aW9ucy5pbWFnZUJhc2U2NClcblxuICB0cnkge1xuICAgIGF3YWl0IGZzLm1rZGlyKGNhY2hlRGlyLCB7IHJlY3Vyc2l2ZTogdHJ1ZSB9KVxuICAgIGF3YWl0IGZzLndyaXRlRmlsZShjdXJyZW50RnJhbWVJbWFnZVBhdGgsIGltYWdlQnVmZmVyKVxuICAgIGF3YWl0IGZzLndyaXRlRmlsZShpbWFnZVBhdGgsIGltYWdlQnVmZmVyKVxuICAgIGF3YWl0IHJ1blB5dGhvblZpc2lvbkNvbW1hbmQoaW1hZ2VQYXRoLCBvdXRwdXRQYXRoKVxuICAgIGNvbnN0IGNvbnRlbnQgPSBhd2FpdCBmcy5yZWFkRmlsZShvdXRwdXRQYXRoLCAndXRmLTgnKVxuICAgIGNvbnN0IHBheWxvYWQgPSBKU09OLnBhcnNlKGNvbnRlbnQpXG4gICAgcGF5bG9hZC5zb3VyY2UgPSBwYXlsb2FkLnNvdXJjZSB8fCB7fVxuICAgIHBheWxvYWQuc291cmNlLnVyaSA9IHBheWxvYWQuc291cmNlLnVyaSB8fCAnJ1xuICAgIHJldHVybiBwYXlsb2FkXG4gIH0gZmluYWxseSB7XG4gICAgYXdhaXQgZnMucm0odGVtcERpciwgeyByZWN1cnNpdmU6IHRydWUsIGZvcmNlOiB0cnVlIH0pXG4gIH1cbn1cblxuYXN5bmMgZnVuY3Rpb24gcnVuUHl0aG9uVmlzaW9uQ29tbWFuZChpbWFnZVBhdGg6IHN0cmluZywgb3V0cHV0UGF0aDogc3RyaW5nKTogUHJvbWlzZTx2b2lkPiB7XG4gIGF3YWl0IG5ldyBQcm9taXNlPHZvaWQ+KChyZXNvbHZlLCByZWplY3QpID0+IHtcbiAgICBjb25zdCBjaGlsZCA9IHNwYXduKFxuICAgICAgJ3B5dGhvbicsXG4gICAgICBbJ3Rlc3RzL2dlbmVyYXRlX2NvbnRyb2xfanNvbi5weScsICctLWltYWdlJywgaW1hZ2VQYXRoLCAnLS1vdXRwdXQnLCBvdXRwdXRQYXRoXSxcbiAgICAgIHtcbiAgICAgICAgY3dkOiBjb3JlUm9vdCxcbiAgICAgICAgZW52OiBwcm9jZXNzLmVudixcbiAgICAgICAgc2hlbGw6IGZhbHNlLFxuICAgICAgfSxcbiAgICApXG5cbiAgICBsZXQgc3RkZXJyID0gJydcbiAgICBjaGlsZC5zdGRlcnIub24oJ2RhdGEnLCAoY2h1bmspID0+IHtcbiAgICAgIHN0ZGVyciArPSBjaHVuay50b1N0cmluZygpXG4gICAgfSlcbiAgICBjaGlsZC5vbignZXJyb3InLCAoZXJyb3IpID0+IHtcbiAgICAgIHJlamVjdChlcnJvcilcbiAgICB9KVxuICAgIGNoaWxkLm9uKCdjbG9zZScsIChjb2RlKSA9PiB7XG4gICAgICBpZiAoY29kZSA9PT0gMCkge1xuICAgICAgICByZXNvbHZlKClcbiAgICAgICAgcmV0dXJuXG4gICAgICB9XG4gICAgICByZWplY3QobmV3IEVycm9yKHN0ZGVyci50cmltKCkgfHwgYGNvcmUgXHU4QkM2XHU1MjJCXHU4MTFBXHU2NzJDXHU2MjY3XHU4ODRDXHU1OTMxXHU4RDI1XHVGRjBDXHU5MDAwXHU1MUZBXHU3ODAxICR7Y29kZX1gKSlcbiAgICB9KVxuICB9KVxufVxuXG4vLyBodHRwczovL3ZpdGUuZGV2L2NvbmZpZy9cbmV4cG9ydCBkZWZhdWx0IGRlZmluZUNvbmZpZyh7XG4gIGJ1aWxkOiB7XG4gICAgc291cmNlbWFwOiAnaGlkZGVuJyxcbiAgfSxcbiAgc2VydmVyOiB7XG4gICAgcHJveHk6IHtcbiAgICAgICcvd3MnOiB7XG4gICAgICAgIHRhcmdldDogJ2h0dHA6Ly8xMjcuMC4wLjE6ODAwMCcsXG4gICAgICAgIHdzOiB0cnVlLFxuICAgICAgICBjaGFuZ2VPcmlnaW46IHRydWUsXG4gICAgICB9LFxuICAgIH0sXG4gIH0sXG4gIHBsdWdpbnM6IFtcbiAgICB2dWUoKSxcbiAgICB2aXNpb25CcmlkZ2VQbHVnaW4oKSxcbiAgICBJbnNwZWN0b3IoKSxcbiAgICB0cmFlQmFkZ2VQbHVnaW4oe1xuICAgICAgdmFyaWFudDogJ2RhcmsnLFxuICAgICAgcG9zaXRpb246ICdib3R0b20tcmlnaHQnLFxuICAgICAgcHJvZE9ubHk6IHRydWUsXG4gICAgICBjbGlja2FibGU6IHRydWUsXG4gICAgICBjbGlja1VybDogJ2h0dHBzOi8vd3d3LnRyYWUuYWkvc29sbz9zaG93Sm9pbj0xJyxcbiAgICAgIGF1dG9UaGVtZTogdHJ1ZSxcbiAgICAgIGF1dG9UaGVtZVRhcmdldDogJyNhcHAnLFxuICAgIH0pLFxuICBdLFxuICByZXNvbHZlOiB7XG4gICAgYWxpYXM6IHtcbiAgICAgICdAJzogcGF0aC5yZXNvbHZlKHBsYXlncm91bmRSb290LCAnLi9zcmMnKSwgLy8gXHUyNzA1IFx1NUI5QVx1NEU0OSBAID0gc3JjXG4gICAgfSxcbiAgfSxcbn0pXG4iXSwKICAibWFwcGluZ3MiOiAiO0FBQStSLFNBQVMsb0JBQW9CO0FBQzVULE9BQU8sU0FBUztBQUNoQixPQUFPLFVBQVU7QUFDakIsT0FBTyxRQUFRO0FBQ2YsU0FBUyxZQUFZLG9CQUFvQjtBQUN6QyxPQUFPLFFBQVE7QUFDZixTQUFTLGFBQWE7QUFDdEIsU0FBUyxxQkFBcUI7QUFDOUIsT0FBTyxlQUFlO0FBQ3RCLE9BQU8scUJBQXFCO0FBVHVKLElBQU0sMkNBQTJDO0FBV3BPLElBQU0sV0FBVyxjQUFjLHdDQUFlO0FBQzlDLElBQU0saUJBQWlCLEtBQUssUUFBUSxRQUFRO0FBQzVDLElBQU0sV0FBVyxLQUFLLFFBQVEsZ0JBQWdCLE1BQU0sTUFBTTtBQUMxRCxJQUFNLGdCQUFnQixLQUFLLFFBQVEsZ0JBQWdCLE1BQU0sSUFBSTtBQUM3RCxJQUFNLGlCQUFpQixLQUFLLEtBQUssZUFBZSxhQUFhO0FBQzdELElBQU0sV0FBVyx1QkFBdUI7QUFDeEMsSUFBTSx3QkFBd0IsS0FBSyxLQUFLLFVBQVUsZ0JBQWdCO0FBRWxFLFNBQVMseUJBQWlDO0FBQ3hDLFFBQU0sa0JBQWtCLEtBQUssS0FBSyxlQUFlLFFBQVE7QUFDekQsTUFBSSxDQUFDLFdBQVcsY0FBYyxHQUFHO0FBQy9CLFdBQU87QUFBQSxFQUNUO0FBRUEsUUFBTSxVQUFVLGFBQWEsZ0JBQWdCLE9BQU87QUFDcEQsUUFBTSxvQkFBb0IsUUFBUSxNQUFNLHFEQUFxRDtBQUM3RixRQUFNLGVBQWUsb0JBQW9CLENBQUMsS0FBSztBQUMvQyxRQUFNLGlCQUFpQixhQUFhLE1BQU0saUNBQWlDO0FBQzNFLFFBQU0sZUFBZSxpQkFBaUIsQ0FBQyxHQUFHLEtBQUssRUFBRSxRQUFRLGdCQUFnQixFQUFFO0FBQzNFLE1BQUksQ0FBQyxjQUFjO0FBQ2pCLFdB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
