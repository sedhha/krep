#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATES="$REPO_ROOT/docs/specs/_templates"
SPECS_DIR="$REPO_ROOT/docs/specs"
PLANS_DIR="$REPO_ROOT/docs/plans"
ADR_DIR="$REPO_ROOT/docs/adr"
INDEX="$SPECS_DIR/README.md"
INDEX_MARKER="SPEC_INDEX_END"

BOLD=$'\033[1m'; DIM=$'\033[2m'; CYAN=$'\033[36m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
if [ ! -t 1 ]; then BOLD=""; DIM=""; CYAN=""; GREEN=""; YELLOW=""; RESET=""; fi

die() { printf '%serror:%s %s\n' "$YELLOW" "$RESET" "$1" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage: scripts/spec_init.sh <slug> [--level N] [--title "Human Title"]

Scaffolds the documents a piece of work needs, at the ceremony level it earns.
See docs/WORKFLOW.md for how to pick a level.

  --level 0   trivial      no artifacts; prints the workflow and exits
  --level 1   task         docs/plans/YYYY-MM-DD-<slug>.md
  --level 2   feature      docs/specs/NNN-<slug>/{spec,design,plan,notes}.md   (default)
  --level 3   system       level 2, plus a numbered ADR stub

Examples
  scripts/spec_init.sh agent-registry
  scripts/spec_init.sh tool-gateway --level 3
  scripts/spec_init.sh add-request-id --level 1 --title "Add requestId to error logs"
  make spec name=agent-registry level=2
USAGE
}

SLUG=""; LEVEL="2"; TITLE=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --level) [ $# -ge 2 ] || die "--level needs a value"; LEVEL="$2"; shift 2 ;;
    --level=*) LEVEL="${1#*=}"; shift ;;
    --title) [ $# -ge 2 ] || die "--title needs a value"; TITLE="$2"; shift 2 ;;
    --title=*) TITLE="${1#*=}"; shift ;;
    -*) die "unknown option: $1" ;;
    *) [ -z "$SLUG" ] || die "unexpected argument: $1"; SLUG="$1"; shift ;;
  esac
done

[ -n "$SLUG" ] || { usage >&2; exit 1; }
case "$LEVEL" in 0|1|2|3) ;; *) die "level must be 0, 1, 2, or 3 (got '$LEVEL')" ;; esac
printf '%s' "$SLUG" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$' \
  || die "slug must be lower-case kebab-case, e.g. agent-registry (got '$SLUG')"

DATE="$(date +%F)"
AUTHOR="$(git -C "$REPO_ROOT" config user.name 2>/dev/null || true)"
[ -n "$AUTHOR" ] || AUTHOR="unknown"

if [ -z "$TITLE" ]; then
  TITLE="$(printf '%s' "$SLUG" | tr '-' ' ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)}1')"
fi

render() {
  local template="$1" dest="$2" number="$3" adr_number="$4" body
  [ -f "$template" ] || die "missing template: $template"
  [ -e "$dest" ] && die "refusing to overwrite existing file: ${dest#"$REPO_ROOT"/}"
  body="$(cat "$template")"
  body="${body//\{\{NUMBER\}\}/$number}"
  body="${body//\{\{ADR_NUMBER\}\}/$adr_number}"
  body="${body//\{\{SLUG\}\}/$SLUG}"
  body="${body//\{\{TITLE\}\}/$TITLE}"
  body="${body//\{\{DATE\}\}/$DATE}"
  body="${body//\{\{AUTHOR\}\}/$AUTHOR}"
  body="${body//\{\{LEVEL\}\}/$LEVEL}"
  printf '%s\n' "$body" > "$dest"
  printf '  %screated%s %s\n' "$GREEN" "$RESET" "${dest#"$REPO_ROOT"/}"
}

