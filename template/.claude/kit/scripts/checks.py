#!/usr/bin/env python3
"""The project's own checks (lint, build, tests), run by the machine before any reviewer reads
the change: the four lenses then read the same evidence, and none of them is spent on a change
that does not build.

Usage: checks.py run <root> <ID>     runs every entry of "checks" in .claude/flow.json in the
                                     repository root and writes .work/<ID>/checks.md; exit 0 when
                                     all pass (or none is configured), 1 when one fails

flow.json: "checks": [{"name": "lint", "run": "ruff check ."}, {"name": "unit", "run": "pytest -q",
"timeout": 900}]. The commands are the dev's, like a Makefile; they run with the shell.

A check that cannot run is a failure, never a skip: a missing tool (exit 127) or a timeout fails
the check and says why. checks.md carries a fingerprint of the working tree (HEAD, the diff and
the untracked files) taken after the run: the gate (hooks/flow.py) lets a reviewer start only
while the tree still matches it, so a result never outlives the code it was run on.
"""
import hashlib
import importlib.util
import os
import subprocess
import sys
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_LINES = 80
DEFAULT_TIMEOUT = 900


def flow_module(root):
    os.environ["CLAUDE_PROJECT_DIR"] = root
    spec = importlib.util.spec_from_file_location("flow", os.path.join(KIT, "hooks", "flow.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_one(root, check):
    name, cmd = str(check.get("name") or "check"), check.get("run")
    timeout = check.get("timeout") if isinstance(check.get("timeout"), (int, float)) else DEFAULT_TIMEOUT
    if not isinstance(cmd, str) or not cmd.strip():
        return {"name": name, "run": str(cmd), "ok": False, "why": "no command in \"run\"", "seconds": 0.0, "output": ""}
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True, errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
        code, out = p.returncode, (p.stdout or "") + (p.stderr or "")
        why = "" if code == 0 else (f"exit {code}: the command was not found; a check that cannot run fails"
                                    if code == 127 else f"exit {code}")
    except subprocess.TimeoutExpired as e:
        code, out = None, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        why = f"timed out after {timeout:g}s"
    return {"name": name, "run": cmd, "ok": code == 0, "why": why, "seconds": time.monotonic() - t0, "output": out}


def write(path, flow, results, fingerprint):
    overall = "NONE" if not results else "PASS" if all(r["ok"] for r in results) else "FAIL"
    lines = [f"Checks: {overall}", f"Fingerprint: {fingerprint}", ""]
    if not results:
        lines.append('No checks configured ("checks" in .claude/flow.json): nothing was run by the machine.')
    for r in results:
        tail = "\n".join(flow.mask(r["output"]).rstrip().splitlines()[-OUTPUT_LINES:])
        lines += [f"## {r['name']}", f"Command: `{flow.mask(r['run'])}`",
                  f"Result: {'PASS' if r['ok'] else 'FAIL'} ({r['why'] or 'exit 0'}, {r['seconds']:.1f}s)", "",
                  "```", tail.replace("```", "'''"), "```", ""]
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    os.replace(tmp, path)
    return overall


def main(argv):
    if len(argv) != 4 or argv[1] != "run":
        print(__doc__, file=sys.stderr)
        return 2
    root, wid = os.path.realpath(argv[2]), argv[3]
    flow_mod = flow_module(root)
    flow = flow_mod.load_flow()
    if flow is None:
        print("forecrew: .claude/flow.json is missing or invalid", file=sys.stderr)
        return 2
    tdir = os.path.join(flow_mod.work_dir(flow), wid)
    if not flow_mod.ID_RX.fullmatch(wid) or not os.path.isdir(tdir):
        print(f"forecrew: no task {wid}", file=sys.stderr)
        return 2
    checks = flow.get("checks") or []
    results = []
    for c in checks if isinstance(checks, list) else []:
        if isinstance(c, dict):
            print(f"check {c.get('name') or 'check'}: {c.get('run')}", flush=True)
            results.append(run_one(root, c))
            print(f"  {'PASS' if results[-1]['ok'] else 'FAIL ' + results[-1]['why']}", flush=True)
    path = os.path.join(tdir, "checks.md")
    overall = write(path, flow_mod, results, flow_mod.tree_fingerprint(flow))
    print(f"{path}: {overall}")
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
