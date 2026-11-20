#!/usr/bin/env python3
"""Prints only the learnings whose Tags line matches, so an agent loads its lens, not the whole file.

Usage: learnings.py --lens <lens>      entries with the tags of a lens in flow.json (what agents call)
       learnings.py <tag> [tag...]     entries with any of the tags
       learnings.py --untagged         entries nobody will ever load (fix them)
       learnings.py --tags             the tags in use, with counts
The learnings file comes from .claude/flow.json ("learnings").
"""
import collections
import json
import os
import re
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def entries(path):
    text = open(path).read()
    # Entries start at "## <slug>" outside fenced blocks (the template inside ``` is skipped).
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for block in re.split(r"(?m)^(?=## )", text):
        if not block.startswith("## "):
            continue
        m = re.search(r"^- \*\*Tags\*\*:\s*(.+)$", block, re.M)
        tags = {t.strip().lower() for t in m.group(1).split(",")} if m else set()
        yield block.rstrip() + "\n", tags


def main(args):
    with open(os.path.join(ROOT, ".claude", "flow.json")) as f:
        flow = json.load(f)
    path = os.path.join(ROOT, flow["learnings"])
    if not args:
        print(__doc__)
        return 1
    all_entries = list(entries(path))
    if args == ["--tags"]:
        for tag, n in collections.Counter(t for _, ts in all_entries for t in ts).most_common():
            print(f"{n:3} {tag}")
        return 0
    if args == ["--untagged"]:
        bad = [b.splitlines()[0] for b, ts in all_entries if not ts]
        print("\n".join(bad))
        return 1 if bad else 0
    if args[0] == "--lens":
        lens = (flow.get("lenses") or {}).get(args[1] if len(args) > 1 else "")
        if lens is None:
            sys.exit(f"unknown lens; flow.json has: {', '.join(flow.get('lenses') or {})}")
        args = lens["tags"]
    wanted = {a.lower() for a in args}
    for block, tags in all_entries:
        if tags & wanted:
            print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
