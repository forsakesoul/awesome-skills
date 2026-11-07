#!/usr/bin/env python3
"""Build docs/index.html (GitHub Pages) from the README skill tables.

The README tables are the single source of truth: add a skill there and rerun this script.
`--check` exits non-zero when docs/index.html is out of date instead of writing it.
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/index.html"
REPO = "https://github.com/forsakesoul/awesome-skills"
INSTALL = "npx skills add forsakesoul/awesome-skills"

CATEGORY = {"Media": "媒体", "Workflow": "工作流", "Productivity": "效率", "Knowledge": "知识"}

T = {
    "en": dict(
        crumb="AI agent skills · Claude Code · Codex",
        h1a="Curated agent skills,", h1b="ready to install", h1c=".",
        lead="Original and collected skills for AI coding agents. Each one is a folder with a SKILL.md; the agent reads its description and invokes it when your request matches.",
        cta_install="Install", cta_browse="Browse skills",
        steps_h="Install in three steps",
        s1="Install every skill for all your agents (user level, available in every project):",
        s2="Or pick one skill and one agent, non-interactively:",
        s3="Start a new agent session so it picks up the new skills. Update or remove them later with <code>npx skills update -g</code> / <code>npx skills remove &lt;name&gt; -g</code>.",
        catalog_h="Skills", copy_one="copy install", source="Source ↗",
        what_h="What's a skill?",
        what_p="A skill is a directory with a <code>SKILL.md</code>: YAML frontmatter with a <code>name</code> and a <code>description</code>, plus optional scripts and references. The description tells the agent when to reach for it, so you just ask in your own words.",
        contrib_h="Contributing",
        contrib_p="One skill per top-level directory, a portable <code>SKILL.md</code>, a row in the README table, and a clean-checkout smoke test. Collected skills keep their original license and attribution.",
        footer="MIT License · Skills authored by others keep their original terms",
        copy="Copy", copied="Copied", count="{n} skills"),
    "zh": dict(
        crumb="AI agent skills · Claude Code · Codex",
        h1a="精选的 agent skill，", h1b="装上就能用", h1c="。",
        lead="自制与社区收录的 AI 编码 agent skill。每个 skill 是一个带 SKILL.md 的目录，agent 读它的描述，在你的需求匹配时自动调用。",
        cta_install="安装", cta_browse="浏览 skill",
        steps_h="三步装好",
        s1="为所有 agent 安装全部 skill（用户级，所有项目可用）：",
        s2="或者只装某一个 skill 到指定 agent，免交互：",
        s3="新开一个 agent 会话，让它加载新的 skill。之后用 <code>npx skills update -g</code> 更新、<code>npx skills remove &lt;name&gt; -g</code> 移除。",
        catalog_h="Skill 列表", copy_one="复制安装命令", source="源码 ↗",
        what_h="什么是 skill？",
        what_p="skill 是一个带 <code>SKILL.md</code> 的目录：YAML 前置元数据里写 <code>name</code> 和 <code>description</code>，可附带脚本和参考资料。description 告诉 agent 什么时候该用它，你只需用自己的话提需求。",
        contrib_h="参与贡献",
        contrib_p="每个 skill 一个顶层目录，SKILL.md 路径可移植，在 README 表格里登记一行，并从干净的检出跑通冒烟测试。收录他人的 skill 保留原许可与署名。",
        footer="MIT 许可证 · 收录的 skill 遵循其原作者的许可",
        copy="复制", copied="已复制", count="{n} 个 skill"),
}


def skills_from_readme():
    """[(category, [(name, description_markdown)])] in README order."""
    text = (ROOT / "README.md").read_text()
    body = text.split("## Skills in this repo", 1)[1].split("\n## ", 1)[0]
    cats = []
    for block in re.split(r"^### ", body, flags=re.M)[1:]:
        title, rest = block.split("\n", 1)
        rows = re.findall(r"^\| \[`([^`]+)`\]\(\./[^)]+\) \| (.+?) \|\s*$", rest, flags=re.M)
        if rows:
            cats.append((title.strip(), rows))
    return cats


def inline_md(text):
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)


def term(label, body, t):
    return (f'<div class="term"><div class="bar"><i></i><i></i><i></i><span>{label}</span>'
            f'<button type="button" class="cp">{t["copy"]}</button></div><pre>{html.escape(body)}</pre></div>')


def section(lang, cats):
    t = T[lang]
    n = sum(len(rows) for _, rows in cats)
    catalog = []
    for cat, rows in cats:
        cards = "".join(
            f'<div class="card"><p class="name"><a href="{REPO}/tree/main/{name}">{name}</a></p>'
            f'<p class="desc">{inline_md(desc)}</p><div class="row">'
            f'<button type="button" class="chip" data-copy="{INSTALL} -g --skill {name}">{t["copy_one"]}</button>'
            f'<a class="src" href="{REPO}/tree/main/{name}">{t["source"]}</a></div></div>'
            for name, desc in rows)
        title = cat if lang == "en" else CATEGORY.get(cat, cat)
        catalog.append(f'<div class="cat"><h2>{title}<span class="count">{len(rows)}</span></h2><div class="cards">{cards}</div></div>')
    return f"""
