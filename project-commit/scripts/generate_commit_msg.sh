#!/usr/bin/env bash
# generate_commit_msg.sh - 根据 diff 生成 Conventional Commit message
#
# 用法:
#   bash generate_commit_msg.sh /path/to/diff.txt [项目名] [项目提交规范] [通用提交规则] [近期commits] [当前分支名]
#
# 参数:
#   $1: diff 文件路径（或 stdin）
#   $2: 项目名（可选）
#   $3: 项目提交规范（可选，来自 projects.json 的 commit_convention）
#   $4: 通用提交规则（可选，来自 projects.json 的 commit_rules）
#   $5: 近期 commits（可选，来自 git log，用于参考风格）
#   $6: 当前分支名（可选，用于推导 scope）
#
# 环境变量:
#   ANTHROPIC_AUTH_TOKEN       - Anthropic API Key
#   ANTHROPIC_BASE_URL          - API 地址（可选，默认 https://api.anthropic.com）
#   ANTHROPIC_DEFAULT_SONNET_MODEL - 模型名（可选，默认 claude-sonnet-4-20250514）
#   HEADER_MAX_LENGTH           - header 最大字符数（可选，默认 100）
#   COMMIT_MSG_MIN_LENGTH       - subject 最少字符数（可选，默认 50）
#   COMMIT_MSG_MAX_LENGTH       - subject 最多字符数（可选，默认 300）
#   CHANGED_FILES_COUNT         - 改动文件数（可选，用于缩放 message 长度）
#   CHANGED_LINES_COUNT         - 改动代码行数（可选，用于缩放 message 长度）

set -uo pipefail

DIFF_FILE="${1:-}"
PROJECT_NAME="${2:-}"
PROJECT_CONVENTION="${3:-}"
COMMIT_RULES="${4:-}"
RECENT_COMMITS="${5:-}"
CURRENT_BRANCH="${6:-}"

# 读取 diff
if [ -n "$DIFF_FILE" ] && [ -f "$DIFF_FILE" ]; then
  DIFF_TEXT=$(cat "$DIFF_FILE")
elif [ -n "${1:-}" ] && [ ! -f "$DIFF_FILE" ]; then
  DIFF_TEXT="$1"
else
  DIFF_TEXT=$(cat)
fi

if [ -z "$DIFF_TEXT" ]; then
  echo "chore: no functional change"
  exit 0
fi

