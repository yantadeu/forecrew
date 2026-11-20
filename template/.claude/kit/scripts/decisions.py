"""Who acts on each review finding, and the session told when the dev decides one on the page.

dashboard.py reads the findings and their decision lines (open, fix-pending, fixed, accepted) and
lets the dev decide one at a time (POST /api/findings-decision). This adds what the dev needs to
decide from the page alone:

  view     needs-you   open on a PASS_WITH_FINDINGS review, a FAIL after max_fix_rounds, or a fix
                       the newer review of its lens still reports (reopened): only the dev moves it
           agent       open on a FAIL review inside the fix-round cap: the stage its route names
                       fixes it on its own
           fixing      the dev asked for a fix and no review ran since
           fixed       the orchestrator marked it fixed after the re-review
           accepted    the dev accepted it as it is
  actor    the stage that acts (refiner, executor, tester), "dev", or None
  route    the stage the review routed it to ([route: ...] in the review)

and, after each decision from the page, <work_dir>/attention/.requests/findings-<ID>.json: the
next prompt or start of a session in that worktree gets it as context and applies it
(hooks/attention.py). The page never edits code and never starts an agent.
"""
import json
import os
import re
import secrets
import time

VIEWS = ("needs-you", "agent", "fixing", "fixed", "accepted")
ROUTE = re.compile(r"\[route:\s*(refiner|executor|tester)\]", re.I)


def route_of(text):
    m = ROUTE.search(text or "")
    return m.group(1).lower() if m else None


def request_path(work_dir, tid):
    return os.path.join(work_dir, "attention", ".requests", f"findings-{tid}.json")


def enrich(state, tdir, stage_list, rounds, max_rounds, work_dir, tid):
    findings = state.get("findings") or []
    capped = rounds >= max_rounds
    for f in findings:
        st, route = f.get("state"), f.get("route") or "executor"
        # A fix the newer review of its lens still reports comes back open (dashboard.py,
        # decided_findings, "reopened"): the dev's again, never the fix loop's.
        if st == "open" and f.get("verdict") == "FAIL" and not capped and not f.get("reopened"):
            f["view"], f["actor"] = "agent", route
        elif st == "fix-pending":
            f["view"], f["actor"] = "fixing", route
        elif st in ("fixed", "accepted"):
            f["view"], f["actor"] = st, None
        else:
            f["view"], f["actor"] = "needs-you", "dev"
    state["findings_counts"] = {v: sum(f["view"] == v for f in findings) for v in VIEWS}
    state["findings_capped"] = capped
    state["findings_sent"] = bool(work_dir) and os.path.isfile(request_path(work_dir, tid))
    # A FAIL inside the round cap is the fix loop's: the dev's move is the findings that wait on
    # them, or nothing.
    if state["status"] == "FAIL" and any(f["view"] == "agent" for f in findings) \
            and not any(f["view"] == "needs-you" and f.get("verdict") == "FAIL" for f in findings):
        state["next_step"] = "decide-findings" if state["findings_counts"]["needs-you"] else "fix-loop"
        state["command"], state["command_kind"] = None, None
    # Fixes asked from the page are not "ready for PR" until a review ran again.
    if state["status"] == "ready-for-mr" and state["findings_counts"]["fixing"]:
        state["status"], state["next_step"] = "fixing", "wait-fixes"
        state["command"], state["command_kind"] = None, None
    return state


def notify(work_dir, task, now=None):
    """After a decision on the page: what the session must apply, as of now."""
    now = time.time() if now is None else now
    item = lambda f: {"lens": f["lens"], "severity": f["severity"], "summary": f["summary"], "route": f.get("route")}
    fix = [item(f) for f in task.get("findings") or [] if f.get("state") == "fix-pending"]
    accepted = [item(f) for f in task.get("findings") or [] if f.get("state") == "accepted"]
    open_left = sum(f.get("view") == "needs-you" for f in task.get("findings") or [])
    path = request_path(work_dir, task["id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = os.path.join(os.path.dirname(path), f".tmp-{secrets.token_hex(6)}")
    with open(tmp, "w") as fh:
        json.dump({"id": task["id"], "since": now, "fix": fix, "accepted": accepted, "open": open_left}, fh)
    os.replace(tmp, path)
