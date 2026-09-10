#!/usr/bin/env python3
"""
compress_images.py —— 批量把本地图片交给 PixelForge 压缩，输出到新目录。

== 使用场景 ==
用户给一个目录（或若干图片），要求「用某个在线图片压缩站点压一下、放到新目录」。
默认走服务端接口（与网页同一套 /api/upload + /api/compress），
--mode ui 则用真实 Chrome 驱动网页界面完成同样的操作。

== 用法 ==
    python3 compress_images.py <source> [-o OUT] [--level LEVEL] [--format FORMAT]
                              [--mode api|ui] [--ext png --ext jpg] [--dry-run]
                              [--report report.json] [--base-url URL] [--session NAME]

常用参数：
    source            源目录（递归）或单个/多个图片文件
    -o, --output      输出目录，默认 <source>-compressed（相对路径基于 cwd）
    --level           light|standard|high|aggressive|extreme，默认 standard
    --format          jpeg|png|webp|avif|keep，默认 keep（保持原格式）
    --mode            api（默认，稳定快）| ui（驱动真实网页）
    --ext             只处理这些扩展名，可多次指定，默认 png/jpg/jpeg/webp
    --report          额外把逐文件结果写成 JSON
    --dry-run         只列出将要处理的文件与目标路径

== 输出 ==
- 保持相对目录结构：源 A/B/x.png → <output>/B/x.webp
- 逐文件一行结果 + 汇总表（原始大小 / 压缩后 / 缩减比 / 尺寸）
- 退出码：全部成功 0；存在失败 2；参数或环境错误 1

== 必须知道的坑 ==
服务端按 md5 秒传，重复上传同一份字节会复用旧记录；旧记录的原始文件 5 分钟即
过期，重传还会把分片记录写坏。因此每份文件都会先经 unique_copy 注入一段无损
元数据注记（像素不变、md5 变新）再上传。详见 references/pixelforge-protocol.md。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pf_client import (  # noqa: E402
    DEFAULT_BASE_URL,
    EXT_FOR_FORMAT,
    FORMATS,
    LEVELS,
    LEVEL_LABELS,
    PixelForge,
    PixelForgeError,
)
from unique_copy import unique_copy  # noqa: E402

SUPPORTED_EXT = (".png", ".jpg", ".jpeg", ".webp")
FORMAT_FOR_EXT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


def human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def collect(source: Path, exts) -> list:
    if source.is_file():
        return [source]
    files = [
        p
        for p in sorted(source.rglob("*"))
        if p.is_file() and p.suffix.lower() in exts and not p.name.startswith(".")
    ]
    return files


def resolve_format(fmt: str, src: Path) -> str:
    if fmt != "keep":
        return fmt
    return FORMAT_FOR_EXT.get(src.suffix.lower(), "webp")


def dest_for(src: Path, root: Path, out_dir: Path, fmt: str) -> Path:
    rel = src.relative_to(root) if root.is_dir() else Path(src.name)
    return (out_dir / rel).with_suffix(EXT_FOR_FORMAT[fmt])


def process_api(client: PixelForge, src: Path, dest: Path, temp_dir: Path,
                level: str, fmt: str) -> dict:
    staged = temp_dir / src.name
    unique_copy(src, staged)
    return client.process_file(staged, dest, level=level, fmt=fmt)


def process_ui(client, ui, src: Path, dest: Path, temp_dir: Path,
               level: str, fmt: str) -> dict:
    staged = temp_dir / src.name
    unique_copy(src, staged)
    data = ui.compress(staged, level=level, fmt=fmt)
    written = client.download(data["downloadUrl"], dest)
    if written != data["compressedSize"]:
        raise PixelForgeError(
            f"下载字节数不一致：期望 {data['compressedSize']}，实得 {written}"
        )
    return {
        "file": str(src),
        "out": str(dest),
        "level": data["level"],
        "format": data["format"],
        "original_size": data["originalSize"],
        "compressed_size": data["compressedSize"],
        "ratio": data["ratio"],
        "width": data["width"],
        "height": data["height"],
        "bytes_ok": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="批量把本地图片交给 PixelForge 压缩并输出到新目录",
    )
    parser.add_argument("source", help="源目录（递归）或图片文件")
    parser.add_argument(
        "-o", "--output", default=None,
        help="输出目录，默认 <source>-compressed（相对路径基于 cwd）",
    )
    parser.add_argument("--level", default="standard", choices=sorted(LEVELS),
                        help="压缩档位，默认 standard")
    parser.add_argument("--format", default="keep", choices=[*FORMATS, "keep"],
                        help="输出格式，默认 keep（保持原格式）")
    parser.add_argument("--mode", default="api", choices=("api", "ui"),
                        help="api=直接调服务端接口（默认）；ui=驱动真实网页")
    parser.add_argument("--ext", action="append", default=None,
                        help="只处理这些扩展名，可多次指定，默认 png/jpg/jpeg/webp")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="站点根地址")
    parser.add_argument("--session", default="pixelforge",
                        help="--mode ui 时使用的 chrome-use 会话名")
    parser.add_argument("--report", default=None, help="把逐文件结果写成 JSON")
    parser.add_argument("--attempts", type=int, default=2, help="单文件最大尝试次数")
    parser.add_argument(
        "--fallback-api", dest="fallback_api", action="store_true", default=True,
        help="--mode ui 时网页链路失败则改用服务端接口兜底（默认开启）",
    )
    parser.add_argument("--no-fallback-api", dest="fallback_api", action="store_false",
                        help="关闭网页模式的接口兜底")
    parser.add_argument("--dry-run", action="store_true", help="只列出计划，不发请求")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        print(f"错误：源路径不存在：{source}", file=sys.stderr)
        return 1
    out_dir = Path(args.output).expanduser().resolve() if args.output else (
        source.parent / f"{source.name}-compressed" if source.is_dir()
        else source.parent / f"{source.stem}-compressed"
    )
    if source.is_dir():
        try:
            out_dir.relative_to(source)
            print(f"错误：输出目录 {out_dir} 位于源目录之内，会边写边扫。", file=sys.stderr)
            return 1
        except ValueError:
            pass

    exts = {e.lower().lstrip(".") for e in (args.ext or [])}
    exts = {f".{e}" for e in exts} if exts else set(SUPPORTED_EXT)
    unknown = sorted(exts - set(SUPPORTED_EXT))
    if unknown:
        print(f"错误：不支持注入唯一副本的扩展名：{', '.join(unknown)}", file=sys.stderr)
        return 1

    files = collect(source, exts)
    if not files:
        print(f"错误：{source} 下没有匹配的图片（{', '.join(sorted(exts))}）", file=sys.stderr)
        return 1

    client = PixelForge(args.base_url)
    ui = None
    if args.mode == "ui" and not args.dry_run:
        try:
            from pf_ui import PixelForgeUI
            ui = PixelForgeUI(args.base_url, args.session)
        except Exception as exc:
            print(f"错误：无法启动浏览器驱动：{exc}", file=sys.stderr)
            return 1

    print(f"开始时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"源：{source}")
    print(f"目标：{out_dir}")
    print(f"档位：{args.level}（{LEVEL_LABELS[args.level]}）  格式：{args.format}  "
          f"模式：{args.mode}  文件数：{len(files)}")
    if LEVELS[args.level]["resize_ratio"] < 1.0:
        print(f"注意：{LEVEL_LABELS[args.level]} 会把尺寸缩放到 "
              f"{LEVELS[args.level]['resize_ratio'] * 100:.0f}%，画面会有可见损失。")
    if args.dry_run:
        for src in files:
            fmt = resolve_format(args.format, src)
            print(f"  {src}  ->  {dest_for(src, source, out_dir, fmt)}")
        return 0

    total_bytes = sum(p.stat().st_size for p in files)
    quota = client.quota(total_bytes)
    max_file = quota.get("maxFileSize") or 0
    oversized = [p for p in files if max_file and p.stat().st_size > max_file]
    if oversized:
        for p in oversized:
            print(f"错误：{p} 超过站点单文件上限 {human(max_file)}", file=sys.stderr)
        return 1
    if not quota.get("available", True):
        print("错误：站点存储空间不足，请稍后再试。", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    failures = []
    results = []
    temp_root = Path(tempfile.mkdtemp(prefix="pixel-forge-"))
    started = time.time()
    try:
        for index, src in enumerate(files, 1):
            fmt = resolve_format(args.format, src)
            dest = dest_for(src, source, out_dir, fmt)
            dest.parent.mkdir(parents=True, exist_ok=True)
            rel = src.relative_to(source) if source.is_dir() else Path(src.name)
            label = f"[{index}/{len(files)}] {rel}"
            record = None
            error = None
            for attempt in range(1, args.attempts + 1):
                t0 = time.time()
                try:
                    if args.mode == "ui":
                        record = process_ui(client, ui, src, dest, temp_root,
                                            args.level, fmt)
                    else:
                        record = process_api(client, src, dest, temp_root,
                                             args.level, fmt)
                    record["seconds"] = round(time.time() - t0, 1)
                    record["attempt"] = attempt
                    break
                except Exception as exc:  # 网络、协议、图片结构、磁盘等
                    error = f"{type(exc).__name__}: {exc}"
                    if attempt < args.attempts:
                        print(f"{label} 第 {attempt} 次失败，重试：{error}", file=sys.stderr)
                        time.sleep(2)
            if record is None and args.mode == "ui" and args.fallback_api:
                # 网页链路会卡在服务端本身也有问题的文件上（例如 merge 504），
                # 同一套接口加上 merge 重试即可成功，见 references/pixelforge-protocol.md
                print(f"{label} 网页链路失败，改用服务端接口兜底：{error}", file=sys.stderr)
                fallback_started = time.time()
                try:
                    record = process_api(client, src, dest, temp_root, args.level, fmt)
                    record["seconds"] = round(time.time() - fallback_started, 1)
                    record["attempt"] = "api-fallback"
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            if record is None:
                failures.append((rel, error))
                print(f"{label} 失败：{error}", file=sys.stderr)
                results.append({"file": str(rel), "error": error})
                continue
            results.append(record)
            saved = 100 * (1 - record["compressed_size"] / record["original_size"])
            print(
                f"{label}  {human(record['original_size'])} -> "
                f"{human(record['compressed_size'])}  缩减 {saved:.1f}%  "
                f"{record['width']}x{record['height']}  {record['seconds']}s"
            )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    ok = [r for r in results if "error" not in r]
    total_before = sum(r["original_size"] for r in ok)
    total_after = sum(r["compressed_size"] for r in ok)
    print(f"\n耗时：{time.time() - started:.1f} 秒")
    if total_before:
        print(f"合计：{human(total_before)} -> {human(total_after)}  "
              f"缩减 {100 * (1 - total_after / total_before):.1f}%")
    print(f"成功 {len(ok)} 个，失败 {len(failures)} 个，输出目录：{out_dir}")
    if failures:
        print("失败列表：", file=sys.stderr)
        for rel, error in failures:
            print(f"  {rel}: {error}", file=sys.stderr)
    if args.report:
        report = Path(args.report).expanduser()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(
            {
                "source": str(source),
                "output": str(out_dir),
                "level": args.level,
                "format": args.format,
                "mode": args.mode,
                "results": results,
            },
            ensure_ascii=False, indent=1,
        ))
        print(f"报告：{report}")
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
