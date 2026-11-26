#!/usr/bin/env bash
# Installs Forecrew into a repository.
#
# Usage: install.sh <target-repo> [--tools claude,cursor,codex,copilot] [--replace]   (default: claude,cursor,codex)
#
# Kit files (.claude/kit/) are replaced on every run. Everything a project adapts (the seven
# agents, flow.json, product-sources.md, LEARNINGS.md, DECISIONS.md, TASKS.md, the task skill, the commands) is
# created only when missing. When yours differs it is kept, unless --replace: then yours is
# moved to .agent-flow-backup/<time>/ first. The kit's originals stay in .claude/kit/originals/
# for comparing and merging. Hooks are merged into .claude/settings.json once. At the end it
# lists the AI configuration already in the repository; /flow-setup existing handles it.
set -euo pipefail

target=""; tools="claude,cursor,codex"; replace=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tools) tools="${2:?--tools needs a list}"; shift 2 ;;
    --replace) replace=1; shift ;;
    -h|--help) sed -n 2,11p "$0"; exit 0 ;;
    *) target="$1"; shift ;;
  esac
done
[ -n "$target" ] || { sed -n 2,11p "$0"; exit 1; }
target="$(cd "$target" && pwd)"
src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/template/.claude"
dst="$target/.claude"

rm -rf "$dst/kit" && mkdir -p "$dst" && cp -R "$src/kit" "$dst/kit"
find "$dst/kit" -name __pycache__ -prune -exec rm -rf {} +
git -C "$src" describe --always --dirty 2>/dev/null > "$dst/kit/VERSION" || echo unknown > "$dst/kit/VERSION"
# The license and the credit travel with every install (Apache-2.0, section 4(d)).
cp "$src/../../LICENSE" "$src/../../NOTICE" "$dst/kit/"
backup="$target/.agent-flow-backup/$(date +%Y%m%d-%H%M%S)"

copy_once() {  # <relative path under .claude>
  local from="$src/$1" to="$dst/$1"
  mkdir -p "$(dirname "$to")" "$(dirname "$dst/kit/originals/$1")"
  cp "$from" "$dst/kit/originals/$1"
  if [ ! -e "$to" ]; then cp "$from" "$to"; echo "added    .claude/$1"
  elif cmp -s "$from" "$to"; then echo "same     .claude/$1"
  elif [ -n "$replace" ]; then
    mkdir -p "$(dirname "$backup/.claude/$1")" && mv "$to" "$backup/.claude/$1" && cp "$from" "$to"
    echo "replaced .claude/$1 (yours: ${backup#"$target"/}/.claude/$1)"
  else echo "kept     .claude/$1 (yours differs; kit's version: .claude/kit/originals/$1)"; fi
}
(cd "$src" && find agents commands skills -type f; echo flow.json; echo product-sources.md; echo LEARNINGS.md; echo DECISIONS.md; echo TASKS.md) |
  while read -r f; do copy_once "$f"; done

if [[ ",$tools," == *",claude,"* ]]; then
  # Per (event, matcher), so a re-install adds what a newer kit wires next to the old entries.
  python3 "$dst/kit/scripts/wire_hooks.py" "$dst/settings.json"
fi

others=$(echo "$tools" | tr ',' '\n' | grep -v '^claude$' | paste -sd, - || true)
[ -z "$others" ] || CLAUDE_PROJECT_DIR="$target" python3 "$dst/kit/scripts/export.py" --tools "$others"

touch "$target/.gitignore"
grep -qxF '/.work/' "$target/.gitignore" || printf '\n# Forecrew work directories: local evidence, never versioned\n/.work/\n' >> "$target/.gitignore"
grep -qxF '/.agent-flow-backup/' "$target/.gitignore" || printf '/.agent-flow-backup/\n' >> "$target/.gitignore"

python3 "$dst/kit/test_kit.py"
echo
CLAUDE_PROJECT_DIR="$target" python3 "$dst/kit/scripts/detect.py"
cat <<EOF

Installed Forecrew $(cat "$dst/kit/VERSION") in $target (tools: $tools). Next, inside the repository:
  0. If configuration was listed above: /flow-setup existing decides, item by item, what to
     keep, merge into the kit, replace or remove (always with a backup and your ok).
  1. Configure it by interview: /flow-setup in Claude Code or Cursor; in Codex, ask it to
     "follow .claude/commands/flow-setup.md". It asks for your task tracker, where product
     documentation lives, what each reviewer reads, and how the project builds and tests.
  2. Commit .claude/, .cursor/, AGENTS.md and .gitignore.
  3. First task: /task <what you want done> (or a ticket id). Dashboard: bash .claude/kit/scripts/work.sh ui start
EOF
