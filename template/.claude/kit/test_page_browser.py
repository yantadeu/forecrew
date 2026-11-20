#!/usr/bin/env python3
"""The Forecrew dashboard page in a real headless Chromium (Playwright): what test_page.py cannot
see without running the page.

Usage: python3 .claude/kit/test_page_browser.py     (needs `pip install playwright` and
       `python3 -m playwright install chromium`)

It builds a scratch repository with a linked worktree, tasks in several states and live alerts,
starts dashboard.py on a free port against it, and runs each step of STEPS in order. A failed
step exits 1 with its name. No forge is called: the fixture's remote is a local bare repository.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from playwright.sync_api import sync_playwright

KIT = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(KIT, "scripts", "dashboard.py")
FLOW = os.path.join(KIT, "..", "flow.json")


class Fail(Exception):
    pass


def check(step, ok, detail=""):
    if not ok:
        raise Fail(f"{step}: {detail}")
    print(f"ok    {step}")


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True, text=True)


def task(wdir, tid, title, reviews=None, closed=False, finding="a finding to decide", stages=True, extra=""):
    d = os.path.join(wdir, tid)
    os.makedirs(d)
    with open(os.path.join(d, "00-purpose.md"), "w") as f:
        f.write(f"# {tid} {title}\n\nLane: Light\n\n## Purpose\nx\n{extra}")
    for name in ("01-contract.md", "02-change.md", "03-proof.md") if stages else ():
        with open(os.path.join(d, name), "w") as f:
            f.write("Status: DONE\n")
    for lens, verdict in (reviews or {}).items():
        with open(os.path.join(d, f"04-review-{lens}.md"), "w") as f:
            body = f"- [medium] {finding}\n  Scenario: the {lens} detail line.\n" if verdict != "PASS" else "- none\n"
            f.write(f"Verdict: {verdict}\n\n## Findings\n{body}")
    if closed:
        with open(os.path.join(d, "closed"), "w") as f:
            f.write("1\n")
    return d


def alert(wdir, session, kind, agent="main", **extra):
    d = os.path.join(wdir, "attention", session)
    os.makedirs(d, exist_ok=True)
    body = {"kind": kind, "since": time.time(), "detail": f"{kind} detail", **extra}
    path = os.path.join(d, f"{agent}.json")
    with open(path, "w") as f:
        json.dump(body, f)
    return path


def keep_held(path, stop):
    """The hook's heartbeat: an alert is held only while its holder beats (15 s)."""
    while not stop.wait(2):
        try:
            with open(path) as f:
                body = json.load(f)
            body["heartbeat"] = time.time()
            with open(path + ".tmp", "w") as f:
                json.dump(body, f)
            os.replace(path + ".tmp", path)
        except (OSError, ValueError):
            pass


ALL_PASS = {"contract": "PASS", "security": "PASS", "qa": "PASS", "product": "PASS"}


