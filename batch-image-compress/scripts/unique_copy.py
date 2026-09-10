#!/usr/bin/env python3
"""
unique_copy.py —— 生成「像素完全相同、md5 不同」的图片副本。

== 为什么需要它 ==
PixelForge（以及不少按内容 hash 做秒传的图床/压缩服务）以 md5 作为去重键：
重复上传同一份字节会命中「秒传」分支，直接复用服务端已有记录而不是重新落盘。
当那条记录的原始文件已过 TTL 被清理、或分片记录被重复上传写坏时，
后续的合并与压缩就会失败（典型报错见 references/pixelforge-protocol.md）。
批量复压前先给每份文件注入一段无损元数据注记，换取一个全新的 md5，
是绕过该问题最省事、且不改动像素的做法。

== 注入方式（不改像素、不改解码结果）==
- PNG ：在 IEND 之前插入一个 tEXt(Comment) 块，并重算 CRC32
- JPEG：在 SOI 之后插入一个 COM(0xFFFE) 段
- WebP：在 RIFF/WEBP 头部之后插入一个 JUNK 块，并修正 RIFF 长度字段

== 用法 ==
    python3 unique_copy.py <src> [dst] [-n NOTE]

不给 dst 时输出到 <src 同目录>/<stem>.unique<suffix>。
末尾打印结果路径与 md5。
"""
from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import uuid
import zlib
from pathlib import Path

PNG_SIG = b"\x89PNG\r\n\x1a\n"
SOI = b"\xff\xd8"
SUPPORTED = (".png", ".jpg", ".jpeg", ".webp")
DEFAULT_NOTE = "batch-image-compress"


class UnsupportedImage(ValueError):
    """既不是 PNG / JPEG / WebP，或结构损坏无法安全注入。"""


def md5_of(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def inject_note(data: bytes, note: str) -> bytes:
    """在图片容器里插入一段注记，返回字节完全等价于原图、仅元数据不同的副本。"""
    marker = f"{note}:{uuid.uuid4().hex}".encode("ascii")
    if data.startswith(PNG_SIG):
        return _png_with_text(data, marker)
    if data.startswith(SOI):
        return _jpeg_with_comment(data, marker)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_with_junk(data, marker)
    raise UnsupportedImage("仅支持 PNG / JPEG / WebP，且文件头必须完整")


def _png_with_text(data: bytes, marker: bytes) -> bytes:
    iend = data.rfind(b"IEND")
    if iend < 4:
        raise UnsupportedImage("PNG 缺少 IEND 块")
    # 块长度只覆盖类型之后的 data，CRC 覆盖 type + data
    body = b"Comment\x00" + marker
    chunk = (
        struct.pack(">I", len(body))
        + b"tEXt"
        + body
        + struct.pack(">I", zlib.crc32(b"tEXt" + body) & 0xFFFFFFFF)
    )
    return data[: iend - 4] + chunk + data[iend - 4 :]


def _jpeg_with_comment(data: bytes, marker: bytes) -> bytes:
    if len(marker) + 2 > 0xFFFF:
        raise UnsupportedImage("COM 段内容过长")
    segment = b"\xff\xfe" + struct.pack(">H", len(marker) + 2) + marker
    return data[:2] + segment + data[2:]


def _webp_with_junk(data: bytes, marker: bytes) -> bytes:
    payload = marker if len(marker) % 2 == 0 else marker + b"\x00"
    chunk = b"JUNK" + struct.pack("<I", len(payload)) + payload
    riff_size = struct.unpack("<I", data[4:8])[0] + len(chunk)
    return (
        data[:4]
        + struct.pack("<I", riff_size)
        + data[8:12]
        + chunk
        + data[12:]
    )


def unique_copy(src, dst=None, note: str = DEFAULT_NOTE) -> Path:
    """把 src 写成一份内容等价、md5 不同的副本，返回副本路径。"""
    src = Path(src).expanduser()
    data = src.read_bytes()
    copy = inject_note(data, note)
    if dst is None:
        dst = src.with_name(f"{src.stem}.unique{src.suffix}")
    dst = Path(dst).expanduser()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(copy)
    if dst.stat().st_size != len(copy):
        raise OSError(f"写入不完整：{dst}")
    return dst


def main() -> int:
    parser = argparse.ArgumentParser(description="生成像素相同、md5 不同的图片副本")
    parser.add_argument("src", help="源图片（PNG / JPEG / WebP）")
    parser.add_argument("dst", nargs="?", help="输出路径，默认 <stem>.unique<suffix>")
    parser.add_argument("-n", "--note", default=DEFAULT_NOTE, help="注记前缀")
    args = parser.parse_args()

    try:
        src_data = Path(args.src).expanduser().read_bytes()
        out = unique_copy(args.src, args.dst, args.note)
    except (OSError, UnsupportedImage) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(f"源：{args.src}  md5={md5_of(src_data)}")
    print(f"副本：{out}  md5={md5_of(out.read_bytes())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
