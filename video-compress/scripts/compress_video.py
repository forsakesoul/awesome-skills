#!/usr/bin/env python3
"""Compress videos with ffmpeg into a new directory, by target size or by quality (CRF).

Sources are never modified. Every output is H.264 + AAC MP4 with faststart and is checked with ffprobe.
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
CRF_START, CRF_STEP, CRF_MAX = 20, 2, 36


def parse_size(text):
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmg]?)i?b?\s*", text, re.I)
    if not m:
        raise argparse.ArgumentTypeError(f"invalid size: {text} (examples: 9.5MB, 50M, 800K)")
    return int(float(m[1]) * 1024 ** "_kmg".index(m[2].lower() or "_"))


def human(n):
    return f"{n / 1024 / 1024:.2f} MB"


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,height",
                        "-of", "json", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    d = json.loads(r.stdout)
    types = [s.get("codec_type") for s in d.get("streams", [])]
    height = next((s.get("height") for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    return {"duration": float(d.get("format", {}).get("duration") or 0), "video": "video" in types,
            "audio": "audio" in types, "height": height}


def encode(src, dst, crf, args):
    vf = f"scale=-2:'min(ih,{args.max_height})'" if args.max_height else None
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", args.preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", args.audio_bitrate, "-movflags", "+faststart"]
    if vf:
        cmd += ["-vf", vf]
    r = subprocess.run(cmd + [str(dst)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "ffmpeg failed")


def compress(src, dst, args):
    """Returns a result dict; raises RuntimeError on failure."""
    size = src.stat().st_size
    if args.max_size is None:
        encode(src, dst, args.crf, args)
        return {"crf": args.crf}
    if size <= args.max_size and not args.max_height and src.suffix.lower() == ".mp4":
        shutil.copy2(src, dst)
        return {"crf": None, "note": "already under target size, copied unchanged"}
    crf = CRF_START
    while True:
        encode(src, dst, crf, args)
        got = dst.stat().st_size
        if got <= args.max_size:
            return {"crf": crf}
        if crf >= CRF_MAX:
            break
        # x264 rule of thumb: +6 CRF roughly halves the size, so jump to the estimate instead of stepping.
        crf = min(CRF_MAX, crf + max(CRF_STEP, math.ceil(6 * math.log2(got / args.max_size))))
    dst.unlink(missing_ok=True)
    raise RuntimeError(f"still over {human(args.max_size)} at CRF {CRF_MAX}; lower the resolution with --max-height")


def verify(src, dst):
    a, b = probe(src), probe(dst)
    if not b or not b["video"]:
        return "output has no video stream"
    if a and a["audio"] and not b["audio"]:
        return "output lost the audio stream"
    if a and abs(a["duration"] - b["duration"]) > 0.5:
        return f"duration changed: {a['duration']:.2f}s -> {b['duration']:.2f}s"
    return None


def collect(source):
    if source.is_file():
        return [source]
    return sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in EXTS)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path, help="a video file, or a directory scanned recursively")
    p.add_argument("-o", "--output", type=Path, help="output directory (default: <source>-compressed)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--max-size", type=parse_size, help="target size per file, e.g. 9.5MB; raises CRF until it fits")
    mode.add_argument("--crf", type=int, default=23, help="fixed quality, lower is better (default 23)")
    p.add_argument("--max-height", type=int, help="downscale to at most this height; never upscales")
    p.add_argument("--audio-bitrate", default="128k")
    p.add_argument("--preset", default="slow", help="x264 preset (slower = smaller at the same quality)")
    p.add_argument("--dry-run", action="store_true", help="list the plan without encoding")
    args = p.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found; install it first (macOS: brew install ffmpeg)")
    source = args.source.resolve()
    if not source.exists():
        sys.exit(f"source not found: {source}")
    base = source.parent / f"{source.stem}-compressed" if source.is_file() else Path(f"{source}-compressed")
    out = (args.output or base).resolve()
    if source.is_dir() and out.is_relative_to(source):
        sys.exit("output directory must not be inside the source directory")

    files = collect(source)
    if not files:
        sys.exit("no video files found")
    plans = [(f, out / (f.relative_to(source).with_suffix(".mp4") if source.is_dir() else f.with_suffix(".mp4").name))
             for f in files]
    if any(dst.resolve() == src for src, dst in plans):
        sys.exit("output would overwrite a source file")
    if args.dry_run:
        for src, dst in plans:
            print(f"{src} ({human(src.stat().st_size)}) -> {dst}")
        return

    failed = 0
    for src, dst in plans:
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            res = compress(src, dst, args)
            problem = verify(src, dst)
            if problem:
                raise RuntimeError(problem)
            before, after = src.stat().st_size, dst.stat().st_size
            crf = f"CRF {res['crf']}" if res["crf"] is not None else res["note"]
            print(f"ok    {src.name}: {human(before)} -> {human(after)} ({after / before:.0%}, {crf}) -> {dst}")
        except RuntimeError as e:
            failed += 1
            print(f"FAIL  {src.name}: {e}", file=sys.stderr)
    print(f"{len(plans) - failed} ok, {failed} failed; output: {out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
