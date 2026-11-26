---
name: task
description: Entry point for implementation work. Turns a task from any tracker (or a plain request) into a purpose with numbered acceptance criteria, picks the lane, resolves open questions one at a time, and runs refiner, executor, tester, four parallel review lenses and a retrospective, with state in .work/<ID>/. Works without any tracker: a plain description is enough. Use when the dev asks to start, implement, fix or change something, or types /task.
argument-hint: "<ticket id, link, or just what you want done>"
---

# Agent flow

Input: `$ARGUMENTS`.

The defects this flow prevents: a decision made without being asked, a purpose lost when the
conversation gets summarized, and a cross-cutting concern (security, QA, product) reviewed as
the last item of someone else's checklist. The protocol every agent follows is
`.claude/kit/PROTOCOL.md`.

## 1. Read before asking

1. **The task.** The input is one of three things:
   - **A ticket id or link** (`PROJ-123`, a URL). Find the tracker in
     `.claude/product-sources.md` and read the task with whatever reaches it (an MCP connector,
     a CLI, a URL). Nothing reaches it: ask the dev to paste the task and its acceptance
     criteria.
   - **A plain request** (`/task add CSV export to the report page`), the normal case in a
     repository with no tracker. Do not ask for a ticket and do not offer `/flow-setup
     tracker`. The acceptance criteria come from the interview instead of a ticket: propose
     them from the request and the code, and the dev confirms or corrects them in the triage.
   - **Nothing** (`/task` alone): ask what the dev wants done, in one question.

   Without a ticket the ID is a short slug of the request (`csv-export`), proposed in the
   triage question; if `.work/` already has it, add a suffix (`csv-export-2`). The ID only names
   the work directory and is matched in branch names and PR/MR titles, so suggest a branch that
   contains it (`feat/csv-export`).
2. **Product sources.** Sync the sources of `.claude/product-sources.md` that decide the area.
   The registry is empty: say so, and offer `/product-source` before going on.
3. **Learnings, prior work and code.** `python3 .claude/kit/scripts/learnings.py <tags of the
   area>` and `learnings.py --search <key words of the request>` (past tasks, kept decisions,
   brain pages), then locate the code the task touches. A fact the code or the prior work
   answers does not become a question; a similar past task is worth naming in the triage.

## 2. Triage: one short round

Two to four numbered questions, each with your recommendation and why, only about what would
change the lane: does it touch an irreversible step, sensitive data or authentication, an
external contract, or does the request have two readings that lead to different work?

| Lane | When | Stages |
| --- | --- | --- |
| **Full** | irreversible, regulated, or an external contract | full interview, Given/When/Then criteria and edge cases, then all stages |
| **Light** | real behavior change with one clear reading | all stages |
| **None** | trivial, mechanical, no behavior change | implement, then the review lenses |

Also classify the change: **code**, **config**, **docs** or **mixed**. A docs-only change skips
the QA lens; nothing skips the security lens. Record a skipped lens as a ruling in `ledger.md`.

## 3. Write the purpose

Close the triage with `AskUserQuestion`: one option per lane, the recommended one first with its
label ending in "(Recommended)" and the why in its description. A question can be answered from
the dashboard when the dev opted in; a free-text "ok" cannot. Then:

```
bash .claude/kit/scripts/work.sh init <ID> "<title>"
```

Fill `00-purpose.md`: the `Lane:` line, every acceptance criterion **copied, not summarized**,
one per line as `- AC-001: ...` (Full lane: Given / When / Then, plus edge cases), the decisions
the dev made out loud with the why, and what stays out. The ids are fixed from here on: every
stage cites them and the gates check that none is left uncovered.

**Dashboard.** Once per session, before the first stage, ask the dev with `AskUserQuestion`:
"Open the live dashboard of the agents?" with "Yes, open it (Recommended)" and "No". On yes,
run `bash .claude/kit/scripts/work.sh ui start --open`: it starts in the background, returns at
once and opens the dev's browser on the page (its link carries a key you never need to see). If
it says there is no browser opener, ask the dev to run `bash .claude/kit/scripts/work.sh ui
start` in their own terminal. Never read or print the link's key. It follows whichever task is
current, so do not ask again in the same session.
`work.sh ui stop` stops it.

## 4. Contract and clarification

`Agent(refiner, "work dir .work/<ID>")` writes `01-contract.md`. Where it found a real open
choice it wrote `[NEEDS CLARIFICATION: <question>]`, and the executor cannot start until none is
left. Resolve them with the dev:

- **One question at a time**, at most five in total. Multiple choice (2 to 5 options, your
  recommendation first and marked) or a short answer with your suggestion. "ok" accepts the
  recommendation.
