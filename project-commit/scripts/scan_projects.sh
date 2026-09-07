#!/usr/bin/env bash
# scan_projects.sh - 扫描配置项目的 git 状态
# 依赖: projects.json（同目录）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 优先读取 projects.json（本地私有无 git 追踪），回退到 projects.example.json（模板）
if [ -f "$SCRIPT_DIR/../projects.json" ]; then
  CONFIG_FILE="$SCRIPT_DIR/../projects.json"
elif [ -f "$SCRIPT_DIR/../projects.example.json" ]; then
  CONFIG_FILE="$SCRIPT_DIR/../projects.example.json"
  echo "⚠️  未找到 projects.json，使用模板 projects.example.json。"
  echo "   请复制 projects.example.json → projects.json 并填入实际项目路径"
else
  echo "❌ 找不到配置文件 projects.json 或 projects.example.json"
  exit 1
fi

# 用 python3 读取 JSON 配置
if [ ! -f "$CONFIG_FILE" ]; then
  echo "❌ 配置文件不存在: $CONFIG_FILE"
  exit 1
fi

# 解析参数
PROJECT_FILTER=""
DIFF_MODE=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --project)
      PROJECT_FILTER="$2"
      shift 2
      ;;
    --diff)
      DIFF_MODE=true
      shift
      ;;
    --verbose|-v)
      VERBOSE=true
      shift
      ;;
    *)
      echo "未知参数: $1"
      echo "用法: $0 [--project 项目名] [--diff] [--verbose]"
      exit 1
      ;;
  esac
done

# 用 python3 解析配置并扫描项目
python3 - "$CONFIG_FILE" "$PROJECT_FILTER" "$DIFF_MODE" "$VERBOSE" << 'PYEOF'
import json, sys, subprocess, os

config_file = sys.argv[1]
project_filter = sys.argv[2] if sys.argv[2] else None
diff_mode = sys.argv[3] == "true"
verbose = sys.argv[4] == "true"

with open(config_file) as f:
    config = json.load(f)

projects = [p for p in config["projects"] if not project_filter or p["name"] == project_filter]
if not projects:
    print(f"❌ 没有匹配的项目: {project_filter}")
    sys.exit(1)
scope_hint = config.get("default_scope_hint", "")

CHANGED = []
CLEAN = []
FAILED = []

for p in projects:
    name = p["name"]
    path = p["path"]

    if not os.path.isdir(path):
        FAILED.append(name)
        print(f"⚠️  项目目录不存在: {path}")
        continue

    os.chdir(path)

    # 检查是否有改动
    result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if result.returncode:
        FAILED.append(name)
        print(f"❌ {name}: git status 失败，状态未知")
        continue
    lines = [l for l in result.stdout.splitlines() if l.strip()]

    if not lines:
        CLEAN.append(name)
        continue

    CHANGED.append(name)

    # 获取分支名
    branch_result = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True)
    if branch_result.returncode:
        FAILED.append(name)
    branch = branch_result.stdout.strip() or "unknown"

    print(f"\n📂 {name}  ({branch})")
    print(f"   📁 {path}")

    if diff_mode:
        # 显示 diff
        diff_result = subprocess.run(["git", "diff", "--stat"], capture_output=True, text=True)
        if diff_result.returncode:
            FAILED.append(name)
        if diff_result.stdout.strip():
            print("   📝 已暂存 + 未暂存:")
            for line in diff_result.stdout.strip().splitlines():
                print(f"      {line}")
        # staged
        staged = subprocess.run(["git", "diff", "--cached", "--stat"], capture_output=True, text=True)
        if staged.returncode:
            FAILED.append(name)
        if staged.stdout.strip():
            print("   📦 Staged:")
            for line in staged.stdout.strip().splitlines():
                print(f"      {line}")
    else:
        # 只显示文件列表
        for line in lines:
            status = line[:2].strip()
            fname = line[3:].strip()
            if status == "M":  icon = "✏️ "
            elif status == "A": icon = "➕"
            elif status == "D": icon = "🗑️ "
            elif status == "R": icon = "🔄"
            elif "?" in status: icon = "❓"
            else: icon = "📄"
            print(f"   {icon} [{status}] {fname}")

if scope_hint and CHANGED:
    print(f"\n💡 {scope_hint}")

print(f"\n=== Summary ===")
print(f"有改动的项目: {len(CHANGED)} 个 → {' '.join(CHANGED) if CHANGED else '无'}")
print(f"干净的项目:   {len(CLEAN)} 个 → {' '.join(CLEAN) if CLEAN else '无'}")
print(f"扫描失败的项目: {len(set(FAILED))} 个 → {' '.join(sorted(set(FAILED))) if FAILED else '无'}")
sys.exit(1 if FAILED else 0)
PYEOF