next_spec_number() {
  local highest=0 n
  for d in "$SPECS_DIR"/[0-9][0-9][0-9]-*; do
    [ -d "$d" ] || continue
    n="$(basename "$d")"; n="${n%%-*}"; n=$((10#$n))
    [ "$n" -gt "$highest" ] && highest="$n"
  done
  printf '%03d' "$((highest + 1))"
}

next_adr_number() {
  local highest=0 n
  for f in "$ADR_DIR"/[0-9][0-9][0-9][0-9]-*.md; do
    [ -f "$f" ] || continue
    n="$(basename "$f")"; n="${n%%-*}"; n=$((10#$n))
    [ "$n" -gt "$highest" ] && highest="$n"
  done
  printf '%04d' "$((highest + 1))"
}

append_index_row() {
  local number="$1" dir="$2" row tmp
  [ -f "$INDEX" ] || return 0
  row="| $number | $TITLE | Draft | [spec]($dir/spec.md) | [design]($dir/design.md) | [plan]($dir/plan.md) |"
  tmp="$(mktemp)"
  awk -v row="$row" -v marker="$INDEX_MARKER" '
    index($0, marker) && !done { print row; done = 1 }
    { print }
  ' "$INDEX" > "$tmp"
  mv "$tmp" "$INDEX"
  printf '  %supdated%s %s\n' "$GREEN" "$RESET" "${INDEX#"$REPO_ROOT"/}"
}

step() { printf '\n  %s%s.%s %s%-8s%s %s\n' "$BOLD" "$1" "$RESET" "$CYAN" "$2" "$RESET" "$3"; }
detail() { printf '              %s%s%s\n' "$DIM" "$1" "$RESET"; }
prompt_line() { printf '              %s> %s%s\n' "$DIM" "$1" "$RESET"; }

if [ "$LEVEL" = "0" ]; then
  printf '\n%sLevel 0 — no documents needed.%s\n' "$BOLD" "$RESET"
  detail "State the diff in one sentence, make the change, run make verify, read the diff."
  detail "If you cannot state it in one sentence, rerun at --level 1."
  printf '\n'
  exit 0
fi

printf '\n'

if [ "$LEVEL" = "1" ]; then
  mkdir -p "$PLANS_DIR"
  DEST="$PLANS_DIR/$DATE-$SLUG.md"
  render "$TEMPLATES/task-plan.md" "$DEST" "" ""
  REL="${DEST#"$REPO_ROOT"/}"
  printf '\n%sLevel 1 — %s%s\n' "$BOLD" "$TITLE" "$RESET"
  step 1 "YOU" "Edit $REL"
  detail "Fill Change and Acceptance Criteria. Leave Approach for the agent."
  step 2 "AGENT" "Plan and implement in one session"
  prompt_line "Read $REL and docs/WORKFLOW.md."
  prompt_line "This is Level 1. Explore the existing flow first, fill in Approach"
  prompt_line "and Tests, then implement test-first. Run make verify."
  step 3 "REVIEW" "Fresh session, ideally the other tool"
  prompt_line "Review the diff on this branch against $REL."
  prompt_line "Check the acceptance criteria only. Do not restate the implementation."
  step 4 "YOU" "Read the diff and ship"
  printf '\n'
  exit 0
fi

NUMBER="$(next_spec_number)"
DIR_NAME="$NUMBER-$SLUG"
DIR="$SPECS_DIR/$DIR_NAME"
[ -e "$DIR" ] && die "refusing to overwrite existing spec folder: ${DIR#"$REPO_ROOT"/}"
for existing in "$SPECS_DIR"/[0-9][0-9][0-9]-"$SLUG"; do
  [ -d "$existing" ] && die "a spec for '$SLUG' already exists: ${existing#"$REPO_ROOT"/}"
done

mkdir -p "$DIR"
render "$TEMPLATES/spec.md"   "$DIR/spec.md"   "$NUMBER" ""
render "$TEMPLATES/design.md" "$DIR/design.md" "$NUMBER" ""
render "$TEMPLATES/plan.md"   "$DIR/plan.md"   "$NUMBER" ""
render "$TEMPLATES/notes.md"  "$DIR/notes.md"  "$NUMBER" ""

ADR_REL=""
if [ "$LEVEL" = "3" ]; then
  mkdir -p "$ADR_DIR"
  ADR_NUMBER="$(next_adr_number)"
  ADR_DEST="$ADR_DIR/$ADR_NUMBER-$SLUG.md"
  render "$TEMPLATES/adr.md" "$ADR_DEST" "$NUMBER" "$ADR_NUMBER"
  ADR_REL="${ADR_DEST#"$REPO_ROOT"/}"
fi

append_index_row "$NUMBER" "$DIR_NAME"

REL="docs/specs/$DIR_NAME"
printf '\n%sLevel %s — %s (%s)%s\n' "$BOLD" "$LEVEL" "$TITLE" "$NUMBER" "$RESET"
printf '%sEach numbered step below is a fresh session. Carry the files forward, never the chat.%s\n' "$DIM" "$RESET"

step 1 "YOU" "Edit $REL/spec.md"
detail "Fill Problem, Goals, Non-Goals, Acceptance Criteria, Constraints."
detail "Write no design decisions. Number the criteria; everything downstream cites them."

step 2 "CLAUDE" "claude"
prompt_line "Read $REL/spec.md, docs/WORKFLOW.md, docs/architecture/overview.md,"
prompt_line "and docs/product/agent-platform-v1.md."
prompt_line "Interview me on anything ambiguous, one question at a time, then write"
prompt_line "$REL/design.md. Write no code."

step 3 "CODEX" "codex"
prompt_line "Read $REL/spec.md, $REL/design.md, docs/WORKFLOW.md, and"
prompt_line "docs/architecture/overview.md."
prompt_line "Adversarially review the design: unstated assumptions, missing edge cases,"
prompt_line "violated layer-graph rules, over-engineering, criteria the design does not"
prompt_line "actually satisfy. Write findings to $REL/notes.md. Write no code."

step 4 "YOU" "Resolve $REL/notes.md, then accept the design"
detail "Fix findings by editing spec.md or design.md, not by arguing in notes.md."
detail "Set design.md Status to Accepted. This is the architectural commitment gate."
if [ "$LEVEL" = "3" ]; then
  detail "Level 3: also fill and accept $ADR_REL, and write the migration/rollback note."
fi

step 5 "CLAUDE" "claude"
prompt_line "Read $REL/spec.md and $REL/design.md. The design is accepted."
prompt_line "Write $REL/plan.md: ordered slices, each independently verifiable, each"
prompt_line "with its tests named first and its verify command. Write no code."

step 6 "BUILD" "one fresh session per slice"
prompt_line "Read $REL/plan.md, spec.md, design.md. Implement slice N only."
prompt_line "Tests first. Then make verify. Stop at the end of the slice."

step 7 "CODEX" "codex — fresh context"
prompt_line "Review the diff against $REL/spec.md acceptance criteria and"
prompt_line "docs/architecture/overview.md. Cite criterion numbers."

step 8 "YOU" "Read the diff. Update the Index status in docs/specs/README.md. Ship."
printf '\n'