- Write each answer into `00-purpose.md` under `## Clarifications`, `### Session <YYYY-MM-DD>`,
  as `- Q: <question> -> A: <answer>`, and update the criterion or decision it changes.
- Re-run the refiner on the same work directory. It replaces the markers with the answers.

More than five open questions means the task is not ready: say so and stop.

## 5. Implement, prove, review

```
Agent(executor, "work dir .work/<ID>")  → 02-change.md
Agent(tester,   "work dir .work/<ID>")  → 03-proof.md
bash .claude/kit/scripts/work.sh review-package    → review.diff, checks.md
in parallel, one message:
  Agent(reviewer) · Agent(security-reviewer) · Agent(qa-reviewer) · Agent(product-reviewer)
                                        → 04-review-<lens>.md
```

These are the default stages. The flow is what `stages` of `.claude/flow.json` says, in its
order: run every stage without `"verdict"` one after the other (a stage the dev added with
`/flow-agent`, such as a migration planner before the executor, runs at its place), then
`review-package`, then every stage with `"verdict": true` in parallel, in one message, as a
review lens.

- `review-package` also runs the project's checks (`checks` in `flow.json`) and writes
  `checks.md`. Exit 1 means one failed: the reviewers are refused until the checks pass on the
  current code, so send the change back to the executor with the failing check (it counts as a
  fix round). A check that cannot run (tool missing, timeout) is a failure too: take it to the
  dev when the executor cannot fix it, never remove the check to get past it.
- Each prompt carries the work directory and only what is not on disk. Never paste a summary
  of the contract: the file is the contract.
- Route on the first line of each answer, not on its prose:
  `DONE` go on; `DONE_WITH_CONCERNS` read the concerns, then go on or ask the dev;
  `NEEDS_CONTEXT` give what is missing and re-run the same stage; `BLOCKED` take it to the dev.
- In Claude Code the hook refuses to launch a stage before the stages it requires pass, and
  sends a stage back once when its file is incomplete. Elsewhere, run
  `bash .claude/kit/scripts/work.sh status` before each next stage: it shows the same checks
  and what is next.
- Stages that write never run in parallel on the same tree. Reviewers do, because none edits code.

## 6. Fix loop

Each finding carries `[route: refiner|executor|tester]`. Send critical and important findings
back to that stage with the finding text, then re-run the contract reviewer and the lenses whose
last review had findings, on a fresh `review-package` (a lens whose last review was a PASS is
not required again). Minor findings go to the dev's list, not to a round.

After `max_fix_rounds` executor rounds (flow.json, default 3) the hook refuses another one:
take the open findings to the dev with your recommendation.

## 7. Findings decision, retrospective, PR/MR

Four verdicts in is not "done" (PROTOCOL.md, "Closing a task").

**Findings decision.** When any lens gives PASS_WITH_FINDINGS, the dev decides which findings
get fixed. Never send findings to be fixed without this question.

The dev may decide them on the Forecrew dashboard instead, one "Fix" or "Accept" per finding:
the page writes each line of `findings-decision.md` and your next prompt or session receives the
decisions as context. Apply them as if the dev had answered the question below, and do not ask
about those findings again.

1. Read the review files and list every finding: severity plus one line, the ones you
   recommend fixing first, each of their labels ending in "(Recommended)".
2. Ask with `AskUserQuestion`, `multiSelect: true`, one option per finding, each question's text
   starting with exactly `Findings <ID>:`. The tool takes at most 4 options per question: with
   more than 4 findings, split them across questions (up to 4 per call, more calls if needed) so
   none is dropped; a finding left off the list is not "accepted", it was never seen. On the
   dashboard this question folds into the task's Decide row and the dev decides in the steps
   view, which answers it once every finding is decided. When the dev prefers the dashboard, end
   your turn instead with exactly `Decide the findings of <ID> in the dashboard's Steps (or answer
   here).` and nothing else: only that whole message folds into the Decide row.
3. The checked findings go to the stage their route names, then the lenses again (step 6); the
   unchecked ones are recorded as accepted in `00-purpose.md`, under "Decisions from the
   interview", with the date and the dev's reason when given.
4. Write (or, after a page decision, complete) `.work/<ID>/findings-decision.md`: first line
   `Decided: YYYY-MM-DD`, then one line per finding, `- fix|accepted <severity> <lens> [<key>]:
   <one line>`, the key copied from `bash .claude/kit/scripts/work.sh findings <ID>` (one key per
   finding; a line without it decides nothing once the lens re-runs). The dashboard shows
   `findings` until this file is at least as new as every review and names every finding, so a
   lens re-run reopens the decision: ask again for the new findings. The dev can also decide a
   finding on the dashboard, which appends its line to the same file: read the file before
   asking, and ask only about the findings still open.
