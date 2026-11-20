#!/usr/bin/env python3
"""Behavior evals for the flow's agents: does each agent do what its file says, under pressure?

Usage: run.py [case...] [--runs N] [--control] [--model M]   run cases with `claude -p --agent <role>`
       run.py --grade <case> <repo-dir>                       grade an existing run (no model call)

Method: a case is a fixture work directory, a prompt that
often pushes the agent to skip a rule, and deterministic checks on the files it writes. Run a
case several times (--runs 5): one pass proves little. --control runs the same prompt with no
agent instructions; a case that also passes under --control does not test the agent.

Each run copies this repository's .claude/ into a scratch git repository, so it evaluates your
adapted agents, not the kit's. It calls the model: it costs tokens and is not run in CI.
Exit codes: 0 every run passed, 1 a check failed, 2 usage or setup error.
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
spec = importlib.util.spec_from_file_location("flow", os.path.join(HERE, "..", "hooks", "flow.py"))
flow_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow_mod)


def load(case):
    with open(os.path.join(HERE, "cases", case, "case.json")) as f:
        return json.load(f)


def setup(case, c, control=False):
    repo = tempfile.mkdtemp(prefix=f"eval-{case}-")
    shutil.copytree(os.path.join(ROOT, ".claude"), os.path.join(repo, ".claude"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    if control:
        # A control with any kit file on disk is not a control: the model reads flow.json, the
        # hook or the protocol on its own and follows them. The whole .claude/ is moved out
        # during the run and brought back for grading.
        shutil.move(os.path.join(repo, ".claude"), repo + ".claude-hidden")
    app = os.path.join(HERE, "cases", case, "repo")
    if os.path.isdir(app):
        shutil.copytree(app, repo, dirs_exist_ok=True)
    work = os.path.join(repo, ".work")
    shutil.copytree(os.path.join(HERE, "cases", case, "work"), os.path.join(work, c["id"]))
    with open(os.path.join(work, "current"), "w") as f:
        f.write(c["id"])
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.name=eval", "-c", "user.email=eval@localhost", "commit", "-qm", "fixture"]):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    return repo


def grade(c, repo):
    """List of failed check descriptions (empty = pass)."""
    work = os.path.join(repo, ".work", c["id"])
    failed = []
    for chk in c["checks"]:
        if "gate" in chk:
            flow_mod.ROOT = repo  # the gate resolves the work directory against this
            with open(os.path.join(repo, ".claude", "flow.json")) as f:
                flow = json.load(f)
            why = flow_mod.gate(flow, c["id"], chk["gate"])
            if why:
                failed.append(f"gate {chk['gate']}: {why}")
            continue
        text = flow_mod.read(os.path.join(work, chk["file"])) or ""
        if chk.get("section"):
            text = flow_mod.section(text, chk["section"])
        if "re" in chk and not re.search(chk["re"], text, re.M | re.I):
            failed.append(f"{chk['file']}: expected /{chk['re']}/ ({chk.get('why', '')})")
        if "not_re" in chk and re.search(chk["not_re"], text, re.M | re.I):
            failed.append(f"{chk['file']}: unexpected /{chk['not_re']}/ ({chk.get('why', '')})")
    return failed


def run_once(case, c, control, model):
    repo = setup(case, c, control)
    cmd = ["claude", "-p", c["prompt"], "--permission-mode", "acceptEdits", "--output-format", "json"]
    if not control:
        cmd += ["--agent", c["agent"]]
    if model:
        cmd += ["--model", model]
    p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=c.get("timeout", 900))
    if control:
        shutil.rmtree(os.path.join(repo, ".claude"), ignore_errors=True)
        shutil.move(repo + ".claude-hidden", os.path.join(repo, ".claude"))
    if p.returncode != 0:
        return repo, [f"claude exited {p.returncode}: {p.stderr.strip()[:300]}"]
    return repo, grade(c, repo)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cases", nargs="*")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--control", action="store_true", help="run without the agent's instructions")
    ap.add_argument("--model")
    ap.add_argument("--grade", nargs=2, metavar=("CASE", "REPO"))
    ap.add_argument("--keep", action="store_true", help="keep the scratch repositories")
    o = ap.parse_args()
    if o.grade:
        failed = grade(load(o.grade[0]), o.grade[1])
        print("\n".join(failed) or "pass")
        return 1 if failed else 0
    if shutil.which("claude") is None:
        print("claude CLI not found", file=sys.stderr)
        return 2
    cases = o.cases or sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(HERE, "cases", "*", "case.json")))
    total_bad = 0
    for case in cases:
        c = load(case)
        passed = 0
        for i in range(o.runs):
            repo, failed = run_once(case, c, o.control, o.model)
            passed += not failed
            print(f"{case} run {i + 1}: {'pass' if not failed else 'FAIL'}{'  ' + repo if o.keep else ''}")
            for f in failed:
                print(f"    {f}")
            if not o.keep:
                shutil.rmtree(repo, ignore_errors=True)
        print(f"{case}: {passed}/{o.runs}{' (control)' if o.control else ''}")
        total_bad += o.runs - passed
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
