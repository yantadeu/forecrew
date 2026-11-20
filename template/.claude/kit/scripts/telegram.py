#!/usr/bin/env python3
"""Telegram bridge of Forecrew: what waits on the dev, on their phone, answered from there.

Usage: telegram.py run <root>        the bridge in the foreground (work.sh telegram start runs it
                                     in the background)
       telegram.py chat-id           prints the chat of each recent message to the bot, to find
                                     the value of FORECREW_TELEGRAM_CHAT

The bot token and the chat id come from the environment, never from a file:
FORECREW_TELEGRAM_TOKEN and FORECREW_TELEGRAM_CHAT. One bridge serves every project of the
registry (~/.forecrew/projects.json), like the dashboard.

While it runs, the bridge is an open page for the hooks (it touches each worktree's
attention/.page): a permission dialog is held for an answer from Telegram, and so are questions
and the session's turn where `work.sh ui answers on` / `turns on` is set. Each message carries
"Answer in the terminal", which releases the hold at once. Answers go through the dashboard's
own answer() and its checks: the alert must be held, with the same qid. Only updates from the
configured chat are read; anything else is ignored.

`"telegram": {"details": false}` in flow.json sends the kind of each alert without its detail
(the command of a permission, the text of a question or turn). Details are masked with the
hook's mask either way.
"""
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dashboard as D  # noqa: E402

TOKEN_ENV, CHAT_ENV = "FORECREW_TELEGRAM_TOKEN", "FORECREW_TELEGRAM_CHAT"
API = os.environ.get("FORECREW_TELEGRAM_API", "https://api.telegram.org").rstrip("/")
POLL_SECONDS = float(os.environ.get("FORECREW_TELEGRAM_POLL", "10"))
TEXT_MAX = 3500
ICONS = {"permission": "🖐", "question": "❓", "turn": "💬"}


class TelegramError(Exception):
    pass


