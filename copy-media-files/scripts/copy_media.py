#!/usr/bin/env python3
"""
copy_media.py —— 并发递归复制媒体文件（按扩展名过滤），保留相对目录结构。

== 使用场景 ==
从相机 SD 卡 / DCIM 目录中按扩展名（.arw / .hif / .jpg 等）把照片复制到本地
存档目录。源文件不会被删除（复制语义，不是移动）。

== 用法 ==
    python3 copy_media.py <source> [-o OUTPUT] [-e EXT ...] [-w WORKERS]

参数说明：
    source            源目录（会被递归扫描）。路径含空格请用引号包起来
    -o, --output      目标子目录名（位于当前工作目录下），默认 arw_files
                      支持嵌套，如 2026/firstHalfYear
    -e, --ext         要复制的扩展名，可多次指定。默认 arw
                      不区分大小写，前导点可省略。例：-e arw -e hif
    -w, --workers     并发线程数，默认 16（SSD/高速读卡器可调大，
                      慢速 USB 或机械盘建议 4 ~ 8）

== 示例 ==
    # 仅复制 .arw（默认）
    python3 copy_media.py /Volumes/Untitled/DCIM

    # 复制到 ./2026/firstHalfYear/，扩展名为 .hif
    python3 copy_media.py "/Volumes/Untitled/DCIM" -o 2026/firstHalfYear -e hif

    # 同时复制 RAW 和 HEIF（双格式拍摄）
    python3 copy_media.py "/Volumes/Untitled/DCIM" -o backup -e arw -e hif

    # 加大并发线程数
    python3 copy_media.py "/Volumes/Untitled/DCIM" -e arw -w 32

== 行为说明 ==
- 递归遍历源目录所有层级；命中扩展名的文件会被复制
- 保留相对路径结构：源 A/B/C/x.arw → 目标 <output>/B/C/x.arw
- 使用 shutil.copy2，会同时复制 mtime / 权限等元数据（EXIF 不受影响）
- 同名冲突自动加 _1 / _2 后缀，不会覆盖已有文件
- 防呆：若目标目录在源目录内会拒绝执行（避免边复制边扫描的递归）
- 不打印每次复制记录；起止时间、耗时、成功/失败汇总会输出
- 仅失败的文件会打印到 stderr，附报错信息；存在失败时退出码为 2
"""
from __future__ import annotations

import argparse
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


_name_lock = threading.Lock()
_reserved: set[Path] = set()


def reserve_destination(target: Path) -> Path:
    with _name_lock:
        stem, suffix = target.stem, target.suffix
        parent = target.parent
        candidate = target
        i = 1
        while candidate.exists() or candidate in _reserved:
            candidate = parent / f"{stem}_{i}{suffix}"
            i += 1
        _reserved.add(candidate)
        return candidate


def copy_one(src: Path, target: Path) -> tuple[Path, str | None]:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        final_target = reserve_destination(target)
        shutil.copy2(str(src), str(final_target))
        return src, None
    except OSError as e:
        return src, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="并发递归复制媒体文件到目标子目录，保留相对目录结构。",
    )
    parser.add_argument("source", help="源目录（会递归扫描）")
    parser.add_argument(
        "-o", "--output", default="arw_files",
        help="目标子目录名（位于当前工作目录下），默认 arw_files。支持嵌套如 2026/firstHalfYear",
    )
    parser.add_argument(
        "-w", "--workers", type=int, default=16,
        help="并发工作线程数，默认 16",
    )
    parser.add_argument(
        "-e", "--ext", action="append",
        help="要复制的文件扩展名（不区分大小写，可多次指定）。默认 arw。例如 -e arw -e hif",
    )
    args = parser.parse_args()
    exts = {e.lower().lstrip(".") for e in (args.ext or ["arw"])}

    source = Path(args.source).expanduser().resolve()
    if not source.is_dir():
        print(f"错误：源目录不存在或不是目录：{source}", file=sys.stderr)
        return 1

    dest_root = (Path.cwd() / args.output).resolve()
    try:
        dest_root.relative_to(source)
        print(
            f"错误：目标目录 {dest_root} 位于源目录 {source} 之内，可能造成无限递归。",
            file=sys.stderr,
        )
        return 1
    except ValueError:
        pass

    dest_root.mkdir(parents=True, exist_ok=True)

    start_dt = datetime.now()
    start_perf = time.perf_counter()
    print(f"开始时间：{start_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    tasks: list[tuple[Path, Path]] = []
    for p in source.rglob("*"):
        if not p.is_file() or p.suffix.lower().lstrip(".") not in exts:
            continue
        rel = p.relative_to(source)
        tasks.append((p, dest_root / rel))

    print(
        f"扫描到 {len(tasks)} 个文件（扩展名：{', '.join(sorted(exts))}），"
        f"使用 {args.workers} 个并发线程复制..."
    )

    copied = 0
    errors: list[tuple[Path, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(copy_one, src, tgt) for src, tgt in tasks]
        for fut in as_completed(futures):
            src, err = fut.result()
            if err is None:
                copied += 1
            else:
                errors.append((src, err))

    end_dt = datetime.now()
    elapsed = time.perf_counter() - start_perf

    if errors:
        print("\n报错列表：", file=sys.stderr)
        for src, err in errors:
            print(f"  {src}: {err}", file=sys.stderr)

    print(f"\n结束时间：{end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"耗时：{elapsed:.2f} 秒")
    print(f"成功 {copied} 个，失败 {len(errors)} 个，目标目录：{dest_root}")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
