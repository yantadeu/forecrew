#!/usr/bin/env python3
"""A second opinion from another vendor's model: the review package of the current task, sent to
a CLI that is not Claude (Codex, Gemini or any command), its answer kept for the
second-opinion reviewer to verify.

Usage: second_opinion.py <root> <work_dir>        (work.sh second-opinion)

Reviewers of one model share its blind spots, clean context or not. This sends the purpose, the
contract and review.diff on stdin to the command, run from the repository root, and writes what
it answers to <work_dir>/<ID>/second-opinion.md, masked like every file the kit writes.

The command: "second_opinion" in flow.json, {"command": "...", "timeout": 900}; without it, the
first of these on PATH:
  codex   codex exec --sandbox read-only -      (reads the prompt from stdin, cannot write)
  gemini  gemini -p "<ask>"                      (stdin is appended to the prompt)
The change leaves the machine for that vendor: configure it only where that is allowed.
Exit codes: 0 answered, 1 the command failed, 2 nothing to send or no command.
"""
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("kit_flow_so", os.path.join(KIT, "hooks", "flow.py"))
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

DIFF_MAX = 400_000
ASK = ("Review the change below for defects. You may read the repository; do not change any file. "
       "Answer only with findings, one per line: `- [critical|important|minor] file:line: what fails, "
       "and the input or state that makes it fail`. Nothing serious: answer `No findings.`")
AUTO = [("codex", "codex exec --sandbox read-only -"),
        ("gemini", "gemini -p " + shlex.quote("Follow the instructions at the start of the input."))]


def command(flow):
    cfg = flow.get("second_opinion") if isinstance(flow.get("second_opinion"), dict) else {}
    if cfg.get("command"):
        return str(cfg["command"]), int(cfg.get("timeout", 900))
    for exe, cmd in AUTO:
        if shutil.which(exe):
            return cmd, int(cfg.get("timeout", 900))
    return None, 0


def read(path, limit=None):
    try:
        with open(path, errors="replace") as f:
            return f.read(limit) if limit else f.read()
    except OSError:
        return None


def main(root, wdir):
    with open(os.path.join(root, ".claude", "flow.json")) as f:
        flow = json.load(f)
    wid = (read(os.path.join(wdir, "current")) or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", wid):
        print("no current task: work.sh init <ID> first", file=sys.stderr)
        return 2
    tdir = os.path.join(wdir, wid)
    diff = read(os.path.join(tdir, "review.diff"))
    if not diff:
        print(f"no review package: run work.sh review-package first ({tdir}/review.diff)", file=sys.stderr)
        return 2
    cmd, timeout = command(flow)
    if not cmd:
        print("no second-opinion CLI: install codex or gemini, or set \"second_opinion\": {\"command\": ...} in flow.json",
              file=sys.stderr)
        return 2
    cut = len(diff) > DIFF_MAX
    prompt = "\n\n".join([ASK,
                          "# Purpose\n" + (read(os.path.join(tdir, "00-purpose.md")) or "(none)"),
                          "# Contract\n" + (read(os.path.join(tdir, "01-contract.md")) or "(none: lane None)"),
                          "# Diff\n" + diff[:DIFF_MAX] + ("\n[diff cut at %d characters]" % DIFF_MAX if cut else "")])
    try:
        p = subprocess.run(cmd, shell=True, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=root)
        code, answer = p.returncode, p.stdout.strip() or p.stderr.strip()[-2000:]
    except subprocess.TimeoutExpired:
        code, answer = 1, f"timed out after {timeout} s"
    out = os.path.join(tdir, "second-opinion.md")
    with open(out, "w") as f:
        f.write(f"Command: {F.mask(cmd)}\nExit: {code}\n{'Diff cut: yes' + chr(10) if cut else ''}\n{F.mask(answer)}\n")
    print(f"{'answered' if code == 0 else 'failed'}: {out}")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
