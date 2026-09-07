#!/usr/bin/env python3
"""
collect_commits.py —— 从一个或多个 Git 仓库收集「指定日期、指定作者」的提交记录，
汇总成便于阅读与总结的 Markdown 文本，供撰写「工作日报」使用。

本脚本只负责【采集 + 整理】提交数据，**不生成日报文字**——日报由 Claude 读取
本脚本的输出后撰写。这是它和原版「调用 gemini 出稿」脚本的关键区别：在 Claude Code
里，Claude 自己就是那个总结的人。

== 用法 ==
    python3 collect_commits.py REPO [REPO ...] [选项]

位置参数：
    REPO              一个或多个 Git 仓库路径（含空格请加引号）。"." 表示当前目录。

时间范围（默认「今天」；多选时以最后一个为准）：
    --today           今天 00:00 至现在（默认）
    --yesterday       昨天全天（昨天 00:00 至今天 00:00）
    --days N          最近 N 天（含今天，从 N-1 天前的 00:00 起）
    --date YYYY-MM-DD 精确自然日 [00:00, 次日 00:00)
    --timezone ZONE   IANA 时区名，如 Asia/Shanghai（默认系统本地时区）
    --since STR       原样传给 git 的 --since（一旦指定则覆盖上面的预设）
    --until STR       原样传给 git 的 --until

过滤与展示：
    -a, --author A    只统计该作者，可多次指定（多个之间是「或」关系）。
                      A 是正则，匹配 "Name <email>"，给名字或邮箱片段即可。
                      不指定 = 统计所有作者。
    --no-body         不输出提交正文（body），只保留标题。
    --files           额外列出每个提交改动的文件路径。
    --merges          包含 merge 提交（默认排除，因为合并提交一般不描述具体工作）。
    --no-all          只看当前分支（默认 --all，覆盖所有本地/远程分支）。

== 输出 ==
    Markdown 文本：开头列出本次采集用到的参数（时间范围、作者、仓库），中间按仓库
    分组列出提交（短哈希、作者、时间、标题、正文、改动量），末尾给出合计。
    若无任何提交，给出明确提示。Claude 据此撰写日报。

== 退出码 ==
    0  完整采集（可以零提交）
    1  覆盖不全或采集失败
    2  argparse 参数校验失败
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date as Date
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ASCII 控制字符作为分隔符：提交之间用 RS(0x1e)，字段之间用 US(0x1f)。
# 正常的 commit message 里不会出现这两个字节，因此可以安全地切分。
RS = "\x1e"
US = "\x1f"
GIT_FORMAT = f"--pretty=format:{RS}%H{US}%an{US}%ae{US}%cI{US}%s{US}%b{US}"


def run_git(repo: str, extra: list[str]) -> subprocess.CompletedProcess:
    """在 repo 目录下跑 git（用 -C 而非 chdir），文本模式、UTF-8、坏字节替换。"""
    return subprocess.run(
        ["git", "-C", repo, *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def is_git_repo(repo: str) -> bool:
    r = run_git(repo, ["rev-parse", "--is-inside-work-tree"])
    return r.returncode == 0 and r.stdout.strip() == "true"


def repo_meta(repo: str) -> tuple[str, str]:
    """返回 (仓库名, 当前分支)。取不到时退化为路径名 / 'unknown'。"""
    top = run_git(repo, ["rev-parse", "--show-toplevel"])
    name = (
        os.path.basename(top.stdout.strip())
        if top.returncode == 0 and top.stdout.strip()
        else os.path.basename(os.path.abspath(repo)) or repo
    )
    br = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = br.stdout.strip() if br.returncode == 0 else "unknown"
    return name, branch


def parse_commits(raw: str) -> list[dict]:
    """把 `git log <GIT_FORMAT> --numstat` 的原始输出解析成提交列表。"""
    commits: list[dict] = []
    for rec in raw.split(RS):
        if not rec.strip():
            continue
        parts = rec.split(US)
        if len(parts) < 6:
            continue
        h, an, ae, ad, subject, body = parts[:6]
        rest = parts[6] if len(parts) > 6 else ""  # body 之后跟着 numstat 行

        added = deleted = 0
        files: list[str] = []
        for line in rest.splitlines():
            line = line.strip()
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) < 3:
                continue
            a_str, d_str, path = cols[0], cols[1], "\t".join(cols[2:])
            if a_str.isdigit():
                added += int(a_str)
            if d_str.isdigit():
                deleted += int(d_str)
            files.append(path)

        commits.append(
            {
                "hash": h[:8],
                "author": an,
                "email": ae,
                "date": ad,
                "subject": subject.strip(),
                "body": body.strip(),
                "added": added,
                "deleted": deleted,
                "files": files,
            }
        )
    return commits


def resolve_timezone(name: str | None) -> tuple[tzinfo, str]:
    if name:
        try:
            return ZoneInfo(name), name
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区：{name}") from exc
    local = datetime.now().astimezone().tzinfo or timezone.utc
    return local, str(local)


def resolve_range(
    args: argparse.Namespace,
) -> tuple[str | None, str | None, str, datetime | None, datetime | None, str]:
    """返回 git 边界、标签、可复核时间边界和时区标签。"""
    tz, timezone_label = resolve_timezone(args.timezone)
    now = datetime.now(tz)

    def midnight(d: datetime) -> datetime:
        return d.replace(hour=0, minute=0, second=0, microsecond=0)

    def iso(d: datetime) -> str:
        return d.isoformat(timespec="seconds")

    if args.since or args.until:
        label = f"自定义（since={args.since or '-'}, until={args.until or '-'}）"
        return args.since, args.until, label, None, None, timezone_label
    if args.date:
        try:
            target = Date.fromisoformat(args.date)
        except ValueError as exc:
            raise ValueError(f"无效日期：{args.date}，应为 YYYY-MM-DD") from exc
        start = datetime.combine(target, datetime.min.time(), tzinfo=tz)
        end = start + timedelta(days=1)
        return iso(start), iso(end), f"指定日期（{target}）", start, end, timezone_label
    if args.yesterday:
        start = midnight(now) - timedelta(days=1)
        end = midnight(now)
        return iso(start), iso(end), f"昨天（{start:%Y-%m-%d}）", start, end, timezone_label
    if args.days:
        start = midnight(now) - timedelta(days=args.days - 1)
        return iso(start), iso(now), f"最近 {args.days} 天（{start:%Y-%m-%d} 起）", start, now, timezone_label
    # 默认：今天
    start = midnight(now)
    return iso(start), iso(now), f"今天（{now:%Y-%m-%d}）", start, now, timezone_label


def keep_in_half_open_range(
    commits: list[dict], start: datetime | None, end: datetime | None
) -> list[dict]:
    if start is None or end is None:
        return commits
    return [
        commit
        for commit in commits
        if start <= datetime.fromisoformat(commit["date"]).astimezone(start.tzinfo) < end
    ]


def build_log_cmd(args: argparse.Namespace, since: str | None, until: str | None) -> list[str]:
    cmd = ["log", "--date=format:%Y-%m-%d %H:%M", GIT_FORMAT, "--numstat"]
    if not args.no_all:
        cmd.append("--all")
    if not args.merges:
        cmd.append("--no-merges")
    if since:
        cmd += ["--since", since]
    if until:
        cmd += ["--until", until]
    for a in args.author or []:
        cmd += ["--author", a]
    return cmd


def render_commit(c: dict, show_body: bool, show_files: bool) -> list[str]:
    out = [f"### `{c['hash']}`  ·  {c['author']}  ·  {c['date']}", c["subject"] or "(无标题)"]
    if show_body and c["body"]:
        out += ["", c["body"]]
    stat = f"_{len(c['files'])} 个文件改动, +{c['added']} / −{c['deleted']}_"
    out += ["", stat]
    if show_files and c["files"]:
        out += ["<details><summary>改动文件</summary>", ""]
        out += [f"- {p}" for p in c["files"]]
        out += ["</details>"]
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description="从一个或多个 Git 仓库收集指定日期/作者的提交，汇总成 Markdown 供撰写日报。",
    )
    p.add_argument("repos", nargs="+", help="一个或多个 Git 仓库路径（'.' 表示当前目录）")
    p.add_argument("-a", "--author", action="append", help="只统计该作者，可多次指定（OR）")
    p.add_argument("--today", action="store_true", help="今天（默认）")
    p.add_argument("--yesterday", action="store_true", help="昨天全天")
    p.add_argument("--days", type=int, help="最近 N 天（含今天）")
    p.add_argument("--date", help="精确自然日（YYYY-MM-DD）")
    p.add_argument("--timezone", help="IANA 时区名，如 Asia/Shanghai（默认系统本地时区）")
    p.add_argument("--since", help="原样传给 git 的 --since（覆盖预设）")
    p.add_argument("--until", help="原样传给 git 的 --until")
    p.add_argument("--no-body", action="store_true", help="不输出提交正文")
    p.add_argument("--files", action="store_true", help="列出每个提交改动的文件路径")
    p.add_argument("--merges", action="store_true", help="包含 merge 提交（默认排除）")
    p.add_argument("--no-all", action="store_true", help="只看当前分支（默认看所有分支）")
    args = p.parse_args()

    if args.days is not None and args.days < 1:
        print("错误：--days 必须 ≥ 1", file=sys.stderr)
        return 1

    try:
        since, until, range_label, range_start, range_end, timezone_label = resolve_range(args)
    except ValueError as exc:
        p.error(str(exc))
    log_cmd = build_log_cmd(args, since, until)

    authors = args.author or []
    show_body = not args.no_body

    lines: list[str] = ["# Git 提交采集结果", ""]
    lines.append(f"- **时间范围**：{range_label}")
    if range_start is not None and range_end is not None:
        lines.append(
            f"- **精确边界**：[{range_start.isoformat(timespec='seconds')}, "
            f"{range_end.isoformat(timespec='seconds')})"
        )
    lines.append(f"- **时区**：{timezone_label}")
    lines.append(f"- **作者过滤**：{('、'.join(authors)) if authors else '全部作者'}")
    lines.append(f"- **分支范围**：{'仅当前分支' if args.no_all else '所有分支 (--all)'}")
    lines.append(f"- **合并提交**：{'包含' if args.merges else '已排除'}")
    lines.append("")

    total_commits = total_added = total_deleted = 0
    valid_repos = 0
    skipped: list[str] = []
    failed: list[str] = []
    collected = 0

    for repo in args.repos:
        repo_disp = repo
        expanded = os.path.expanduser(repo)
        if not is_git_repo(expanded):
            skipped.append(repo_disp)
            lines += [f"## ⚠️ 跳过：{repo_disp}", "", "不是一个有效的 Git 仓库。", ""]
            continue

        valid_repos += 1
        name, branch = repo_meta(expanded)
        result = run_git(expanded, log_cmd)
        if result.returncode != 0:
            failed.append(repo_disp)
            lines += [
                f"## ⚠️ {name}  （{repo_disp}）",
                "",
                f"git log 执行失败：{result.stderr.strip() or '未知错误'}",
                "",
            ]
            continue

        collected += 1
        commits = keep_in_half_open_range(parse_commits(result.stdout), range_start, range_end)
        r_added = sum(c["added"] for c in commits)
        r_deleted = sum(c["deleted"] for c in commits)
        total_commits += len(commits)
        total_added += r_added
        total_deleted += r_deleted

        lines += [
            f"## 📁 {name}  （{repo_disp}）",
            "",
            f"- 分支：`{branch}`",
            f"- 本范围内提交：**{len(commits)}** 个 ｜ 改动：+{r_added} / −{r_deleted}",
            "",
        ]
        if not commits:
            lines += ["_该范围内没有匹配的提交。_", ""]
            continue
        for c in commits:
            lines += render_commit(c, show_body, args.files)
            lines.append("")

    # 合计
    lines += ["---", "", "## 合计", ""]
    lines.append(f"- 有效仓库：{valid_repos} 个" + (f"（跳过 {len(skipped)} 个）" if skipped else ""))
    lines.append(f"- 采集状态：{'incomplete' if skipped or failed else 'complete'}；成功 {collected} 仓，失败 {len(failed)} 仓，跳过 {len(skipped)} 仓；以下合计仅覆盖成功仓库。")
    lines.append(f"- 提交总数：**{total_commits}** 个")
    lines.append(f"- 改动总量：+{total_added} / −{total_deleted}")
    lines.append("")

    if total_commits == 0 and collected > 0:
        lines += [
            "> ⚠️ **在指定的时间范围与作者条件下，未找到任何提交记录。**",
            "> 请确认：仓库路径是否正确、作者名/邮箱是否拼对、日期范围是否合适。",
            "> 0 个提交只表示 Git 采集结果，不等于当天没有其他工作；未提交改动、设计、QA、验收和沟通应另行取证。",
            "",
        ]

    sys.stdout.write("\n".join(lines))
    sys.stdout.write("\n")
    # 覆盖不完整时返回 1；stdout 保留成功仓库的部分结果。
    return 1 if valid_repos == 0 or failed or skipped else 0


if __name__ == "__main__":
    sys.exit(main())