5. When a fix round ends (executor, tester and the lenses again), mark each finding that was
   fixed: change its line from `- fix ...` to `- fixed ...` (key and text unchanged), one line
   per finding, nothing else rewritten. A finding the round did not fix keeps `- fix` (the
   dashboard shows it to the dev again), and the new lens findings go through this decision.

**Retrospective.** When every applicable lens has a verdict, none is `FAIL` and the findings
are decided:

1. `Agent(retrospective, "work dir .work/<ID>")` writes `05-retro.md`: what went wrong and the
   learnings, decisions and brain updates it proposes, tagged.
2. Show the dev the verdicts, the "Out of purpose" items, the rulings in `ledger.md`, and the
   proposals. Ask with `AskUserQuestion` `multiSelect` which to keep, then append the approved
   learnings to the learnings file, the approved decisions to the decisions file (`decisions` in
   `flow.json`; mark one it replaces `Superseded by: <slug>`), and apply the approved brain
   updates as `/brain add` would. Nothing the dev did not check is written.
3. `python3 .claude/kit/scripts/learnings.py --index <ID>` adds the task to the tasks file
   (purpose, criteria, PR), so a later task finds it after this one's work directory is deleted.

**Done.** Before opening the PR or MR, run the project's check (the build and test commands
`/flow-setup stack` recorded, the same the CI runs). If it fails, do not open it: show the
failure to the dev and let the dev decide; a failing check is never worked around to get the
PR out.

**Ship (optional).** Write the PR/MR body to `.work/<ID>/pr-body.md` (purpose, the ACs and how
each is proven, the rulings in `ledger.md`, merge order, what is left open), then run
`python3 .claude/kit/scripts/ship.py <ID>`. With `"ship": {"enabled": true}` in `flow.json` it
pushes the task's own branch (never with force, never a base branch) and opens the PR/MR with
the dev's tool (`gh`, `glab`, or a custom command), and keeps its URL for the dashboard. Off, it
prints the push and the command for the dev to run. A missing or logged-out tool is named with
what to run; never ask for a token.

The task is done when its PR or MR is open or merged (the dashboard finds it on GitHub or
GitLab and links it, and a merge git can see counts too), or when the dev runs
`bash .claude/kit/scripts/work.sh done [ID]` or clicks "Mark as done" on the dashboard (same
marker; the page warns about a FAIL or findings still open first). A task on a base branch or a
detached HEAD has no PR to find and closes only this way. Before that the dashboard says
`findings` or `ready-for-mr`. Once done, suggest `/clear` (or a new session) for the next task:
the finished task's context is noise for the next one.

**Merge order.** With more than one PR or MR open at the same time (parallel tasks in worktrees,
or one task split into several), run `python3 .claude/kit/scripts/merge-order.py` (no
arguments: the branches of the worktrees) and put its numbered list in a "Merge order" section
of each PR or MR description: a branch cut from another merges after it, and two branches that
change the same file merge in the order they started, the second rebased first. Run it again
when one of them merges.

## 8. Close and clean up

When the session starts with a line from the cleanup hook ("finished task(s) not cleaned up
yet"), or the dev says a PR or MR was merged, offer the cleanup. Learnings come first: a task
the plan marks "no retrospective yet" loses what it taught with its evidence, so offer the
retrospective (step 7) before anything is deleted.

Then run `bash .claude/kit/scripts/work.sh cleanup <ID>` (or `--all-done`): it prints the plan
and, without a terminal, deletes nothing. Ask with `AskUserQuestion`, `multiSelect`, which
items go: the task state, the worktree and its local branch (only when the plan does not
refuse it; say why when it does), and the review of Claude's auto memory about the task. The
dev confirms in the dashboard ("clean up" on the task, or "clean up all done") or by running
`! bash .claude/kit/scripts/work.sh cleanup <ID> --state --worktree --memory` and typing `yes`;
never delete the listed paths yourself. A worktree is never removed with `--force`; one that
is dirty or unpushed, has a live session, or holds a git-ignored secret (`.env`, keys) is
refused, and so is a squash-merged branch whose remote branch was deleted: show the commands to
remove it by hand.

A memory request reaches the next prompt or session in that worktree as context: list the
auto-memory entries about the task with `AskUserQuestion` `multiSelect` and delete only the
checked ones.

Without subagents (Cursor, Codex, Copilot, another client): run each stage in a **new
conversation** with the role file `.claude/agents/<role>.md` as the instruction and the work
directory path, and run `work.sh status` between stages. The same conversation that wrote the
code reviews it with the same blind spot.
