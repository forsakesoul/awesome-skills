#!/usr/bin/env python3
"""
pf_ui.py —— 用真实 Chrome 驱动 PixelForge 网页完成上传与压缩。

和 pf_client（直接打服务端接口）相比，这条路走的是网页本身的操作链路：
拖拽/选择文件 → 选档位 → 选格式 → 点「开始压缩」→ 取回压缩结果。
用于「必须通过网页界面操作」或需要人工肉眼核对预览对比的场景。

依赖 chrome-use CLI（https://github.com/leeguooooo/chrome-use）。
每条命令都带 --session <名字>，因此不会碰到用户正在用的其它标签页。

== 为什么要这么多等待与钩子 ==
- 页面的上传状态（hashing → checking → uploading → merging → complete）是
  React 状态，上一张图的「上传完成 / 开始压缩」文本在下一张图开始上传后
  仍会短暂保留，仅凭文本判断会点到上一张图的压缩结果；
  因此必须等「文件名: <当前文件名>」出现。
- /api/compress 的响应只存在于 React 内部 state 里，页面不会把它暴露到 DOM，
  所以在页面里挂一个 fetch 钩子，把压缩响应收集到 window.__pfComp。
- 档位/格式按钮的 textContent 是小写（'png'），可访问名才是大写（'PNG'），
  匹配时统一转小写。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pf_client import LEVEL_LABELS

INSTALL_HINT = (
    "未找到 chrome-use CLI。安装：\n"
    "  curl -fsSL https://raw.githubusercontent.com/leeguooooo/chrome-use/main/install.sh | sh"
)

# 把 /api/compress 的响应收集到 window.__pfComp（页面自身不改动，只旁路读取）
HOOK_COMPRESS = (
    "(()=>{if(window.__pfCompHooked)return 'ok';window.__pfCompHooked=1;window.__pfComp=[];"
    "const orig=window.fetch;"
    "window.fetch=async function(...args){const resp=await orig.apply(this,args);"
    "try{const url=(typeof args[0]==='string'?args[0]:(args[0]&&args[0].url))||'';"
    "if(url.indexOf('/api/compress')>=0){const clone=resp.clone();"
    "clone.json().then(j=>window.__pfComp.push(j)).catch(()=>{});}}catch(e){}"
    "return resp;};return 'hooked';})()"
)


class UIError(RuntimeError):
    pass


class ChromeUse:
    """chrome-use CLI 的极薄封装：每个方法一次子进程调用。"""

    def __init__(self, session: str):
        self.session = session
        self.bin = shutil.which("chrome-use")
        if not self.bin:
            raise UIError(INSTALL_HINT)

    def _run(self, *args, timeout=300, check=True):
        proc = subprocess.run(
            [self.bin, *args, "--session", self.session],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and proc.returncode != 0:
            raise UIError(f"chrome-use {' '.join(args)} 失败：{proc.stderr.strip()}")
        return proc.stdout

    def open(self, url: str):
        self._run("open", url)

    def upload(self, selector: str, path):
        # 上传后页面会把 input.value 清空，命令的返回值因此不可靠；以页面文本为准
        self._run("upload", selector, str(path), check=False)

    def eval_str(self, code: str, timeout=120) -> str:
        return self._run("eval", code, timeout=timeout).strip()

    def eval_json(self, code: str, timeout=120):
        raw = self.eval_str(f"JSON.stringify({code})", timeout=timeout)
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except Exception:
            return None
        if isinstance(value, str):  # 字符串返回会被 CLI 再套一层引号
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def page_text(self, limit: int = 400) -> str:
        raw = self.eval_str(f"document.body.innerText.slice(0,{limit})")
        try:
            return json.loads(raw)
        except Exception:
            return raw.strip('"')


class PixelForgeUI:
    def __init__(self, base_url: str, session: str = "pixelforge",
                 file_input: str = "input[type=file]"):
        self.base_url = base_url.rstrip("/")
        self.file_input = file_input
        self.cli = ChromeUse(session)
        self.cli.open(self.base_url)
        time.sleep(2)
        self.cli.eval_str(HOOK_COMPRESS)

    # ---------- 页面交互 ----------

    def _click_button(self, predicate_js: str, what: str):
        code = (
            "(()=>{const b=[...document.querySelectorAll('button')]"
            f".find({predicate_js});"
            "if(!b)return 'NOTFOUND';b.click();return 'OK';})()"
        )
        got = self.cli.eval_json(code)
        if got != "OK":
            raise UIError(f"页面上找不到按钮：{what}")

    def _select_level(self, level: str):
        label = LEVEL_LABELS[level]
        self._click_button(f"x=>x.textContent.trim().startsWith('{label}')", f"档位 {label}")

    def _select_format(self, fmt: str):
        self._click_button(
            f"x=>x.textContent.trim().toLowerCase()==='{fmt.lower()}'", f"格式 {fmt}"
        )

    def _result_count(self) -> int:
        return self.cli.eval_json("window.__pfComp.length") or 0

    def _wait(self, condition_js: str, what: str, timeout: float):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.cli.eval_json(f"({condition_js})") is True:
                return
            time.sleep(1.0)
        raise UIError(f"等待超时（{timeout:.0f}s）：{what}")

    # ---------- 单文件流程 ----------

    def compress(self, path, level: str = "standard", fmt: str = "webp",
                 timeout: float = 420.0) -> dict:
        path = Path(path)
        before = self._result_count()
        self.cli.upload(self.file_input, path)
        base = path.name
        self._wait(
            "document.body.innerText.indexOf('开始压缩')>=0"
            " && document.body.innerText.indexOf('上传完成')>=0"
            f" && document.body.innerText.indexOf('文件名: {base}')>=0",
            f"上传完成（{base}）",
            timeout,
        )
        self._select_level(level)
        self._select_format(fmt)
        self._click_button("x=>x.textContent.trim().startsWith('开始压缩')", "开始压缩")
        deadline = time.time() + timeout
        while time.time() < deadline:
            entries = self.cli.eval_json(f"window.__pfComp.slice({before})") or []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("code") == 0 and entry.get("data"):
                    data = entry["data"]
                    if data.get("format") == fmt and data.get("level") == level:
                        return data
                elif entry.get("code"):
                    raise UIError(f"站点压缩失败：{entry.get('message')}")
            time.sleep(1.0)
        raise UIError(f"等待压缩结果超时：{base}")
