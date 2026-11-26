#!/usr/bin/env python3
"""Prints only the learnings whose Tags line matches, so an agent loads its lens, not the whole file.

Usage: learnings.py --lens <lens>      entries with the tags of a lens in flow.json (what agents call)
       learnings.py <tag> [tag...]     entries with any of the tags
       learnings.py --untagged         entries nobody will ever load (fix them)
       learnings.py --tags             the tags in use, with counts
       learnings.py --search <text>    prior work, best first: learnings, decisions, finished tasks and
                                       brain pages (BM25 on the words; by meaning with "embeddings")
       learnings.py --index <ID>       appends the task to the tasks file, from its 00-purpose.md
                                       (once; a second run changes nothing)
Paths come from .claude/flow.json ("learnings", "decisions", "tasks", "brain", "work_dir").

"embeddings" in flow.json turns on search by meaning: {"command": "...", "min_similarity": 0.3}.
The command reads a JSON array of strings on stdin and prints a JSON array of vectors (one per
string). Vectors of the notes are cached in <work_dir>/embeddings.json. A command that fails falls
back to BM25 and says so on stderr.
"""
import collections
import datetime
import glob
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import unicodedata

DEFAULTS = {"decisions": ".claude/DECISIONS.md", "tasks": ".claude/TASKS.md", "brain": "docs/brain"}
KINDS = ("learnings", "decisions", "tasks")
LIMIT = 10
MAX_PAGE = 256 * 1024
MAX_PAGES = 2000
STOP = set("""a an and are as at be by do does for from has have how in is it its of on or so that the
this to was we what when where which who why will with o os as um uma de da do das dos e em no na nos
nas por para pra com que se ao à é foi ser como mais mas sem sobre""".split())


def flow_at(root):
    with open(os.path.join(root, ".claude", "flow.json")) as f:
        return json.load(f)


def path_of(root, flow, key):
    return os.path.join(root, os.path.expanduser(flow.get(key) or DEFAULTS.get(key, "")))


def entries(path):
    if not os.path.isfile(path):
        return
    text = open(path, errors="replace").read()
    # Entries start at "## <slug>" outside fenced blocks (the template inside ``` is skipped).
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for block in re.split(r"(?m)^(?=## )", text):
        if not block.startswith("## "):
            continue
        m = re.search(r"^- \*\*Tags\*\*:\s*(.+)$", block, re.M)
        tags = {t.strip().lower() for t in m.group(1).split(",")} if m else set()
        yield block.rstrip() + "\n", tags


def brain_pages(root, flow):
    """The brain's pages: regular files under the folder, never a link that leads out of it."""
    bdir = path_of(root, flow, "brain")
    real = os.path.realpath(bdir)
    pages = []
    for page in sorted(glob.glob(os.path.join(bdir, "**", "*.md"), recursive=True)):
        rp = os.path.realpath(page)
        if os.path.islink(page) or not rp.startswith(real + os.sep) or not os.path.isfile(rp):
            continue
        # index.md and log.md describe the pages; they would match every search.
        if os.path.dirname(rp) == real and os.path.basename(rp) in ("index.md", "log.md"):
            continue
        if os.path.getsize(rp) > MAX_PAGE:
            continue
        pages.append(page)
        if len(pages) >= MAX_PAGES:
            break
    return pages


def notes(root, flow):
    """Everything the search reads, as {kind, source, title, text, tags}."""
    out = []
    for kind in KINDS:
        path = path_of(root, flow, kind)
        for block, tags in entries(path):
            out.append({"kind": kind, "source": os.path.relpath(path, root), "title": block.splitlines()[0][3:].strip(),
                        "text": block, "tags": sorted(tags)})
    for page in brain_pages(root, flow):
        text = open(page, errors="replace").read()
        m = re.search(r"^# (.+)$", text, re.M)
        title = m.group(1).strip() if m else os.path.splitext(os.path.basename(page))[0]
        tags = re.search(r"^Tags:\s*(.+)$", text, re.M)
        out.append({"kind": "brain", "source": os.path.relpath(page, root), "title": title,
                    "text": text.rstrip() + "\n", "tags": sorted({t.strip().lower() for t in tags.group(1).split(",")}) if tags else []})
    return out


