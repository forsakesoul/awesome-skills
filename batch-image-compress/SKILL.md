---
name: batch-image-compress
description: >-
  批量压缩本地图片并把结果输出到新目录：上传到 PixelForge 在线压缩站点（或同构的
  上传-压缩服务），按档位与格式压缩后逐个下载，保留相对目录结构。用户要求"把这批图
  片压一下""图片太大了缩一缩""用某个在线压缩网站压缩图片""压缩后放到新目录"时使用。
---

# batch-image-compress

把目录（或若干）图片交给 PixelForge 压缩，输出到新目录，源文件不动、相对目录结构保留。

默认走服务端接口（与网页同一套 `/api/upload/*` + `/api/compress`），
`--mode ui` 则用真实 Chrome 驱动网页界面完成同样的操作。

## 何时调用

- 用户给出一个目录 / 一批图片，要求压缩后放到新目录
- 用户指定某个在线图片压缩站点（PixelForge 及其同构部署）批量处理本地图片
- 用户问「为什么压缩完没变小」——多半是 PNG 小图或档位/格式选错，见下文

不要用于：

- 只需要单张图压缩（直接用站点页面点一下更快）
- 需要保持无损（PNG 无损优化请用 `pngquant`/`oxipng` 之类本地工具）
- 需要按业务规则裁剪、加水印、改尺寸（那是另一类图像处理任务）

## 开始前先确认三件事

1. **档位**：不指定时用 `standard`。`aggressive`/`extreme` 会把尺寸缩到 80%/60%
   且 quality 很低，**画面可见损失**，必须让用户明确要求后再用（用户说「极限压缩」
   就是 `extreme`）。
2. **格式**：不指定时 `keep`（保持原格式）。要显著变小就得输出 `webp`（保留透明通道），
   这会把扩展名改成 `.webp`，要提前说明会改变文件名与引用。
3. **输出目录**：默认 `<source>-compressed`（与源目录同级）。不要写回源目录。

## 用法

`<skill-dir>` 是当前 SKILL.md 所在目录，不要假设 runner 的固定安装路径。

```bash
python3 "<skill-dir>/scripts/compress_images.py" <source> \
    [-o OUT] [--level LEVEL] [--format FORMAT] [--mode api|ui] [--dry-run] [--report r.json]
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `source` | 源目录（递归）或单个/多个图片文件 | 必填 |
| `-o, --output` | 输出目录 | `<source>-compressed` |
| `--level` | `light`/`standard`/`high`/`aggressive`/`extreme` | `standard` |
| `--format` | `jpeg`/`png`/`webp`/`avif`/`keep` | `keep` |
| `--mode` | `api` 直接调接口；`ui` 驱动真实网页 | `api` |
| `--ext` | 只处理这些扩展名，可多次指定 | `png/jpg/jpeg/webp` |
| `--report` | 逐文件结果写成 JSON | 不写 |
| `--fallback-api` | `--mode ui` 时网页链路失败则改用接口兜底（默认开） | 开 |
| `--dry-run` | 只列出计划，不发请求 | — |

典型用法：

```bash
# 用户说「极限压缩 + webp」（最常见的诉求）
python3 "<skill-dir>/scripts/compress_images.py" ~/Downloads/0909终 \
    --level extreme --format webp

# 保真优先：只压 JPEG/WebP，保持原格式与尺寸
python3 "<skill-dir>/scripts/compress_images.py" ~/Pictures/batch \
    --level standard --format keep

# 必须走网页界面（用户明确要求"用这个网站上传压缩"）
python3 "<skill-dir>/scripts/compress_images.py" ~/Downloads/pics \
    --level extreme --format webp --mode ui
```

## 执行流程

1. 先 `--dry-run` 看一眼文件清单与目标路径，确认输出目录不在源目录内。
2. 正式跑。脚本逐文件：`unique_copy`（换成新 md5，见下）→ 分片上传 + 合并 →
   `/api/compress` → 下载到目标路径 → 校验字节数与服务端 `compressedSize` 一致。
3. 读汇总：合计缩减比、逐文件尺寸、失败列表。把「压缩后反而变大」的条目如实报给用户。
4. 用户后续想更小/更保真时，改档位或格式重跑即可（输出目录会被同名覆盖）。

失败重试：单文件默认最多尝试 2 次（每次用新的 `unique_copy`，避免命中秒传旧记录）；
`--mode ui` 下若网页链路最终仍失败，会自动改用服务端接口兜底 —— 网页上表现为
「上传失败: Unexpected token 'A'」的文件（实际是 merge 504）正属于这一类。

## 必须知道的三个坑

1. **服务端 5 分钟 TTL**：原始文件与结果都会过期，所以流程必须「传完立刻压、
   压完立刻下」。脚本已经是逐文件串行，不要改成先批量上传再统一压缩。
2. **重复上传同一份字节会写坏服务端记录**：站点按 md5 秒传，重复上传会让分片
   记录出现重复行，`merge` 报 `Chunks incomplete`、压缩报 `File not found /
   Original file expired`。因此脚本上传前用 `scripts/unique_copy.py` 注入一段
   无损元数据（PNG tEXt / JPEG COM / WebP JUNK）换新 md5，**像素不变**。
   手工调试时也要遵守这一点。
3. **4.6MB 以上的文件 merge 可能返回 504 但服务端已完成**：重试 merge 即可命中
   「秒传」分支。脚本内置重试，看到 504 不要直接判定失败。

协议细节、档位参数、交互坑位见 [PixelForge 协议与坑位](references/pixelforge-protocol.md)。

## 结果解读（回答"为什么没变小"）

- JPG + 保持格式：约降到 13%~16%（1.5MB → 215KB），明显。
- 小 PNG 图标（< 20KB）+ 保持 PNG：几乎压不动，`standard`/`high` 还可能变大；
  只有 `aggressive`/`extreme`（带缩放）才明显变小。
- 想要"所有图都显著变小"：输出 `webp` + `extreme`，代价是尺寸 60% 与画质损失。

## --mode ui 注意

- 会驱动用户本机真实 Chrome（chrome-use 中继），首次执行前先向用户说明入口、
  操作与停止条件。
- 每张图约 10~25 秒，需要页面保持在前台可控状态；执行期间不要让用户手动操作
  同一标签页，否则等待条件会被打断。
- 依赖 `chrome-use` CLI（缺失时脚本给出安装命令）。
