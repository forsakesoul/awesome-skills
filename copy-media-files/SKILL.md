---
name: copy-media-files
description: Concurrently copy media files (ARW/HIF/JPG/CR3/NEF/MP4 etc.) from a source directory to a target subdirectory under the current working directory, recursing into all subfolders and preserving the relative folder structure. Filters by file extension (default `arw`, multiple allowed). Use when the user wants to import or back up photos/videos from an SD card or camera DCIM tree by extension. Triggers: "import RAW", "back up photos", "copy arw/hif files", "从 SD 卡复制", "导入相机文件", "搬运照片".
---

# copy-media-files

并发地从某个目录递归复制媒体文件（按扩展名过滤）到当前目录下的子目录，**保留相对目录结构**。源文件不会被删除。

## 何时调用

满足以下任一条件时调用：
- 用户想从相机 SD 卡 / DCIM 目录把 RAW / HEIF / JPG 等照片复制到本地
- 用户给出一个源目录，要按扩展名把里面的某类文件批量复制出来
- 需要并发加速、需要保留原目录结构、需要起止时间统计

不要用于：
- 用户明确要"移动"（move/cut）而非复制
- 单文件简单复制（直接 `cp` 就够了）

## 用法

脚本路径：`~/.claude/skills/copy-media-files/scripts/copy_media.py`

```bash
python3 ~/.claude/skills/copy-media-files/scripts/copy_media.py <source> \
    [-o OUTPUT] [-e EXT ...] [-w WORKERS]
```

| 参数 | 说明 | 默认值 |
|---|---|---|
| `source` | 源目录，会被递归扫描；带空格请加引号 | 必填 |
| `-o, --output` | 目标子目录名，位于当前工作目录下；支持嵌套如 `2026/firstHalfYear` | `arw_files` |
| `-e, --ext` | 要复制的扩展名，可多次指定；不区分大小写，前导点可省 | `arw` |
| `-w, --workers` | 并发线程数（I/O 密集，线程比进程合适） | `16` |

## 调用流程

1. **先 `cd` 到希望放结果的目录**，再运行脚本——`-o` 是相对于当前工作目录的
2. 如果用户没说扩展名，先用 `find <source> -type f | sed 's/.*\.//' | sort | uniq -c | sort -rn` 看看卡里实际有什么类型再决定 `-e`
3. 默认 16 线程；如果是慢速 USB / 机械盘，降到 4~8；高速 SSD 可以 32

## 示例

```bash
# 复制 .arw 到 ./arw_files/
python3 ~/.claude/skills/copy-media-files/scripts/copy_media.py /Volumes/Untitled/DCIM

# 复制 .hif 到 ./2026/firstHalfYear/
python3 ~/.claude/skills/copy-media-files/scripts/copy_media.py \
    "/Volumes/Untitled/DCIM" -o 2026/firstHalfYear -e hif

# 同时复制 ARW 和 HEIF（双格式拍摄）
python3 ~/.claude/skills/copy-media-files/scripts/copy_media.py \
    "/Volumes/Untitled/DCIM" -o backup -e arw -e hif -w 32
```

## 输出行为

- 起止时间戳 + 总耗时
- 扫描到的文件数 + 使用的扩展名集合
- 不打印每次复制的明细
- 仅失败项打印到 stderr：`<源路径>: <报错信息>`
- 汇总：成功 N 个，失败 M 个，目标目录路径
- 退出码：全部成功 `0`，参数/源目录错误 `1`，存在文件复制失败 `2`

## 行为细节（重要）

- **保留相对路径**：源 `A/B/C/x.arw` → 目标 `<output>/B/C/x.arw`
- **元数据保留**：用 `shutil.copy2`，保留 mtime / 权限；EXIF 在文件内容里，不受影响
- **重名不覆盖**：目标已存在同名文件时自动追加 `_1`、`_2` 后缀
- **防递归**：如果目标目录在源目录之内会拒绝执行
- **并发安全**：线程间通过锁协调目标文件名预留，不会两个线程算出同一个目标名
