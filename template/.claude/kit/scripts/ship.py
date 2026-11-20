#!/usr/bin/env python3
"""Ship a task: push its branch and open the pull or merge request with the dev's forge tool.

Usage: ship.py <ID> [--dry-run]

Optional and off by default. flow.json "ship" decides:
  {"enabled": false, "tool": "auto", "push": true, "draft": true, "command": ""}
  tool   auto (github.com -> gh, a GitLab -> glab, anything else -> none), gh, glab, custom, none
  custom a command template with {base} {branch} {title} {body_file} {draft}, each value
         shell-quoted on its own; the template itself is the dev's, never built from task text.

Disabled (or tool none), it writes the body file and prints the one command the dev can run.
Enabled, it pushes the task's own branch (never with force, never a base branch), opens the
PR/MR, prints its URL and keeps it in .work/<ID>/mr.json, so the dashboard reads the task as
done at once. A tool that is missing or not logged in is named with what to install or run;
this script never asks for, reads or prints a token.

Exit codes: 0 shipped or command printed, 1 refused or the tool failed, 2 usage.
"""
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("kit_dashboard_ship", os.path.join(HERE, "dashboard.py"))
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

DEFAULTS = {"enabled": False, "tool": "auto", "push": True, "draft": True, "command": ""}
TOOLS = ("auto", "gh", "glab", "custom", "none")
URL_RX = re.compile(r"https?://\S+")


def config(flow):
    got = flow.get("ship") if isinstance(flow.get("ship"), dict) else {}
    out = {**DEFAULTS, **{k: v for k, v in got.items() if k in DEFAULTS}}
    if out["tool"] not in TOOLS:
        out["tool"] = "none"
    return out


def pick_tool(cfg, root, flow):
    if cfg["tool"] != "auto":
        return cfg["tool"]
    remote = D.parse_remote(D.git_out(root, "remote", "get-url", "origin") or "")
    forge = D.forge_of(remote[0], flow) if remote else None
    return {"github": "gh", "gitlab": "glab"}.get(forge, "none")


def base_of(root):
    return D.default_base(root).split("/", 1)[-1]


def body_text(tdir, tid):
    """The PR/MR body: the task's own pr-body.md when the closing wrote one, else the purpose."""
    for name in ("pr-body.md", "00-purpose.md"):
        text = D.read(os.path.join(tdir, name))
        if text:
            return text
    return f"Task {tid}."


def command(tool, cfg, base, branch, title, body_file):
    draft = bool(cfg["draft"])
    if tool == "gh":
        return ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title,
                "--body-file", body_file] + (["--draft"] if draft else [])
    if tool == "glab":
        return ["glab", "mr", "create", "--source-branch", branch, "--target-branch", base, "--title", title,
                "--description", open(body_file).read(), "--yes"] + (["--draft"] if draft else [])
    if tool == "custom" and cfg["command"]:
        values = {"base": base, "branch": branch, "title": title, "body_file": body_file, "draft": "true" if draft else "false"}
        words = shlex.split(cfg["command"])
        return [re.sub(r"\{(base|branch|title|body_file|draft)\}", lambda m: values[m.group(1)], w) for w in words]
    return None


def auth_hint(tool, host):
    if tool == "gh":
        return "gh is not logged in: run `gh auth login`, then ship again."
    return f"glab is not logged in to {host}: run `glab auth login --hostname {host}`, then ship again."


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    dry = "--dry-run" in argv
    if len(args) != 1 or not D.ID_RX.fullmatch(args[0]):
        print(__doc__.strip().split("\n\n")[0], file=sys.stderr)
        return 2
    tid = args[0]
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    flow = D.flow_of(root)
    wdir = D.work_dir(root)
    tdir = os.path.join(wdir, tid) if wdir else None
    if not tdir or not os.path.isdir(tdir):
        print(f"ship: no task {tid} in {root}", file=sys.stderr)
        return 1
    head = (D.git_out(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    branch = D.task_branch(tdir, head)
    if not branch or branch == "HEAD" or branch in D.base_branches(flow):
        print(f"ship: refused: {branch or 'no branch'} is a base branch or detached; a task ships from its own branch.",
              file=sys.stderr)
        return 1
    cfg, base = config(flow), base_of(root)
    tool = pick_tool(cfg, root, flow)
    title = D.title(tdir, tid)
    body_file = os.path.join(tdir, "pr-body.md")
    if not os.path.exists(body_file):
        with open(body_file, "w") as f:
            f.write(body_text(tdir, tid))
    cmd = command(tool if tool != "none" else "gh", cfg, base, branch, title, body_file) if tool != "custom" or cfg["command"] else None
    shown = " ".join(shlex.quote(w) for w in cmd) if cmd else None
    if not cfg["enabled"] or tool == "none":
        print(f"ship is off: push and open the PR/MR yourself.\n  git push -u origin {shlex.quote(branch)}")
        if shown and tool != "none":
            print(f"  {shown}")
        print(f"  body: {body_file}")
        return 0
    binary = cmd[0] if cmd else None
    if not cmd or not shutil.which(binary):
        install = {"gh": "https://cli.github.com", "glab": "https://gitlab.com/gitlab-org/cli#installation"}.get(binary, "")
        print(f"ship: {binary or 'no command'} is not installed{(': ' + install) if install else ''}; install it, then ship again.",
              file=sys.stderr)
        return 1
    if tool in ("gh", "glab"):
        host = (D.parse_remote(D.git_out(root, "remote", "get-url", "origin") or "") or ("",))[0]
        auth = [tool, "auth", "status"] + (["--hostname", host] if tool == "glab" and host else [])
        if subprocess.run(auth, cwd=root, capture_output=True).returncode != 0:
            print(f"ship: {auth_hint(tool, host)}", file=sys.stderr)
            return 1
    if dry:
        print(f"would push {branch} and run: {shown}")
        return 0
    if cfg["push"]:
        p = subprocess.run(["git", "-C", root, "push", "-u", "origin", branch], capture_output=True, text=True)
        if p.returncode != 0:
            print(f"ship: push failed: {p.stderr.strip()[-500:]}", file=sys.stderr)
            return 1
    p = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    urls = URL_RX.findall(p.stdout + "\n" + p.stderr)
    if p.returncode != 0 or not urls:
        print(f"ship: {binary} failed: {(p.stderr or p.stdout).strip()[-500:]}", file=sys.stderr)
        return 1
    url = urls[-1].rstrip(".,)")
    m = re.search(r"/(?:pull|merge_requests)/(\d+)", url)
    if m:
        with open(os.path.join(tdir, "mr.json"), "w") as f:
            json.dump({"iid": int(m.group(1)), "url": url, "state": "opened", "branch": branch}, f)
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
