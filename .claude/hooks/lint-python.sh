#!/usr/bin/env bash
file=$(jq -r '.tool_response.filePath // .tool_input.file_path // empty')
case "$file" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0
cd "$(dirname "$0")/../.." || exit 0

uv run --quiet ruff check --fix --quiet "$file" >/dev/null 2>&1
uv run --quiet ruff format --quiet "$file" >/dev/null 2>&1
ruff_out=$(uv run --quiet ruff check --output-format concise "$file" 2>&1)
ruff_rc=$?
pyright_out=$(uv run --quiet pyright "$file" 2>&1)
pyright_rc=$?

if [ $ruff_rc -ne 0 ] || [ $pyright_rc -ne 0 ]; then
  {
    [ $ruff_rc -ne 0 ] && printf 'ruff:\n%s\n' "$ruff_out"
    [ $pyright_rc -ne 0 ] && printf 'pyright (strict):\n%s\n' "$pyright_out"
    echo "Fix these before continuing."
  } >&2
  exit 2
fi