def fixture(base):
    """repo (main, a base branch: no PR/MR lookup) with a task in findings, one ready to close and
    six alerts; a linked worktree with a done task. Returns (repo, main .work, held alert paths)."""
    repo, wt = os.path.join(base, "repo"), os.path.join(base, "wt-b")
    os.makedirs(os.path.join(repo, ".claude"))
    shutil.copy(FLOW, os.path.join(repo, ".claude", "flow.json"))
    with open(os.path.join(repo, ".gitignore"), "w") as f:
        f.write(".work/\n")
    git(base, "init", "-q", "-b", "main", repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    git(repo, "worktree", "add", "-q", "-b", "feat/T-B", wt)
    work, wt_work = os.path.join(repo, ".work"), os.path.join(wt, ".work")
    task(work, "T-FIND", "Findings to decide", {**ALL_PASS, "security": "PASS_WITH_FINDINGS"},
         finding="the token reaches the log")
    task(work, "T-READY", "Ready to close", ALL_PASS)
    task(wt_work, "T-DONE", "Closed task", closed=True)
    now = time.time()
    held = []
    held.append(alert(work, "s-q", "question", held=True, heartbeat=now, qid="Q1",
                      questions=[{"question": "Which lane?", "header": "Lane", "multiSelect": False,
                                  "options": [{"label": "Light", "description": ""}, {"label": "Full", "description": ""}]}]))
    alert(work, "s-p", "permission", tool="Bash", detail="Bash: rm -rf build")
    alert(work, "s-turn", "turn", message="Contract written. Shall I go on?")
    alert(work, "s-idle", "turn", since=now - 300, message="Report written.")
    alert(work, "s-prog", "turn", message="Executor launched.")
    os.makedirs(os.path.join(work, "attention", "s-prog", ".running"))
    open(os.path.join(work, "attention", "s-prog", ".running", "agent-1"), "w").close()
    held.append(alert(work, "s-fold", "question", held=True, heartbeat=now, qid="QF",
                      questions=[{"question": "Findings T-FIND: which ones get fixed?", "header": "Findings", "multiSelect": True,
                                  "options": [{"label": "fix all", "description": ""}]}]))
    return repo, work, held


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(repo, port):
    # No forge token reaches the fixture's server: the test never calls a network.
    env = {k: v for k, v in os.environ.items() if not k.endswith("_TOKEN") and k not in ("FORGE_HOST", "GITLAB_HOST")}
    proc = subprocess.Popen([sys.executable, DASHBOARD, repo, str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            if proc.poll() is not None:
                raise Fail(f"server: dashboard.py exited: {proc.stderr.read().decode()[-500:]}")
            time.sleep(0.1)
    proc.kill()
    raise Fail("server: dashboard.py did not listen in 10 s")


def rows(page, group):
    return page.eval_on_selector_all(f'#needs [data-group="{group}"] .nlist > [data-row]', "els => els.map(e => e.dataset.row)")


def needs_step(page, ctx):
    """One list grouped by what the dev must do; the title, the count and the sidebar badges agree."""
    page.wait_for_selector('#needs [data-group="answer"]:not([hidden]) [data-row]')
    answer, approve = rows(page, "answer"), rows(page, "approve")
    decide, ship = rows(page, "decide"), rows(page, "ship")
    idle, progress = rows(page, "idle"), rows(page, "progress")
    check("needs: answer", sorted(r.split("/")[1] for r in answer) == ["s-q", "s-turn"], answer)
    check("needs: approve", [r.split("/")[1] for r in approve] == ["s-p"], approve)
    check("needs: idle and progress", [r.split("/")[1] for r in idle] == ["s-idle"] and [r.split("/")[1] for r in progress] == ["s-prog"],
          f"{idle} {progress}")
    check("needs: progress closed", page.eval_on_selector('#needs [data-group="progress"]', "e => !e.open"))
    n = len(answer) + len(approve) + len(decide) + len(ship)
    check("needs: title", page.title() == f"({n}) Forecrew", page.title())
    check("needs: count", page.inner_text("#needs-count").startswith(str(n)), page.inner_text("#needs-count"))
    badges = sum(int(b) for b in page.eval_on_selector_all("aside .badge", "els => els.map(e => e.textContent)") if b.strip())
    check("needs: badges", badges == n, f"{badges} != {n}")
    row = page.locator('#needs [data-group="answer"] [data-row*="s-q"]')
    check("needs: new dot", row.locator("[data-new]").is_visible())
    row.locator("[data-row-toggle]").click()
    check("needs: details", row.locator(".nrow-b").is_visible() and "Which lane?" in row.inner_text())
    check("needs: seen", not row.locator("[data-new]").is_visible())


def fold_step(page, ctx):
    """The held "Findings <ID>:" question of the main session folds into its task's Decide row."""
    decide = page.locator('#needs [data-group="decide"] [data-row^="find/"]')
    check("fold: decide row", decide.count() == 1 and "waiting for this decision" in decide.inner_text(), decide.all_inner_texts())
    check("fold: no answer row", not any("s-fold" in r for r in rows(page, "answer")), rows(page, "answer"))


def decide_step(page, ctx):
    """Findings are decided in one place: "Decide in Steps" opens the steps view at the finding,
    shown whole; Fix stages a choice and writes nothing; "Send 1 decision(s)" writes its line, and
    with every finding decided the folded "Findings <ID>:" question gets its free-text answer."""
    dec = os.path.join(ctx["work"], "T-FIND", "findings-decision.md")
    page.click('#needs [data-row^="find/"] [data-decide]')
    f = page.locator("#tree .finding.needs-you")
    f.wait_for()
    check("decide: steps view", page.locator("#tree").is_visible() and "the security detail line" in f.inner_text(), f.inner_text())
    f.locator('[data-stage="fix"]').click()
    page.wait_for_selector('#tree [data-stage="fix"][aria-pressed="true"]')
    check("decide: staged, nothing written", not os.path.exists(dec))
    page.click("#tree [data-send-decisions]")
    page.wait_for_selector("#tree [data-told], #tree [data-tell]")
    text = open(dec).read()
    check("decide: line written", text.startswith("Decided:") and "- fix medium security [" in text, text)
    answer = os.path.join(ctx["work"], "attention", "s-fold", "main.answer.json")
    for _ in range(50):
        if os.path.exists(answer):
            break
        time.sleep(0.1)
    got = json.load(open(answer)) if os.path.exists(answer) else {}
    check("decide: folded question answered", (got.get("answers") or [{}])[0].get("other", "").startswith("findings decided on the dashboard for T-FIND"), got)
    check("decide: other question untouched", not os.path.exists(os.path.join(ctx["work"], "attention", "s-q", "main.answer.json")))


def side_width(page):
    return page.evaluate("document.getElementById('side').getBoundingClientRect().width")


def sidebar_step(page, ctx):
    """One row per task, grouped only where a worktree has several; the filter on "/", the arrow
    keys and Enter; the edge resizes within its limits and keeps the chosen width; the rail; the
    gear's popover of switches closes on Escape and gives the focus back."""
    ids = page.eval_on_selector_all("#tasks .task", "els => els.map(e => e.dataset.id)")
    check("side: one row per task", sorted(ids) == ["T-DONE", "T-FIND", "T-READY"], ids)
    check("side: grouped only with several tasks", page.locator("#tasks .wt").count() == 1
          and page.locator('#tasks .task[data-id="T-DONE"] .sub').count() == 1)
    page.keyboard.press("Escape")
    page.locator("body").click(position={"x": 900, "y": 5})
    page.keyboard.press("/")
    check("side: / focuses the filter", page.evaluate("document.activeElement.id") == "side-filter")
    page.keyboard.type("ready")
    check("side: filter", page.eval_on_selector_all("#tasks .task", "els => els.map(e => e.dataset.id)") == ["T-READY"])
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_function("location.hash.endsWith('/T-READY')")
    check("side: arrow and Enter open a task", True)
    page.fill("#side-filter", "")
    page.dispatch_event("#side-filter", "input")
    w0 = side_width(page)
    page.focus("#side-grip")
    page.keyboard.press("ArrowRight")
    check("side: grip by keyboard", abs(side_width(page) - (w0 + 16)) < 2, f"{w0} -> {side_width(page)}")
    page.evaluate("chooseSide(500)")
    page.set_viewport_size({"width": 760, "height": 900})
    page.wait_for_timeout(300)
    check("side: clamped to 60% of the window", abs(side_width(page) - 456) < 2,
          (side_width(page), page.evaluate("[innerWidth, document.querySelector('.app').style.cssText]")))
    page.set_viewport_size({"width": 1400, "height": 900})
    page.wait_for_timeout(300)
    check("side: the chosen width returns", abs(side_width(page) - 500) < 2, side_width(page))
    page.dblclick("#side-grip")
    check("side: double click resets", abs(side_width(page) - 290) < 2, side_width(page))
    page.click("#side-collapse")
    check("side: rail", side_width(page) < 60 and page.locator("#tasks .sdot.amber").count() >= 1)
    page.click("#side-collapse")
    page.click("#side-gear")
    check("side: gear popover", page.locator("#side-pop").is_visible() and page.locator("#side-pop [data-switch]").count() >= 2)
    page.keyboard.press("Escape")
    check("side: Escape closes and returns focus", page.locator("#side-pop").is_hidden()
          and page.evaluate("document.activeElement.id") == "side-gear",
          (page.locator("#side-pop").is_hidden(), page.evaluate("document.activeElement.outerHTML.slice(0, 80)")))


def menu_step(page, ctx):
    """One settings menu: closed until opened, the language switch inside it, Escape closes it."""
    check("menu: closed", page.locator("#lang-btn").is_hidden())
    page.click("#menu-btn")
    check("menu: open", page.locator("#lang-btn").is_visible() and page.get_attribute("#menu-btn", "aria-expanded") == "true")
    page.click("#lang-btn")
    page.wait_for_function("document.documentElement.lang === 'pt-BR'")
    page.click("#lang-btn")
    page.wait_for_function("document.documentElement.lang === 'en'")
    page.keyboard.press("Escape")
    check("menu: Escape closes and returns focus", page.locator("#menu").is_hidden() and page.evaluate("document.activeElement.id") == "menu-btn")


def fold_hint_step(page, ctx):
    """A turn's long message is capped and scrolled to its end; a capped box that is not at its end fades."""
    row = page.locator('#needs [data-row*="s-turn"]')
    row.locator("[data-row-toggle]").click()
    box = row.locator("[data-turn-msg]")
    check("fold: message whole", "Shall I go on?" in box.inner_text())
    page.evaluate("""() => { const el = document.querySelector('#needs [data-row*="s-turn"] [data-turn-msg]');
      el.textContent = 'line\\n'.repeat(80) + el.textContent; el.scrollTop = 0; foldHints() }""")
    check("fold: hint on a capped box", "fold" in box.get_attribute("class") and "at-end" not in box.get_attribute("class"), box.get_attribute("class"))


STEPS = [needs_step, fold_step, decide_step, sidebar_step, menu_step, fold_hint_step]


def main():
    base = tempfile.mkdtemp(prefix="page-browser-")
    # The registry and the private key go to a temporary home, never the dev's ~/.forecrew.
    os.environ["FORECREW_HOME"] = os.path.join(base, "home")
    proc, beat = None, threading.Event()
    try:
        repo, work, held = fixture(base)
        for path in held:
            threading.Thread(target=keep_held, args=(path, beat), daemon=True).start()
        port = free_port()
        proc = serve(repo, port)
        key = subprocess.run([sys.executable, os.path.join(KIT, "hooks", "flow.py"), "page-key"],
                             capture_output=True, text=True, check=True).stdout.strip()
        ctx = {"repo": repo, "work": work, "url": f"http://127.0.0.1:{port}/?k={key}"}
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900}, locale="en-US")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(ctx["url"])
            for step in STEPS:
                step(page, ctx)
            check("no page errors", not errors, errors)
            browser.close()
        print("test_page_browser: ok")
    except Fail as e:
        print(f"FAIL  {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # a wait that timed out: the element or the condition never came
        print(f"FAIL  {type(e).__name__}: {str(e).splitlines()[0]}", file=sys.stderr)
        sys.exit(1)
    finally:
        beat.set()
        if proc:
            proc.terminate()
            proc.wait(timeout=5)
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
