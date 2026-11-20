#!/usr/bin/env python3
"""Merge order of the branches (MRs) open at the same time, computed from git alone.

Usage: merge-order.py [--base <remote/branch>] [--json] [branch ...]
       (default base: the remote's default branch, origin/HEAD, else origin/main)

Without branches it takes the ones checked out in the worktrees of this repository that
have commits the base does not, or uncommitted changes: a running task often has all its work
uncommitted, so a worktree's changed files (`git status`) count with its committed diff, and a
branch with only uncommitted work is marked "(not committed yet)". For each pair it says why
one goes before the other:

  stacked   B was cut from A (A's tip is in B): A merges first, or B's MR carries A's diff.
  overlap   both change the same file and neither contains the other: the one that overlaps
            fewer branches merges first (ties: the one that started first), and the other
            rebases on the base and re-runs its pipeline. A branch that overlaps two others
            waits for both and rebases once.

A branch with neither is independent and merges in any order. The order is printed as a
numbered list, the same text that goes into the "Merge order" section of each PR or MR.
"""
import argparse
import json
import os
import subprocess
import sys


def git(*args, check=True, cwd=None):
    run = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    if check and run.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {run.stderr.strip()}")
    return run


def worktrees():
    """{branch: worktree path} of the worktrees with a branch checked out."""
    out, found, path = git("worktree", "list", "--porcelain").stdout, {}, None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch "):
            found[line[len("branch "):].removeprefix("refs/heads/")] = path
    return found


def worktree_branches():
    return list(worktrees())


def uncommitted_files(path):
    """Files changed and not committed in a worktree: staged, unstaged and untracked (each file
    of a new directory, not the directory), both sides of a rename. Ignored files do not count."""
    if not path:
        return set()
    run = git("-C", path, "status", "--porcelain", "-z", "--untracked-files=all", check=False)
    if run.returncode != 0:
        return set()
    out, entries, i = set(), run.stdout.split("\0"), 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        out.add(entry[3:])
        if entry[0] in "RC":  # -z puts the source of a rename or copy in the next entry
            if i < len(entries) and entries[i]:
                out.add(entries[i])
            i += 1
    return out


def started_at(base, branch, path):
    """When the work began: the first commit ahead of the base, else when the worktree was
    created (its .git file), else 0."""
    first = first_commit_time(base, branch)
    if first or not path:
        return first
    try:
        return int(os.stat(os.path.join(path, ".git")).st_mtime)
    except OSError:
        return 0


def ahead(base, branch):
    return int(git("rev-list", "--count", f"{base}..{branch}").stdout.strip() or 0)


def first_commit_time(base, branch):
    times = git("log", "--format=%ct", "--reverse", f"{base}..{branch}").stdout.split()
    return int(times[0]) if times else 0


def changed_files(base, branch):
    return set(git("diff", "--name-only", f"{base}...{branch}").stdout.split())


def is_ancestor(a, b):
    return git("merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def plan(base, branches, paths=None):
    """Returns (order, edges, independent, pending): order is the merge list, edges the reasons,
    pending the branches whose work is only uncommitted. paths maps a branch to its worktree,
    whose uncommitted changes count with the committed ones."""
    paths = paths or {}
    names = list(dict.fromkeys(branches))
    count = {b: ahead(base, b) for b in names}
    dirty = {b: uncommitted_files(paths.get(b)) for b in names}
    live = [b for b in names if count[b] > 0 or dirty[b]]
    pending = sorted(b for b in live if count[b] == 0)
    started = {b: started_at(base, b, paths.get(b)) for b in live}
    # Sorted, so the answer does not depend on the order the branches were named in.
    live.sort(key=lambda x: (started[x], x))
    files = {b: (changed_files(base, b) if count[b] else set()) | dirty[b] for b in live}
    pairs = []  # (a, b, kind, detail), the overlap direction decided once every overlap is known
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            # A branch with nothing committed sits on the base: it is no one's parent.
            if count[a] and is_ancestor(a, b) and not is_ancestor(b, a):
                pairs.append((a, b, "stacked", f"{b} was cut from {a}"))
            elif count[b] and is_ancestor(b, a) and not is_ancestor(a, b):
                pairs.append((b, a, "stacked", f"{a} was cut from {b}"))
            else:
                common = sorted(files[a] & files[b])
                if common:
                    shown = ", ".join(common[:5]) + (f" (+{len(common) - 5})" if len(common) > 5 else "")
                    pairs.append((a, b, "overlap", shown))
    overlaps = {b: sum(1 for p in pairs if p[2] == "overlap" and b in p[:2]) for b in live}
    edges = []  # (first, then, kind, detail)
    for a, b, kind, detail in pairs:
        if kind == "stacked":
            edges.append((a, b, kind, detail))
            continue
        # The branch that overlaps more waits and rebases once onto all of them.
        first, then = sorted((a, b), key=lambda x: (overlaps[x], started[x], x))
        edges.append((first, then, "overlap", f"both change {detail}; rebase {then} after {first} merges"))
    # Kahn's sort, ties broken by the branch that started first.
    before = {b: set() for b in live}
    for first, then, _, _ in edges:
        before[then].add(first)
    order, left = [], set(live)
    while left:
        ready = sorted((b for b in left if not (before[b] & left)), key=lambda x: (started[x], x))
        if not ready:  # a cycle cannot come from ancestry; overlap edges follow start time
            ready = sorted(left, key=lambda x: (started[x], x))
        order.append(ready[0])
        left.discard(ready[0])
    linked = {b for e in edges for b in e[:2]}
    return order, edges, [b for b in order if b not in linked], pending


def default_base():
    ref = git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False).stdout.strip()
    return ref or "origin/main"


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--base", default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("branches", nargs="*")
    args = p.parse_args()
    args.base = args.base or default_base()
    paths = worktrees()
    branches = args.branches or [b for b in paths if b != args.base.split("/")[-1]]
    order, edges, independent, pending = plan(args.base, branches, paths)
    if args.json:
        print(json.dumps({"base": args.base, "order": order, "independent": independent, "pending": pending,
                          "edges": [dict(zip(("first", "then", "kind", "detail"), e)) for e in edges]}, indent=2))
        return 0
    if not order:
        print(f"no branch ahead of {args.base} and no uncommitted work")
        return 0
    print(f"Merge order into {args.base}:")
    for n, b in enumerate(order, 1):
        why = [f"after {f} ({k}: {d})" for f, t, k, d in edges if t == b]
        print(f"  {n}. {b}" + (" (not committed yet)" if b in pending else "")
              + ("  independent, any order" if b in independent else "")
              + "".join(f"\n       {w}" for w in why))
    return 0


if __name__ == "__main__":
    sys.exit(main())