# 截断超长 diff
if [ ${#DIFF_TEXT} -gt 8000 ]; then
  DIFF_TEXT="${DIFF_TEXT:0:8000}"
  DIFF_TEXT="${DIFF_TEXT}"$'\n'"...(diff truncated)"
fi

# --- 读取环境变量配置 ---
HEADER_MAX=${HEADER_MAX_LENGTH:-100}
MSG_MIN=${COMMIT_MSG_MIN_LENGTH:-50}
MSG_MAX=${COMMIT_MSG_MAX_LENGTH:-300}
CHANGED_FILES=${CHANGED_FILES_COUNT:-0}
CHANGED_LINES=${CHANGED_LINES_COUNT:-0}

# --- 根据改动规模计算建议 message 长度 ---
# 规模越大，建议长度越接近 MSG_MAX
suggest_msg_length() {
  local files=$1
  local lines=$2
  local min=$3
  local max=$4

  # 计算规模分数 (0~1)
  # 文件数贡献: 0~1, 饱和于 15 个文件
  local f_score=$(python3 -c "print(min(float($files) / 15.0, 1.0))")
  # 行数贡献: 0~1, 饱和于 500 行
  local l_score=$(python3 -c "print(min(float($lines) / 500.0, 1.0))")
  # 综合分数: 取两者较大值（任一方面规模大就拉高）
  local score=$(python3 -c "print(max($f_score, $l_score))")

  # 根据分数在 min~max 之间插值
  python3 -c "print(int($min + ($max - $min) * $score))"
}

SUGGESTED_MSG_LEN=$(suggest_msg_length "$CHANGED_FILES" "$CHANGED_LINES" "$MSG_MIN" "$MSG_MAX")

# 从分支名推导建议 scope
SUGGESTED_SCOPE=""
if [ -n "$CURRENT_BRANCH" ]; then
  BRANCH_SUFFIX=$(echo "$CURRENT_BRANCH" | sed 's|.*/||')
  if [ -n "$BRANCH_SUFFIX" ] && [ "$BRANCH_SUFFIX" != "$CURRENT_BRANCH" ]; then
    SUGGESTED_SCOPE="$BRANCH_SUFFIX"
  fi
fi

# --- 方式1: Claude Code API ---
if [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  BASE_URL="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"
  MODEL="${ANTHROPIC_DEFAULT_SONNET_MODEL:-claude-sonnet-4-20250514}"

  EXTRA_TEXT=""
  if [ -n "$PROJECT_CONVENTION" ]; then
    EXTRA_TEXT="${EXTRA_TEXT}"$'\n'"该项目提交规范："$'\n'"${PROJECT_CONVENTION}"
  fi
  if [ -n "$COMMIT_RULES" ]; then
    EXTRA_TEXT="${EXTRA_TEXT}"$'\n'"额外提交规则："$'\n'"${COMMIT_RULES}"
  fi
  if [ -n "$RECENT_COMMITS" ]; then
    EXTRA_TEXT="${EXTRA_TEXT}"$'\n'"近期 commits（请参考其风格、术语和 scope 使用习惯）："$'\n'"${RECENT_COMMITS}"
  fi
  if [ -n "$SUGGESTED_SCOPE" ]; then
    EXTRA_TEXT="${EXTRA_TEXT}"$'\n'"当前分支名：${CURRENT_BRANCH}，建议 scope 使用：${SUGGESTED_SCOPE}"
  fi

  # 规模信息
  SCALE_HINT=""
  if [ "$CHANGED_FILES" -gt 0 ] || [ "$CHANGED_LINES" -gt 0 ]; then
    SCALE_HINT=$'\n'"本次改动规模：${CHANGED_FILES} 个文件，${CHANGED_LINES} 行代码变更。根据规模，commit message 主体建议 ${SUGGESTED_MSG_LEN} 个字符左右。"
  fi

  PROMPT="你是一个 Git 提交助手。根据以下 diff 内容，生成一条 Conventional Commits 格式的 commit message。

规则：
- 格式：type(scope): subject（scope 为可选，但跨项目同一主题时必须带且复用同一个 scope）
- type 只能是：feat / fix / chore / docs / style / refactor / test / perf / ci / build
- scope 优先使用建议值（若有），跨项目同一主题必须复用同一个 scope
- subject 用中文，必须描述实际改动点，不能只写\"update\"、\"merge\"、\"fix bug\"等空泛描述
- header（type(scope): subject 整行）不得超过 ${HEADER_MAX} 个字符
- **关键：commit message 长度应匹配改动规模**：
  - 改动小（≤3 文件，≤50 行）→ 简短，50-80 字即可
  - 改动中等（4-8 文件，50-200 行）→ 80-180 字，适当展开描述
  - 改动大（≥9 文件或 >200 行）→ 180-300 字，详细说明改了哪些模块、为什么改、影响范围
- 若描述超过 header 上限（${HEADER_MAX} 字符），使用短 header + body 格式：
  - header 控制在 ${HEADER_MAX} 字符内，概括核心变更
  - body 详细展开（header 与 body 之间空一行），body 整体不超过 ${MSG_MAX} 字符
- 只输出 commit message 本身，不要有任何解释、引号、markdown 或多余文字
- 如果 diff 为空或毫无意义，输出：chore: no functional change${EXTRA_TEXT}${SCALE_HINT}

Diff:
\`\`\`
${DIFF_TEXT}
\`\`\`"

  RESPONSE=$(curl -s -X POST "${BASE_URL}/v1/messages" \
    -H "x-api-key: ${ANTHROPIC_AUTH_TOKEN}" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d "{
      \"model\": \"${MODEL}\",
      \"max_tokens\": 500,
      \"messages\": [{\"role\": \"user\", \"content\": $(echo "${PROMPT}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}]
    }" 2>/dev/null || echo "")

  MSG=$(echo "$RESPONSE" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    for b in d.get('content',[]):
        if b.get('type')=='text':
            print(b['text'].strip())
            break
except: pass
" 2>/dev/null || echo "")

  # 校验：必须是 type: 或 type(scope): 格式，且 header 不超过最大长度
  if [ -n "$MSG" ] && echo "$MSG" | grep -qE '^(feat|fix|chore|docs|style|refactor|test|perf|ci|build)(\([^)]+\))?:'; then
    HEADER=$(echo "$MSG" | head -1)
    if [ ${#HEADER} -le $HEADER_MAX ]; then
      echo "$MSG"
      exit 0
    fi
  fi
fi

# --- 方式2: 基于规则本地生成 ---
# 分析 diff 判断类型
if echo "$DIFF_TEXT" | grep -q "^+.*TODO\|^+.*FIXME\|^+.*HACK"; then
  TYPE="fix"
elif echo "$DIFF_TEXT" | grep -q "test\|spec\.\|expect("; then
  TYPE="test"
elif echo "$DIFF_TEXT" | grep -q "^+.*export function\|^+.*export class\|^+.*export const\|^+.*export interface\|^+.*function.*{"; then
  TYPE="feat"
elif echo "$DIFF_TEXT" | grep -q "^-.*export function\|^-.*export class"; then
  TYPE="refactor"
elif echo "$DIFF_TEXT" | grep -q "package.json\|pnpm-lock\|yarn.lock\|Cargo.toml\|go.mod"; then
  TYPE="chore"
elif echo "$DIFF_TEXT" | grep -q "\.md\|\.MD\|README\|CHANGELOG"; then
  TYPE="docs"
elif echo "$DIFF_TEXT" | grep -q "style\|padding\|margin\|color\|font\|\.css\|\.scss"; then
  TYPE="style"
else
  TYPE="fix"
fi

# 使用建议 scope（从分支名推导）
SCOPE="$SUGGESTED_SCOPE"

# 生成 header，确保不超过最大长度
if [ -n "$SCOPE" ]; then
  BASE="${TYPE}(${SCOPE})"
else
  BASE="${TYPE}"
fi

# 剩下的长度留给 subject
MAX_SUBJECT=$(( HEADER_MAX - ${#BASE} - 2 ))  # 2 for ": "
SUBJECT="update ${PROJECT_NAME:-code}"

if [ ${#SUBJECT} -gt $MAX_SUBJECT ]; then
  SUBJECT="${SUBJECT:0:$(( MAX_SUBJECT - 3 ))}..."
fi

HEADER="${BASE}: ${SUBJECT}"

if [ ${#HEADER} -le $HEADER_MAX ]; then
  echo "$HEADER"
else
  # 兜底：不带 scope
  echo "${TYPE}: update ${PROJECT_NAME:-code}"
fi
