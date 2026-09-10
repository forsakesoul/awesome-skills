# PixelForge 协议与坑位

对象：`https://pixel-forge-phi-three.vercel.app`（Vercel + Vercel Blob）。
以下接口与行为是从站点前端产物 `assets/index-*.js` 反推 + 实测确认的；
换部署或站点改版后需要重新核对，不要当成长期稳定契约。

## 接口

| 方法 | 路径 | 入参 | 返回 |
|---|---|---|---|
| GET | `/api/quota` | `?intendedBytes=<n>` | `{driver, usedBytes, limitBytes, available, fileTtlMs, maxFileSize}` |
| GET | `/api/upload/status` | `?hash=<md5>&totalChunks=<n>` | `{uploadedChunks:[int], isComplete:bool}` |
| POST | `/api/upload/chunk` | multipart：`hash`、`index`、`chunk` | `{index}` |
| POST | `/api/upload/merge` | JSON：`hash, filename, totalChunks, fileSize, mimeType` | `{fileId, filename, fileSize, width, height, mimeType, expiresAt}` |
| POST | `/api/compress` | JSON：`fileId, level, format[, quality][, width][, height]` | 见下 |
| GET | `<downloadUrl>` | 公开 blob，带 `?download=1` | 文件字节 |
| GET | `/api/preview/<fileId>?type=original\|compressed` | — | 预览图（网页用） |

响应统一信封：`{code, message, data}`；`code === 0` 才算成功。

`/api/compress` 的 `data`：

```json
{
  "compressedFileId": "<md5>_<level>_<ts>",
  "originalSize": 1591444,
  "compressedSize": 34224,
  "ratio": 0.0215,
  "width": 646, "height": 1080,
  "format": "webp", "level": "extreme",
  "previewUrl": "https://<store>.public.blob.vercel-storage.com/compressed/....webp__exp<ms>",
  "downloadUrl": "https://<store>.public.blob.vercel-storage.com/compressed/....webp__exp<ms>?download=1",
  "expiresAt": 1789008649474
}
```

Blob 是公开可读的，下载不需要 Cookie 或签名；`__exp<ms>` 是过期时间戳。

## 档位与格式

前端硬编码 5 档（`quality` 越小、`resizeRatio` 越小压得越狠）：

| level | 网页名称 | quality | resizeRatio | pngCompressionLevel | webpEffort |
|---|---|---|---|---|---|
| `light` | 轻度压缩 | 90 | 1.0 | 3 | 2 |
| `standard` | 标准压缩 | 75 | 1.0 | 6 | 4 |
| `high` | 较强压缩 | 60 | 1.0 | 7 | 5 |
| `aggressive` | 强力压缩 | 40 | 0.8 | 8 | 6 |
| `extreme` | 极限压缩 | 20 | 0.6 | 9 | 6 |

格式：`jpeg` / `png` / `webp` / `avif`；网页默认 `jpeg`。
可选参数 `quality`、`width`、`height` 只有在网页「高级选项」里手填才会带上。

实测取舍：

- **JPEG/PNG 源图 + 保持原格式**：JPG 大约只降到 13%~16%（1.5MB → 215KB）。
- **PNG 源图 + 保持 PNG**：小图标（< 20KB）几乎压不动，`standard`/`high`
  甚至变大（例如 14613 B → 16655 B）；只有 `aggressive`/`extreme` 因为缩放尺寸才明显变小。
- **输出 webp**：收益最大，且保留透明通道；`extreme` 档 1.5MB JPG → 34KB，
  4.6MB PNG → 34KB（尺寸同时缩到 60%）。
- 尺寸会按 `resizeRatio` 缩放，**这是有损的**：要求保真时用
  `light`/`standard`/`high`，或 `--format webp --level high`。

## 服务端坑位（务必先读）

1. **5 分钟 TTL**：`fileTtlMs = 300000`。原始文件与压缩结果都在 5 分钟后过期，
   下载报 410 / `Original file expired`。批量处理必须「上传完立刻压缩 + 立刻下载」，
   不能先批量传完再统一压。
2. **md5 秒传 + 记录写坏**：`/api/upload/status` 按 md5 判断是否已存在完整分片。
   重复上传同一份字节时：
   - 前端跳过已存在的分片，`merge` 直接复用旧记录；
   - 若旧记录的文件已过期，压缩阶段报 `File not found. Please upload first.`
     或 `Original file expired. Please re-upload.`；
   - 若强行重传全部分片（例如把 `isComplete` 改成 false），`/api/upload/chunk`
     会为同一 index **追加重复行**，`merge` 随即报
     `Chunks incomplete: expected 1, got 3`，该 hash 被永久写坏。
   → 结论：**永远不要重复上传同一份字节**，先经 `unique_copy.py` 换一个 md5。
3. **merge 可能 504 但服务端已完成**：4.6MB 文件的分片合并会触发
   `FUNCTION_INVOCATION_TIMEOUT`，接口返回纯文本 `An error occurred with your
   deployment`（HTTP 504，不是 JSON 信封）。此时服务端通常在后台把合并做完，
   **重试 merge 即可命中「秒传」分支**（`File already exists (instant upload)`）。
   客户端的 `_merge_with_retry` 已实现这一重试。
4. **错误响应不一定是 JSON**：平台级错误（超时、请求体过大）返回纯文本，
   解析 JSON 会抛 `Unexpected token 'A'`。判错时先看 HTTP 状态码。
5. **单文件上限 50MB、总量上限 800MB**，超限时 `/api/upload/chunk` 返回 507。
6. 前端分片固定 2MB、并发 3、每片重试 3 次；本仓库客户端保持一致。

## 与网页交互时的额外注意（`--mode ui`）

- 页面状态是 React state：上一张图的「上传完成 / 开始压缩」文本在新文件开始
  上传后仍会短暂保留，只按文本判断会点到上一张图的压缩结果（表现为压缩响应里的
  `originalSize` 与当前文件不符）。必须等 `文件名: <basename>` 出现。
- `/api/compress` 的响应不会进入 DOM。想拿到 `downloadUrl` 必须在页面里挂
  `window.fetch` 钩子收集（`pf_ui.py` 的 `HOOK_COMPRESS`）。
- 档位按钮 `textContent` 是中文名称 + `Q:` 数字；格式按钮的 `textContent` 是
  **小写**（`png`），可访问名才是大写（`PNG`）。
- 上传命令报 “file input is still empty” 是误报：页面在 `onChange` 里会清空
  `input.value`，以页面文本为准。