def call(token, method, http_timeout=20, **params):
    """One Bot API call. The token is part of the URL, so no error text ever carries the URL."""
    data = json.dumps(params).encode()
    req = urllib.request.Request(f"{API}/bot{token}/{method}", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            desc = json.load(e).get("description", "")
        except (ValueError, OSError, AttributeError):
            desc = ""
        raise TelegramError(f"{method}: HTTP {e.code} {desc}".replace(token, "[masked]")) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise TelegramError(f"{method}: {type(e).__name__}: {str(e).replace(token, '[masked]')}") from None
    if not isinstance(body, dict) or not body.get("ok"):
        raise TelegramError(f"{method}: {str((body or {}).get('description', 'not ok')).replace(token, '[masked]')}")
    return body.get("result")


def current_task(wdir):
    try:
        with open(os.path.join(wdir, "current")) as f:
            tid = f.read().strip()
    except OSError:
        return ""
    return tid if D.ID_RX.fullmatch(tid or "") else ""


def touch_page(wdir):
    adir = os.path.join(wdir, "attention")
    if not os.path.isdir(adir):
        return
    try:
        with open(os.path.join(adir, ".page"), "a"):
            pass
        os.utime(os.path.join(adir, ".page"))
    except OSError:
        pass


def details_on(root):
    flow = D.read_json(os.path.join(root, ".claude", "flow.json"))
    tg = flow.get("telegram") if isinstance(flow, dict) else None
    return not (isinstance(tg, dict) and tg.get("details") is False)


def wants_you(a):
    """A turn that only reports is not pinged: the page shows it as idle, and so does the phone."""
    return a["kind"] != "turn" or D._FLOW.asks(a.get("message") or a.get("detail") or "")


def single_pick(a):
    qs = a.get("questions") or []
    return len(qs) == 1 and isinstance(qs[0], dict) and not qs[0].get("multiSelect") and qs[0].get("options")


def render(ref, a, details):
    """(text, buttons) of one alert. Buttons only while the hook holds it for an answer."""
    head = f"{ICONS[a['kind']]} <b>{html.escape(ref['project'])}</b>"
    if ref["task"]:
        head += f" · {html.escape(ref['task'])}"
    head += f" · {html.escape(ref['agent'] if ref['agent'] != 'main' else 'main session')}"
    lines = [head]
    if a["kind"] == "permission":
        lines.append(f"wants to run <b>{html.escape(a.get('tool') or 'a tool')}</b>")
        if details and a.get("detail"):
            lines.append(f"<code>{html.escape(a['detail'][:TEXT_MAX])}</code>")
    elif a["kind"] == "question":
        for q in (a.get("questions") or [])[:4]:
            if not isinstance(q, dict):
                continue
            lines.append(f"<b>{html.escape(str(q.get('question') or ''))}</b>" if details else "asks a question")
            if details:
                for i, o in enumerate(q.get("options") or []):
                    label = o.get("label", "") if isinstance(o, dict) else str(o)
                    lines.append(f"{i + 1}. {html.escape(str(label))}")
    else:
        msg = a.get("message") or a.get("detail") or ""
        lines.append(html.escape(msg[-TEXT_MAX:]) if details else "waits for your next message")
    held, buttons = a.get("held"), []
    if held and a["kind"] == "permission":
        buttons.append([{"text": "Allow", "data": "allow"}, {"text": "Deny", "data": "deny"}])
    elif held and a["kind"] == "question" and single_pick(a):
        opts = a["questions"][0]["options"]
        buttons += [[{"text": str(o.get("label", "") if isinstance(o, dict) else o)[:60], "data": f"o{i}"}]
                    for i, o in enumerate(opts[:8])]
    elif held and a["kind"] == "question":
        lines.append("<i>Several questions or picks: answer on the dashboard or in the terminal.</i>")
    elif held and a["kind"] == "turn":
        lines.append("<i>Reply to this message to send the session your next message.</i>")
    if held:
        buttons.append([{"text": "Answer in the terminal", "data": "release"}])
    else:
        lines.append("<i>Answer in the terminal.</i>")
    return "\n".join(lines), buttons


class Bridge:
    def __init__(self, token, chat, own):
        self.token, self.chat, self.own = token, str(chat), own
        self.sent = {}       # alert key -> {"msg", "ref", "kind", "view", "n"}
        self.by_n = {}       # short number in callback data -> alert key
        self.by_msg = {}     # Telegram message id -> alert key (replies to a turn)
        self.next_n = 1
        self.offset = None

    def api(self, method, **params):
        return call(self.token, method, **params)

    def markup(self, n, buttons):
        rows = [[{"text": b["text"], "callback_data": f"{n}:{b['data']}"} for b in row] for row in buttons]
        return {"inline_keyboard": rows}

    def scan(self, now=None):
        """Sends what is new, updates what changed, and closes what is gone."""
        now = time.time() if now is None else now
        seen = set()
        for root in D.project_roots(self.own):
            details = details_on(root)
            for i, (wt, _branch) in enumerate(D.worktrees(root)):
                wdir = D.work_dir(wt)
                if not wdir:
                    continue
                touch_page(wdir)
                for a in D.alerts(wdir, now):
                    if not wants_you(a):
                        continue
                    key = f"{root}\0{i}\0{a['session']}\0{a['agent']}\0{a.get('qid') or a['since']}"
                    seen.add(key)
                    ref = {"root": root, "wt": i, "session": a["session"], "agent": a["agent"], "qid": a.get("qid"),
                           "project": os.path.basename(root), "task": current_task(wdir)}
                    view = render(ref, a, details)
                    s = self.sent.get(key)
                    if s is None:
                        n = self.next_n
                        self.next_n += 1
                        msg = self.api("sendMessage", chat_id=self.chat, text=view[0], parse_mode="HTML",
                                       reply_markup=self.markup(n, view[1]))
                        self.sent[key] = {"msg": msg["message_id"], "ref": ref, "kind": a["kind"], "view": view, "n": n,
                                          "single": bool(single_pick(a))}
                        self.by_n[n], self.by_msg[msg["message_id"]] = key, key
                    elif s["view"] != view:
                        self.edit(s, view[0], view[1])
                        s["view"] = view
        for key in [k for k in self.sent if k not in seen]:
            s = self.sent.pop(key)
            self.by_n.pop(s["n"], None)
            self.by_msg.pop(s["msg"], None)
            if not s.get("done"):
                self.edit(s, s["view"][0] + "\n<i>No longer waiting (answered elsewhere, or the session moved on).</i>", [])

    def edit(self, s, text, buttons):
        try:
            self.api("editMessageText", chat_id=self.chat, message_id=s["msg"], text=text, parse_mode="HTML",
                     reply_markup=self.markup(s["n"], buttons))
        except TelegramError:
            pass  # an old message Telegram no longer edits: nothing to do

    def ours(self, chat):
        return isinstance(chat, dict) and str(chat.get("id")) == self.chat

    def handle(self, update):
        cb = update.get("callback_query")
        if isinstance(cb, dict):
            if not self.ours((cb.get("message") or {}).get("chat")):
                return
            self.on_button(cb)
            return
        m = update.get("message")
        if isinstance(m, dict) and self.ours(m.get("chat")) and isinstance(m.get("text"), str):
            reply = (m.get("reply_to_message") or {}).get("message_id")
            key = self.by_msg.get(reply)
            s = self.sent.get(key) if key else None
            if s and s["kind"] == "turn":
                self.answer(s, {"message": m["text"]}, "✅ Sent to the session.")
            elif not m["text"].startswith("/start"):
                self.api("sendMessage", chat_id=self.chat, text="To answer a session, reply to its message.")

    def on_button(self, cb):
        n, _, act = str(cb.get("data") or "").partition(":")
        key = self.by_n.get(int(n)) if n.isdigit() else None
        s = self.sent.get(key) if key else None
        if s is None:
            self.api("answerCallbackQuery", callback_query_id=cb.get("id"), text="This is no longer waiting.")
            return
        if act == "release":
            body, done = {"release": True}, "↩ Handed back to the terminal."
        elif act in ("allow", "deny") and s["kind"] == "permission":
            body, done = {"behavior": act}, "✅ Allowed." if act == "allow" else "⛔ Denied."
        elif act[:1] == "o" and act[1:].isdigit() and s["kind"] == "question" and s["single"]:
            body, done = {"answers": [{"options": [int(act[1:])], "other": ""}]}, "✅ Answered."
        else:
            self.api("answerCallbackQuery", callback_query_id=cb.get("id"), text="Not a valid answer.")
            return
        code = self.answer(s, body, done)
        self.api("answerCallbackQuery", callback_query_id=cb.get("id"),
                 text=done if code == 200 else "This is no longer waiting.")

    def answer(self, s, body, done):
        ref = s["ref"]
        code, why = D.answer(ref["root"], dict(body, wt=ref["wt"], session=ref["session"], agent=ref["agent"], qid=ref["qid"]))
        if code == 200:
            s["done"] = True
            self.edit(s, s["view"][0] + f"\n<b>{html.escape(done)}</b>", [])
        else:
            self.edit(s, s["view"][0] + f"\n<i>Not sent: {html.escape(why)}.</i>", [])
        return code

    def poll(self, timeout):
        params = {"timeout": int(timeout), "allowed_updates": ["message", "callback_query"]}
        if self.offset is not None:
            params["offset"] = self.offset
        for u in self.api("getUpdates", http_timeout=timeout + 10, **params) or []:
            self.offset = u["update_id"] + 1
            try:
                self.handle(u)
            except TelegramError as e:
                print(f"forecrew telegram: {e}", file=sys.stderr)

    def step(self, wait=0):
        self.scan()
        self.poll(wait)


def credentials():
    token, chat = os.environ.get(TOKEN_ENV, ""), os.environ.get(CHAT_ENV, "")
    if not token:
        print(f"forecrew telegram: set {TOKEN_ENV} (from @BotFather) in the shell that starts the bridge.", file=sys.stderr)
        sys.exit(2)
    return token, chat


def run(root):
    token, chat = credentials()
    if not chat:
        print(f"forecrew telegram: set {CHAT_ENV}; send your bot a message, then: work.sh telegram chat-id", file=sys.stderr)
        return 2
    D.register(root)
    b = Bridge(token, chat, root)
    # Old updates are not answers to anything this bridge sent.
    try:
        pending = b.api("getUpdates", offset=-1)
        if pending:
            b.offset = pending[-1]["update_id"] + 1
    except TelegramError as e:
        print(f"forecrew telegram: {e}", file=sys.stderr)
        return 1
    print("forecrew telegram: bridge running", flush=True)
    while True:
        try:
            # A short long-poll keeps the page heartbeat fresh (the hold gives up after 10 s).
            b.step(wait=min(POLL_SECONDS, 3))
        except TelegramError as e:
            print(f"forecrew telegram: {e}", file=sys.stderr, flush=True)
            time.sleep(5)


def chat_id():
    token, _ = credentials()
    try:
        updates = call(token, "getUpdates")
    except TelegramError as e:
        print(f"forecrew telegram: {e}", file=sys.stderr)
        return 1
    chats = {}
    for u in updates or []:
        c = (u.get("message") or {}).get("chat") or {}
        if "id" in c:
            chats[c["id"]] = c.get("username") or c.get("title") or c.get("first_name") or ""
    if not chats:
        print("No message yet: send your bot any message in Telegram, then run this again.")
        return 1
    for cid, name in chats.items():
        print(f"{cid}\t{name}")
    print(f"export {CHAT_ENV}=<the id above>")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["run"] and len(sys.argv) == 3:
        sys.exit(run(os.path.realpath(sys.argv[2])))
    if sys.argv[1:] == ["chat-id"]:
        sys.exit(chat_id())
    print(__doc__, file=sys.stderr)
    sys.exit(2)