<div data-l="{lang}">
  <div class="hero">
    <p class="crumb">{t['crumb']}</p>
    <h1>{t['h1a']}<br><span class="hi">{t['h1b']}</span>{t['h1c']}</h1>
    <p class="lead">{t['lead']}</p>
    <div class="ctas"><a class="btn primary" href="#install-{lang}">{t['cta_install']}</a><a class="btn" href="#skills-{lang}">{t['cta_browse']} · {t['count'].format(n=n)}</a></div>
  </div>
  <section id="install-{lang}">
    <h2>{t['steps_h']}</h2>
    <ol class="steps">
      <li><span class="num">1</span><div><p>{t['s1']}</p>{term('bash', INSTALL + ' -g', t)}</div></li>
      <li><span class="num">2</span><div><p>{t['s2']}</p>{term('bash', INSTALL + ' -g --skill video-compress --agent codex -y', t)}</div></li>
      <li><span class="num">3</span><div><p>{t['s3']}</p></div></li>
    </ol>
  </section>
  <section id="skills-{lang}">
    <h2>{t['catalog_h']}</h2>
    {''.join(catalog)}
  </section>
  <section class="two">
    <div class="card why"><h2>{t['what_h']}</h2><p>{t['what_p']}</p></div>
    <div><h2>{t['contrib_h']}</h2><p>{t['contrib_p']}</p></div>
  </section>
  <footer>{t['footer']} · <a href="{REPO}">github.com/forsakesoul/awesome-skills</a></footer>
</div>"""


def page():
    cats = skills_from_readme()
    css = (ROOT / "tools/pages.css").read_text()
    copy_txt = json.dumps({l: [T[l]["copy"], T[l]["copied"]] for l in T}, ensure_ascii=False)
    fonts = "family=ZCOOL+KuaiLe&family=Permanent+Marker&family=Noto+Sans+SC:wght@400;700&family=JetBrains+Mono:wght@400;700"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>awesome-skills — curated AI agent skills</title>
<meta name="description" content="Original and collected skills for AI coding agents, installable with npx skills.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{fonts}&display=swap">
<style>{css}</style>
</head>
<body>
<div class="top"><div class="in">
  <a class="brand" href="#">awesome-<b>skills</b></a>
  <nav><a href="{REPO}">GitHub</a>
    <span class="langs" role="group" aria-label="Language"><button type="button" data-set="en">EN</button><button type="button" data-set="zh">中</button></span>
  </nav>
</div></div>
<main>{section('en', cats)}{section('zh', cats)}</main>
<script>
const COPY = {copy_txt}, langs = ["en", "zh"];
let cur = "en";
function pick(l, keep) {{
  if (!langs.includes(l)) l = "en";
  cur = l;
  document.documentElement.lang = l === "zh" ? "zh-CN" : l;
  document.querySelectorAll("[data-l]").forEach((e) => e.classList.toggle("on", e.dataset.l === l));
  document.querySelectorAll(".langs button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.set === l)));
  if (!keep) history.replaceState(null, "", "#" + l);
}}
async function copy(btn, text, label) {{
  await navigator.clipboard.writeText(text);
  btn.textContent = COPY[cur][1];
  setTimeout(() => (btn.textContent = label), 1400);
}}
document.querySelectorAll(".langs button").forEach((b) => b.addEventListener("click", () => pick(b.dataset.set)));
document.querySelectorAll(".cp").forEach((b) => b.addEventListener("click", () => copy(b, b.closest(".term").querySelector("pre").textContent, COPY[cur][0])));
document.querySelectorAll(".chip").forEach((b) => {{ const label = b.textContent; b.addEventListener("click", () => copy(b, b.dataset.copy, label)); }});
// A fragment is a language code (#zh) or ends with one (#install-zh): show that language and keep the fragment.
function langOf(h) {{ const m = h.match(/(?:^|-)([a-z]{{2}})$/); return m && langs.includes(m[1]) ? m[1] : null; }}
addEventListener("hashchange", () => {{ const h = location.hash.slice(1), l = langOf(h); if (l) pick(l, h !== l); }});
const h = location.hash.slice(1), hl = langOf(h);
pick(hl || (navigator.language || "en").slice(0, 2).toLowerCase(), !!hl && h !== hl);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    html_text = page()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != html_text:
            sys.exit("docs/index.html is out of date; run python3 tools/build_pages.py")
        print("docs/index.html is up to date")
    else:
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(html_text)
        print(f"wrote {OUT.relative_to(ROOT)}")
