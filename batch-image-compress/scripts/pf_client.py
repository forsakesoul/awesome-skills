#!/usr/bin/env python3
"""
pf_client.py —— PixelForge 压缩服务的最小 HTTP 客户端。

网页（https://pixel-forge-phi-three.vercel.app）前端用的是同一套接口，
所以这个客户端既能作为网页驱动失败时的兜底，也能独立批量处理：

    GET  /api/quota?intendedBytes=<n>          配额与限制（fileTtl / maxFileSize）
    GET  /api/upload/status?hash=&totalChunks= 已存在的分片索引 + isComplete
    POST /api/upload/chunk                     multipart: hash, index, chunk
    POST /api/upload/merge                     {hash, filename, totalChunks, fileSize, mimeType}
    POST /api/compress                         {fileId, level, format, quality?, width?, height?}
    GET  <downloadUrl>                         压缩结果（公开 blob，带 ?download=1）

完整协议、档位参数与服务端坑位见 references/pixelforge-protocol.md。
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_BASE_URL = "https://pixel-forge-phi-three.vercel.app"
CHUNK_SIZE = 2 * 1024 * 1024
CHUNK_WORKERS = 3
CHUNK_RETRIES = 3
MERGE_RETRIES = 4
MERGE_BACKOFF = 3.0

# 与网页「压缩档位」一一对应：quality 越小 / resizeRatio 越小，压得越狠
LEVELS = {
    "light": {"quality": 90, "resize_ratio": 1.0, "png_level": 3, "webp_effort": 2},
    "standard": {"quality": 75, "resize_ratio": 1.0, "png_level": 6, "webp_effort": 4},
    "high": {"quality": 60, "resize_ratio": 1.0, "png_level": 7, "webp_effort": 5},
    "aggressive": {"quality": 40, "resize_ratio": 0.8, "png_level": 8, "webp_effort": 6},
    "extreme": {"quality": 20, "resize_ratio": 0.6, "png_level": 9, "webp_effort": 6},
}
FORMATS = ("jpeg", "png", "webp", "avif")
LEVEL_LABELS = {
    "light": "轻度压缩",
    "standard": "标准压缩",
    "high": "较强压缩",
    "aggressive": "强力压缩",
    "extreme": "极限压缩",
}
EXT_FOR_FORMAT = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "avif": ".avif"}
MIME_FOR_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".avif": "image/avif",
}


class PixelForgeError(RuntimeError):
    """服务端返回 code != 0，或网络/协议层失败。"""


def plan_chunks(size: int, chunk_size: int = CHUNK_SIZE):
    """把文件切成 [(index, start, end)]，与网页前端的分片逻辑一致。"""
    if size <= 0:
        raise ValueError("文件大小为 0，无法上传")
    total = math.ceil(size / chunk_size)
    return [(i, i * chunk_size, min((i + 1) * chunk_size, size)) for i in range(total)]


def guess_mime(path) -> str:
    return MIME_FOR_EXT.get(Path(path).suffix.lower(), "application/octet-stream")


class PixelForge:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 120.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    # ---------- 基础请求 ----------

    def _raw(self, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def _json(self, url, data=None, headers=None, allow_plain_error=True):
        status, raw = self._raw(url, data, headers)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            if not allow_plain_error:
                raise
            # Vercel 平台级错误（超时/体积超限）返回的是纯文本，不是 JSON
            text = raw[:200].decode("utf-8", "replace").strip()
            return status, {"code": -1, "message": f"HTTP {status}: {text}", "data": None}
        return status, payload

    @staticmethod
    def _ok(payload, what):
        if payload.get("code") != 0:
            raise PixelForgeError(f"{what} 失败：{payload.get('message')}")
        return payload.get("data")

    def quota(self, intended_bytes: int = 0) -> dict:
        query = urllib.parse.urlencode({"intendedBytes": str(intended_bytes)})
        status, payload = self._json(f"{self.base}/api/quota?{query}")
        return self._ok(payload, "查询配额")

    def upload_status(self, file_hash: str, total_chunks: int) -> dict:
        query = urllib.parse.urlencode(
            {"hash": file_hash, "totalChunks": str(total_chunks)}
        )
        status, payload = self._json(f"{self.base}/api/upload/status?{query}")
        return self._ok(payload, "查询上传状态")

    def upload_chunk(self, file_hash: str, index: int, chunk: bytes) -> dict:
        body, content_type = _multipart(
            {
                "hash": (None, file_hash.encode()),
                "index": (None, str(index).encode()),
                "chunk": (f"chunk{index}.bin", chunk),
            }
        )
        status, payload = self._json(
            f"{self.base}/api/upload/chunk",
            data=body,
            headers={"Content-Type": content_type},
        )
        return self._ok(payload, f"上传分片 {index}")

    def merge(self, file_hash: str, filename: str, total_chunks: int,
              file_size: int, mime_type: str) -> dict:
        body = json.dumps(
            {
                "hash": file_hash,
                "filename": filename,
                "totalChunks": total_chunks,
                "fileSize": file_size,
                "mimeType": mime_type,
            }
        ).encode()
        status, payload = self._json(
            f"{self.base}/api/upload/merge",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        return self._ok(payload, "合并分片")

    def compress(self, file_id: str, level: str = "standard", fmt: str = "webp",
                 quality=None, width=None, height=None) -> dict:
        if level not in LEVELS:
            raise ValueError(f"未知档位：{level}，可选 {sorted(LEVELS)}")
        if fmt not in FORMATS:
            raise ValueError(f"未知格式：{fmt}，可选 {list(FORMATS)}")
        spec = {"fileId": file_id, "level": level, "format": fmt}
        if quality is not None:
            spec["quality"] = int(quality)
        if width is not None:
            spec["width"] = int(width)
        if height is not None:
            spec["height"] = int(height)
        body = json.dumps(spec).encode()
        status, payload = self._json(
            f"{self.base}/api/compress",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        return self._ok(payload, "压缩")

    # ---------- 组合流程 ----------

    def upload_file(self, path, progress=None) -> dict:
        """分片上传 + 合并，返回 {fileId, width, height, ...}。

        完全复刻网页前端：先查 status 秒传，只补传缺失分片，再 merge。
        merge 可能返回平台级 504（FUNCTION_INVOCATION_TIMEOUT），
        此时服务端通常仍在后台完成合并，重试即可命中「秒传」分支。
        """
        path = Path(path)
        data = path.read_bytes()
        file_hash = hashlib.md5(data).hexdigest()
        chunks = plan_chunks(len(data), CHUNK_SIZE)
        total = len(chunks)
        status = self.upload_status(file_hash, total)
        if not status.get("isComplete"):
            have = set(status.get("uploadedChunks") or [])
            pending = [c for c in chunks if c[0] not in have]
            for index, start, end in pending:
                self._upload_chunk_with_retry(file_hash, index, data[start:end])
                if progress:
                    progress(index + 1, total)
        return self._merge_with_retry(file_hash, path.name, total, len(data),
                                      guess_mime(path))

    def _upload_chunk_with_retry(self, file_hash, index, chunk):
        last = None
        for _ in range(CHUNK_RETRIES):
            try:
                return self.upload_chunk(file_hash, index, chunk)
            except Exception as exc:  # 网络抖动 / 服务端 5xx
                last = exc
                time.sleep(1.0)
        raise PixelForgeError(f"分片 {index} 上传失败：{last}")

    def _merge_with_retry(self, file_hash, filename, total, size, mime):
        last = None
        for attempt in range(MERGE_RETRIES):
            try:
                return self.merge(file_hash, filename, total, size, mime)
            except Exception as exc:
                last = exc
                time.sleep(MERGE_BACKOFF)
                # 若分片被判定不完整，重新对齐一次再试
                if "incomplete" in str(exc).lower():
                    try:
                        have = set(
                            (self.upload_status(file_hash, total).get("uploadedChunks") or [])
                        )
                        if len(have) < total:
                            raise PixelForgeError(
                                f"服务端分片记录不完整（{len(have)}/{total}），"
                                "该 hash 已被写坏，请改用新的 hash（unique_copy）重传"
                            )
                    except PixelForgeError:
                        raise
                    except Exception:
                        pass
        raise PixelForgeError(f"合并分片失败（重试 {MERGE_RETRIES} 次）：{last}")

    def download(self, url: str, dest) -> int:
        status, raw = self._raw(url)
        if status != 200:
            raise PixelForgeError(f"下载失败：HTTP {status}")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return len(raw)

    def process_file(self, src, dest, level="standard", fmt="webp", progress=None) -> dict:
        """上传 → 压缩 → 下载，返回一行结果记录。"""
        info = self.upload_file(src, progress=progress)
        result = self.compress(info["fileId"], level=level, fmt=fmt)
        written = self.download(result["downloadUrl"], dest)
        record = {
            "file": str(src),
            "out": str(dest),
            "level": result["level"],
            "format": result["format"],
            "original_size": result["originalSize"],
            "compressed_size": result["compressedSize"],
            "ratio": result["ratio"],
            "width": result["width"],
            "height": result["height"],
            "src_width": info.get("width"),
            "src_height": info.get("height"),
            "bytes_ok": written == result["compressedSize"],
        }
        if not record["bytes_ok"]:
            raise PixelForgeError(
                f"下载字节数不一致：期望 {result['compressedSize']}，实得 {written}"
            )
        return record


def _multipart(fields) -> tuple:
    """把 {name: (filename|None, bytes)} 编码成 multipart/form-data。"""
    boundary = "----PixelForgeBatch" + uuid.uuid4().hex
    parts = []
    for name, (filename, content) in fields.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
        if filename:
            head += f'; filename="{filename}"\r\nContent-Type: application/octet-stream'
        parts.append(head.encode() + b"\r\n\r\n" + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