def words(text):
    """Lower case, no accents, no stop words, a trailing plural s cut: "Invoices" finds "invoice"."""
    text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    out = []
    for w in re.findall(r"[a-z0-9]+", text):
        if len(w) < 2 or w in STOP:
            continue
        out.append(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def bm25(docs, query, k1=1.5, b=0.75):
    q = set(words(query))
    toks = [words(d) for d in docs]
    if not q or not toks:
        return [0.0] * len(docs)
    avg = sum(map(len, toks)) / len(toks) or 1
    df = collections.Counter(w for t in toks for w in set(t) & q)
    scores = []
    for t in toks:
        tf = collections.Counter(w for w in t if w in q)
        s = 0.0
        for w, n in tf.items():
            idf = math.log(1 + (len(toks) - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * n * (k1 + 1) / (n + k1 * (1 - b + b * len(t) / avg))
        scores.append(s)
    return scores


def run_embed(cfg, root, texts):
    p = subprocess.run(cfg["command"], shell=True, input=json.dumps(texts), capture_output=True, text=True,
                       timeout=cfg.get("timeout", 120), cwd=root)
    if p.returncode != 0:
        raise RuntimeError(f"exited {p.returncode}: {p.stderr.strip()[-300:]}")
    vecs = json.loads(p.stdout)
    if not (isinstance(vecs, list) and len(vecs) == len(texts)
            and all(isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v) for v in vecs)):
        raise RuntimeError("did not print one vector of numbers per string")
    return vecs


def embeddings(root, flow, texts):
    """Vectors of the texts, cached by command and text; None when off or failing."""
    cfg = flow.get("embeddings") or {}
    if not cfg.get("command"):
        return None
    cache_path = os.path.join(root, flow.get("work_dir", ".work"), "embeddings.json")
    try:
        cache = json.load(open(cache_path))
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    key = lambda t: hashlib.sha256((cfg["command"] + "\0" + t).encode()).hexdigest()
    try:
        missing = list(dict.fromkeys(t for t in texts if key(t) not in cache))
        if missing:
            for t, v in zip(missing, run_embed(cfg, root, missing)):
                cache[key(t)] = v
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            keep = {key(t) for t in texts}  # notes deleted since drop out of the cache
            tmp = cache_path + ".tmp"
            json.dump({k: v for k, v in cache.items() if k in keep}, open(tmp, "w"))
            os.replace(tmp, cache_path)
        return [cache[key(t)] for t in texts]
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"embeddings off for this search ({e}); searching by words", file=sys.stderr)
        return None


def cosine(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb and len(a) == len(b) else 0.0


def search(root, flow, query, limit=LIMIT, semantic=True):
    """(mode, [note with "score"]) best first. semantic=False never runs the embeddings command."""
    all_notes = notes(root, flow)
    scored, mode = None, "words"
    if semantic and all_notes:
        vecs = embeddings(root, flow, [n["text"] for n in all_notes])
        if vecs is not None:
            try:
                qv = run_embed(flow["embeddings"], root, [query])[0]
                floor = float(flow["embeddings"].get("min_similarity", 0.3))
                scored = [(cosine(qv, v), n) for v, n in zip(vecs, all_notes)]
                scored = [(s, n) for s, n in scored if s >= floor]
                mode = "meaning"
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
                print(f"embeddings off for this search ({e}); searching by words", file=sys.stderr)
    if scored is None:
        scored = [(s, n) for s, n in zip(bm25([n["text"] for n in all_notes], query), all_notes) if s > 0]
    scored.sort(key=lambda x: -x[0])
    return mode, [{**n, "score": round(s, 4)} for s, n in scored[:limit]]


def section(text, name):
    m = re.search(rf"(?ms)^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)", text)
    body = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S) if m else ""
    return [ln.rstrip() for ln in body.splitlines() if ln.strip()]


def index(root, flow, tid):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", tid) or tid.startswith("."):
        sys.exit(f"bad task id: {tid}")
    tdir = os.path.join(root, flow.get("work_dir", ".work"), tid)
    purpose_file = os.path.join(tdir, "00-purpose.md")
    if not os.path.isfile(purpose_file):
        sys.exit(f"no task {tid}: {purpose_file} is missing")
    out = path_of(root, flow, "tasks")
    if any(re.match(rf"## {re.escape(tid)}(:|\s|$)", b) for b, _ in entries(out)):
        print(f"{tid} already in {os.path.relpath(out, root)}")
        return 0
    text = open(purpose_file).read()
    title = re.sub(rf"^#\s*{re.escape(tid)}\s*", "", text.splitlines()[0]).strip() if text else ""
    purpose = " ".join(section(text, "Purpose")) or "(no purpose written)"
    criteria = [ln for ln in section(text, "Acceptance criteria") if re.match(r"-\s*AC-\d+", ln)]
    rulings = 0
    if os.path.isfile(os.path.join(tdir, "ledger.md")):
        rulings = sum(ln.startswith("- Ruling:") for ln in open(os.path.join(tdir, "ledger.md")))
    pr = ""
    if os.path.isfile(os.path.join(tdir, "mr.json")):
        try:
            pr = json.load(open(os.path.join(tdir, "mr.json"))).get("url", "")
        except (OSError, ValueError):
            pass
    lines = [f"## {tid}: {title}" if title else f"## {tid}",
             "- **Tags**: task",
             f"- **Closed**: {datetime.date.today().isoformat()}",
             f"- **Purpose**: {purpose}"]
    lines += ["- **Criteria**:"] + [f"  {c}" for c in criteria] if criteria else []
    lines.append(f"- **Rulings**: {rulings}" + (" (the approved ones are in the decisions file)" if rulings else ""))
    if pr:
        lines.append(f"- **PR**: {pr}")
    if not os.path.isfile(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "w").write("# Tasks\n\nOne entry per finished task, appended by `learnings.py --index <ID>`.\n")
    with open(out, "a") as f:
        f.write("\n" + "\n".join(lines) + "\n")
    print(f"{tid} added to {os.path.relpath(out, root)}")
    return 0


def main(args):
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    flow = flow_at(root)
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--search":
        if len(args) < 2:
            sys.exit("usage: learnings.py --search <text>")
        mode, found = search(root, flow, " ".join(args[1:]))
        for n in found:
            print(f"<!-- {n['source']} ({n['kind']}, {mode} {n['score']}) -->\n{n['text']}")
        if not found:
            print(f"nothing on: {' '.join(args[1:])}", file=sys.stderr)
        return 0
    if args[0] == "--index":
        if len(args) != 2:
            sys.exit("usage: learnings.py --index <ID>")
        return index(root, flow, args[1])
    all_entries = list(entries(os.path.join(root, flow["learnings"])))
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
