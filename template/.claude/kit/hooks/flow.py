#!/usr/bin/env python3
"""Agent flow hook: logs agent activity for the dashboard and gates stage completion.

Wired to SubagentStart, SubagentStop and PreToolUse. Two refusals, both only for an agent handed
the current work directory:
  - SubagentStop of a stage whose file misses a required section, status or verdict line, or
    an acceptance criterion it must cover (sent back once, then logged as failed);
  - launching a stage (the Agent tool) before the stages it requires pass, while the contract
    has open [NEEDS CLARIFICATION] markers, or past max_fix_rounds of the executor; a reviewer
    also waits for the project's checks (scripts/checks.py) to pass on the current tree.
Any other tool call is never blocked. Logging and the gates run only while a work is current;
the attention alerts (attention.py: which session waits on the dev, and why) run for every
session, because the session that waits on the dev is often the one still in the triage. For
those it is also wired to PostToolUse, PermissionRequest, Notification, Stop,
UserPromptSubmit, SessionStart and SessionEnd (scripts/wire_hooks.py).

Also the single implementation of the checks the scripts need:
  flow.py work-dir        prints the resolved work directory (refuses one outside the repo)
  flow.py status <ID>     re-runs the gate on every stage file; exit 1 on a failure or a FAIL
  flow.py page-key        prints the key the dashboard's link carries (?k=)
  flow.py remote-allow [on|off]   Allow of a permission from the page or Telegram (off by default)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

# attention.py imports this module as "flow"; without the alias it would load a second copy.
if __name__ == "__main__":
    sys.modules.setdefault("flow", sys.modules[__name__])

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

# Masked before anything is written: a command line or an agent's last message can carry a
# card number, a national id (with or without separators) or a credential.
SENSITIVE = [
    (re.compile(r"\d(?:[ .\-/]?\d){10,}"), "[digits]"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|KEY|CREDENTIAL)[A-Z0-9_]*)\s*[=:]\s*\S+"), r"\1=[masked]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [masked]"),
    (re.compile(r"(?i)(authorization\s*:\s*)\S+"), r"\1[masked]"),
    (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), "://[masked]@"),
    # A flag and its value: `--password s3cr3t`, `--passphrase=x`, `--token x`.
    (re.compile(r"(?i)(--?(?:password|passwd|passphrase|token|secret|api[-_]?key|access[-_]?key)(?:=|\s+))[^\s'\"]+"), r"\1[masked]"),
    # curl -u user:pass, curl --user user:pass.
    (re.compile(r"(?i)((?:^|\s)(?:-u\s*|--user[=\s]+)['\"]?[^\s:'\"]+:)[^\s'\"]+"), r"\1[masked]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[aws-key]"),
    # Presigned URLs: the signature is the credential.
    (re.compile(r"(?i)((?:X-Amz-)?Signature=)[^&\s'\"]+"), r"\1[masked]"),
]


# What a turn's last message asks of the dev: a "?" or an explicit ask, English or Portuguese, in
# its last ASK_TAIL characters, where a session puts its question. Shared by the Stop hold
# (attention.py), which holds only a turn that asks, and the dashboard, which tells a turn that
# waits on the dev from one that only informs.
ASK_TAIL = 600
ASK_WORDS = re.compile(
    r"\b(?:responda|confirme|aprova|escolha|posso seguir|quer que|me diga|decida|aguardo|me avise"
    r"|prefere|se estiver ok|answer|reply|confirm|approve|choose|shall i|should i|let me know|decide"
    r"|prefer|if it'?s ok|go-ahead|waiting for your|which option)\b", re.I)


def asks(text):
    tail = str(text or "")[-ASK_TAIL:]
    return "?" in tail or bool(ASK_WORDS.search(tail))


def mask(text):
    for rx, repl in SENSITIVE:
        text = rx.sub(repl, text)
    return text


def forecrew_home():
    return os.environ.get("FORECREW_HOME") or os.path.join(os.path.expanduser("~"), ".forecrew")


# Web answers (from the dashboard or the Telegram bridge) reach a hold as a file under the work
# directory, which every process of the project can write: an agent's background job, a test, a
# build script. So a hold acts only on an answer signed with a key that lives outside the project,
# in <FORECREW_HOME>/private/answer.key (0600 in a 0700 directory). It does not stop a process
# that can read that file; run agents sandboxed with that directory unreadable for that.
PRIVATE_DIR = "private"
ANSWER_KEY = "answer.key"
# Allow of a permission from the page or Telegram: off unless this file exists. Outside the
# project, so nothing a project's process writes can turn it on; `work.sh ui allow on|off`.
REMOTE_ALLOW = "remote-allow"


def private_dir():
    return os.path.join(forecrew_home(), PRIVATE_DIR)


def answer_key(create=False):
    """The signing key, or None when there is none (or it is readable by others). create makes
    one, for the signers (dashboard, telegram); the holds only read."""
    d = private_dir()
    path = os.path.join(d, ANSWER_KEY)
    if create and not os.path.exists(path):
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(os.urandom(32))
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if st.st_mode & 0o077 or (hasattr(os, "getuid") and st.st_uid != os.getuid()):
            print(f"forecrew: {path} must be private to you (chmod 600); web answers are off.", file=sys.stderr)
            return None
        key = f.read()
    return key if len(key) >= 32 else None


def _answer_mac(key, answer):
    import hmac
    body = {k: v for k, v in answer.items() if k != "sig"}
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hmac.new(key, b"forecrew-answer\0" + data, hashlib.sha256).hexdigest()


def sign_answer(answer):
    """The answer with its signature; raises when no key can be made."""
    key = answer_key(create=True)
    if key is None:
        raise RuntimeError("no private answer key: see " + private_dir())
    return {**answer, "sig": _answer_mac(key, answer)}


def answer_signed(answer):
    """True when the answer carries a valid signature: written by the dashboard or the bridge."""
    import hmac
    if not isinstance(answer, dict) or not isinstance(answer.get("sig"), str):
        return False
    key = answer_key()
    return key is not None and hmac.compare_digest(answer["sig"], _answer_mac(key, answer))


def page_key():
    """What the dashboard's URL carries (?k=) to be served at all: derived from the answer key, so
    it survives a restart and every dashboard of this machine takes the same link."""
    import hmac
    key = answer_key(create=True)
    if key is None:
        raise RuntimeError("no private answer key: see " + private_dir())
    return hmac.new(key, b"forecrew-page", hashlib.sha256).hexdigest()[:43]


def remote_allow_on():
    return os.path.isfile(os.path.join(private_dir(), REMOTE_ALLOW))


def load_flow():
    path = os.path.join(ROOT, ".claude", "flow.json")
    try:
        with open(path) as f:
            flow = json.load(f)
        if not isinstance(flow, dict):
            raise ValueError("not an object")
        return flow
    except OSError:
        return None
    except ValueError as e:
        # A broken flow.json turns the gate off; say so instead of passing every stage silently.
        print(f"forecrew: {path} is invalid ({e}); stage gate and dashboard log are off.", file=sys.stderr)
        return None


def work_dir(flow):
    d = os.path.realpath(os.path.join(ROOT, flow.get("work_dir", ".work")))
    root = os.path.realpath(ROOT)
    if d == root or not d.startswith(root + os.sep):
        raise ValueError(f"work_dir {d} must be a subdirectory of {root}")
    return d


# Session and agent ids become path components: the first character excludes "." and "..",
# and ".answer" is the suffix of the file the dashboard writes next to an alert.
ALERT_ID_RX = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}")
# Events that raise or clear an alert; PreToolUse is handled inline, it runs on every tool call.
ATTENTION_EVENTS = {"PostToolUse", "SubagentStart", "SubagentStop", "PermissionRequest", "Notification", "Stop",
                    "UserPromptSubmit", "SessionStart", "SessionEnd"}


def alert_path(flow, session, agent):
    """<work_dir>/attention/<session>/<agent>.json, or None when an id is not a safe name."""
    for i in (session, agent):
        if not isinstance(i, str) or not ALERT_ID_RX.fullmatch(i) or i.endswith(".answer"):
            return None
    return os.path.join(work_dir(flow), "attention", session, agent + ".json")


def attention(flow, event):
    """Never raises, and prints to stdout only on UserPromptSubmit and SessionStart (a memory
    cleanup request, as context): on PermissionRequest and Notification a stdout line is a
    decision, and a broken alert must not break the session."""
    name = event.get("hook_event_name")
    try:
        if name == "PreToolUse":
            # The tool ran past whatever this agent was waiting on. AskUserQuestion is the hold
            # entry's: hooks of one event run in parallel, and this would erase its alert.
            if event.get("tool_name") != "AskUserQuestion":
                path = alert_path(flow, event.get("session_id"), event.get("agent_id") or "main")
                if path:
                    os.unlink(path)
        elif name in ATTENTION_EVENTS:
            import attention as attn
            attn.handle(event, flow)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"forecrew attention: {type(e).__name__}: {e}", file=sys.stderr)


def current_id(flow):
    try:
        with open(os.path.join(work_dir(flow), "current")) as f:
            wid = f.read().strip()
    except OSError:
        return None
    return wid if re.fullmatch(r"[A-Za-z0-9._-]+", wid) else None


def log(flow, wid, entry):
    # Masked per value, never on the serialized line: that would eat JSON quotes and the timestamp.
    # Except the agent id: a hex id with eleven digits in it would be masked as a number, and
    # every agent so masked would share one lane on the dashboard.
    entry = {k: mask(v) if isinstance(v, str) and k != "agent" else v for k, v in entry.items()}
    entry["t"] = time.time()
    entry["work"] = wid
    line = json.dumps(entry, ensure_ascii=False)
    # One short line per write with O_APPEND: concurrent hooks do not interleave.
    with open(os.path.join(work_dir(flow), "events.jsonl"), "a") as f:
        f.write(line + "\n")


AC = re.compile(r"\bAC-\d{3}\b")
MARKER = re.compile(r"\[NEEDS CLARIFICATION[^\]]*\]")
STATUSES = ("DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED")


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def section(text, name):
    m = re.search(r"^##\s+" + re.escape(name) + r"\s*$(.*?)(?=^##\s|\Z)", text or "", re.M | re.S | re.I)
    return m.group(1) if m else ""


def purpose(flow, wid):
    """(text, acceptance criterion ids, lane) of 00-purpose.md."""
    text = read(os.path.join(work_dir(flow), wid, "00-purpose.md"))
    ids = sorted(set(AC.findall(section(text, "Acceptance criteria"))))
    lane = re.search(r"^Lane:\s*(\w+)", text or "", re.M | re.I)
    return text, ids, (lane.group(1).lower() if lane else "")


def tool_detail_full(event):
    inp = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    for key in ("command", "file_path", "pattern", "url", "description", "subagent_type"):
        if inp.get(key):
            return str(inp[key])
    return ""


def tool_detail(event):
    return tool_detail_full(event)[:120]


def in_this_work(event, flow, wid):
    """True when the agent was handed this work directory: a stale `current` must not
    capture an agent launched for something else (a standalone review, an exploration)."""
    path = event.get("agent_transcript_path") or event.get("transcript_path")
    if not path:
        return True  # no transcript to check: gating is the safe side
    marker = os.path.basename(work_dir(flow)) + "/" + wid
    try:
        with open(path, errors="replace") as f:
            return any(marker in line for line in f)
    except OSError:
        return True


def gate(flow, wid, agent_type):
    """Returns the reason the stage may not finish, or None."""
    stage = (flow.get("stages") or {}).get(agent_type)
    if not stage:
        return None
    base = os.path.join(work_dir(flow), wid)
    ptext, acs, _ = purpose(flow, wid)
    if ptext is None:
        return f"{base}/00-purpose.md does not exist: the orchestrator must write the purpose before any stage runs."
    path = os.path.join(base, stage["file"])
    text = read(path)
    if text is None:
        return f"Write your result to {path} before finishing (protocol: .claude/kit/PROTOCOL.md)."
    missing = [s for s in stage.get("sections", [])
               if not re.search(r"^##\s+" + re.escape(s) + r"\s*$", text, re.M | re.I)]
    if missing:
        return f"{path} is missing the sections: " + ", ".join(f'"## {s}"' for s in missing)
    if stage.get("verdict") and not re.search(r"^Verdict:\s*(PASS|PASS_WITH_FINDINGS|FAIL)\s*$", text, re.M):
        return f"{path} must start with a line 'Verdict: PASS | PASS_WITH_FINDINGS | FAIL'."
    if stage.get("status") and not re.search(r"^Status:\s*(" + "|".join(STATUSES) + r")\s*$", text, re.M):
        return f"{path} must start with a line 'Status: {' | '.join(STATUSES)}'."
    if "What can fail silently" in stage.get("sections", []) and re.fullmatch(
            r"\s*(-\s*)?(none|nothing|n/?a)?\.?\s*", section(text, "What can fail silently"), re.I):
        return "\"What can fail silently\" cannot be empty or 'none': if nobody can name a silent failure, the refinement has not looked deep enough."
    if stage.get("covers"):
        if not acs:
            return f"{base}/00-purpose.md has no acceptance criteria written as AC-001, AC-002... under '## Acceptance criteria'."
        missing = [a for a in acs if a not in AC.findall(section(text, stage["covers"]))]
        if missing:
            return f"{path}: '## {stage['covers']}' must cite every acceptance criterion; missing {', '.join(missing)}."
    return None


ID_RX = re.compile(r"[A-Za-z0-9._-]+")


def tree_fingerprint(flow=None):
    """What the code looks like right now: HEAD, the diff against it and every untracked file
    (name and content), outside the work directory. Same tree, same value."""
    def git(*args):
        try:
            return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            return b""
    head = git("rev-parse", "HEAD").strip()
    if not head:
        return "no-git"
    h = hashlib.sha256(head + b"\0" + git("diff", "HEAD", "--binary"))
    skip = os.path.relpath(work_dir(flow), os.path.realpath(ROOT)).encode() + b"/" if flow else None
    for name in sorted(git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0")):
        # Bytecode is written by the hooks themselves (importing attention.py) and by any Python
        # check: it is not the change, and it would make every result stale at once.
        if not name or (skip and name.startswith(skip)) or b"__pycache__/" in name or name.endswith(b".pyc"):
            continue
        h.update(name + b"\0")
        try:
            with open(os.path.join(ROOT, name.decode(errors="replace")), "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            pass
    return h.hexdigest()[:16]


def checks_gate(flow, wid):
    """Why a reviewer may not start because of the project's checks, or None. No checks
    configured: no gate."""
    if not flow.get("checks"):
        return None
    path = os.path.join(work_dir(flow), wid, "checks.md")
    text = read(path)
    if text is None:
        return "the project's checks have not run: work.sh checks (work.sh review-package runs them too)."
    result = re.search(r"^Checks:\s*(\w+)", text, re.M)
    if not result or result.group(1) != "PASS":
        failed = re.findall(r"^## (.+)\n(?:.*\n)?Result: FAIL", text, re.M)
        return (f"the project's checks fail ({', '.join(failed) or 'see the file'}): {path}. "
                f"The change goes back to the executor before any reviewer reads it.")
    fp = re.search(r"^Fingerprint:\s*(\S+)", text, re.M)
    if not fp or fp.group(1) != tree_fingerprint(flow):
        return "the code changed since the checks ran: run work.sh checks again."
    return None


def ready(flow, wid, target):
    """Returns why `target` may not start yet, or None."""
    stage = flow["stages"][target]
    ptext, _, lane = purpose(flow, wid)
    if ptext is None:
        return "write 00-purpose.md first (work.sh init)."
    # Lane None skips refiner, executor and tester: the reviewers then check the change directly.
    for req in [] if lane == "none" else stage.get("requires", []):
        rfile = flow["stages"][req]["file"]
        text = read(os.path.join(work_dir(flow), wid, rfile))
        if text is None:
            return f"{target} needs {req} first: {rfile} does not exist."
        why = gate(flow, wid, req)
        if why:
            return f"{target} needs {req} to pass its gate: {why}"
        st = re.search(r"^Status:\s*(\w+)", text, re.M)
        if st and st.group(1) in ("NEEDS_CONTEXT", "BLOCKED"):
            return f"{req} reported {st.group(1)}: resolve it with the dev before {target}."
        markers = MARKER.findall(text)
        if markers:
            return (f"{rfile} has {len(markers)} open [NEEDS CLARIFICATION] marker(s): run the clarification "
                    f"loop (task skill, step 4) and re-run {req}.")
    if stage.get("verdict"):
        why = checks_gate(flow, wid)
        if why:
            return f"{target} needs the project's checks: {why}"
    if target == "executor":
        starts = sum(1 for e in events(flow) if e.get("work") == wid and e.get("ev") == "start" and e.get("type") == "executor")
        cap = flow.get("max_fix_rounds", 3)
        if starts > cap:
            return f"the executor already ran {starts} times (first run + {cap} fix rounds): stop and take the open findings to the dev."
    return None


def events(flow):
    text = read(os.path.join(work_dir(flow), "events.jsonl")) or ""
    out = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def status(flow, wid):
    bad, shown_next = False, False
    if flow.get("checks"):
        why = checks_gate(flow, wid)
        print(f"  {'ok' if not why else 'pending':7}  {'checks':18} checks.md")
        if why:
            print(f"           {why}")
    for agent, stage in flow["stages"].items():
        text = read(os.path.join(work_dir(flow), wid, stage["file"]))
        if text is None:
            line = f"  pending  {agent:18} {stage['file']}"
            if not shown_next:
                why = ready(flow, wid, agent)
                line += f"   <- next{': blocked, ' + why if why else ''}"
                shown_next = True
            print(line)
            continue
        reason = gate(flow, wid, agent)
        m = re.search(r"^(?:Verdict|Status):\s*(\w+)", text, re.M)
        word = m.group(1) if m else ""
        markers = len(MARKER.findall(text))
        failing = reason or word in ("FAIL", "BLOCKED", "NEEDS_CONTEXT") or markers
        label = "FAILED" if reason else "OPEN" if markers else word if failing else "ok"
        print(f"  {label:7}  {agent:18} {stage['file']} {word}".rstrip())
        if reason:
            print(f"           {reason}")
        if markers:
            print(f"           {markers} open [NEEDS CLARIFICATION] marker(s)")
        bad |= bool(failing)
    return 1 if bad else 0


def cli(args):
    # Exit codes: 0 ok, 1 a check failed, 2 configuration or usage error.
    if args[0] == "page-key" and len(args) == 1:
        print(page_key())
        return 0
    if args[0] == "remote-allow" and len(args) <= 2:
        flag = os.path.join(private_dir(), REMOTE_ALLOW)
        if args[1:] == ["on"]:
            answer_key(create=True)  # makes the private directory, 0700
            open(flag, "w").close()
        elif args[1:] == ["off"]:
            try:
                os.unlink(flag)
            except FileNotFoundError:
                pass
        elif args[1:]:
            print("usage: flow.py remote-allow [on|off]", file=sys.stderr)
            return 2
        print("on" if remote_allow_on() else "off")
        return 0
    flow = load_flow()
    if flow is None:
        print("forecrew: .claude/flow.json is missing or invalid", file=sys.stderr)
        return 2
    try:
        if args[0] == "work-dir":
            print(work_dir(flow))
            return 0
        if args[0] == "status" and len(args) == 2:
            return status(flow, args[1])
    except ValueError as e:
        print(f"forecrew: {e}", file=sys.stderr)
        return 2
    print(__doc__, file=sys.stderr)
    return 2


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    flow = load_flow()
    if flow is None:
        return 0
    attention(flow, event)
    try:
        wid = current_id(flow)
    except ValueError as e:
        print(f"forecrew: {e}; stage gate and dashboard log are off.", file=sys.stderr)
        return 0
    if not wid:
        return 0
    name = event.get("hook_event_name")
    agent = event.get("agent_id") or "main"
    agent_type = event.get("agent_type") or ("main" if agent == "main" else "")

    if name == "SubagentStart":
        log(flow, wid, {"ev": "start", "agent": agent, "type": agent_type})
    elif name == "PreToolUse":
        log(flow, wid, {"ev": "tool", "agent": agent, "type": agent_type,
                        "tool": event.get("tool_name"), "detail": tool_detail(event)})
        inp = event.get("tool_input") or {}
        target = inp.get("subagent_type")
        marker = os.path.basename(work_dir(flow)) + "/" + wid
        if event.get("tool_name") in ("Agent", "Task") and target in flow["stages"] and marker in str(inp.get("prompt", "")):
            why = ready(flow, wid, target)
            if why:
                log(flow, wid, {"ev": "refused", "agent": agent, "type": target, "detail": why})
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "deny", "permissionDecisionReason": f"forecrew: {why}"}}))
    elif name == "SubagentStop":
        reason = gate(flow, wid, agent_type) if in_this_work(event, flow, wid) else None
        if reason and not event.get("stop_hook_active"):
            log(flow, wid, {"ev": "blocked", "agent": agent, "type": agent_type, "detail": reason})
            print(reason, file=sys.stderr)
            return 2  # blocks the stop and hands the reason back to the agent
        summary = (event.get("last_assistant_message") or "")[:300]
        # A stop let through on the retry is still a failed stage: `work.sh status` reports it.
        log(flow, wid, {"ev": "stop", "agent": agent, "type": agent_type,
                        "gate": "failed" if reason else "ok", "detail": reason or summary})
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]) if len(sys.argv) > 1 else main())
