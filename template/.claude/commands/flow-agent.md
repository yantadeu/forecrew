---
description: Create, move or remove a specialized agent of Forecrew, its room on the site, and its place in the flow - by interviewing the dev
argument-hint: "[catalog | add <name> | new | move <name> | remove <name> | list]"
---

# Specialized agents

Input: `$ARGUMENTS`. Without one, ask with `AskUserQuestion`: hire one from the catalog, create a
new agent, move one, remove one, or list them.

Write every question to the dev in the `language` of `.claude/flow.json`. Show each file you
will write or change, as a diff, and wait for the dev's "ok" before writing it.

## list

Print the agents of `.claude/agents/`, and for each one: its place in the flow (a stage of
`stages` in `.claude/flow.json`, with what it requires; a review lens; or outside the flow), its
room (`rooms`) and its label.

## catalog

Read `.claude/kit/specialists/catalog.json` and list each specialist: its label in the dev's
language, its pitch, and whether the project already has it (an `agents/<name>.md` or a `stages`
entry). The dashboard shows the same list under "Hire a specialist" in the Crew panel. Then ask
with `AskUserQuestion`, `multiSelect`, which to add, and run **add** for each.

## add <name>

A ready specialist from the catalog: no interview for what the catalog already decides.

1. Read its entry in `.claude/kit/specialists/catalog.json` and its file
   `.claude/kit/specialists/<name>.md`. A name not in the catalog: say so and offer **new**.
2. Ask only what depends on the project, one round each, with your recommendation first:
   - **What it reads** (`lenses.<lens>.read`): files of this repository that matter to its
     specialty (a schema, a design system, an API contract). Look for them first and propose them.
   - **Room**: the catalog's room, or another of `rooms`.
3. Show the diff and write, after the dev's ok, exactly what **new** writes for a review lens:
   the agent file (copied from the catalog, adapted only where the project needs it), the
   `stages` entry `{"file": "04-review-<lens>.md", "verdict": true, "requires": ["refiner",
   "executor", "tester"], "sections": ["Findings"]}`, the `lenses` entry with the catalog's
   `tags`, the room, and `agents.<name>` with the catalog's `label`, `color` and `emblem`.
4. Run `python3 .claude/kit/scripts/export.py` and `bash .claude/kit/scripts/work.sh status`.

## new

Before the interview, read the catalog: when the specialty the dev names is one of its entries,
offer **add** of that entry first.

Interview, one round per question, with your recommendation first:

1. **Specialty.** What does it know that the other agents do not (performance, accessibility,
   data migrations, a framework, a domain such as payments)? What defect does it exist to
   prevent? Read the code and the learnings first, so the question carries a concrete example.
2. **Name.** A short kebab-case name (`perf-reviewer`, `a11y-reviewer`, `migration-planner`), and
   its label in English and in the dev's language, for the dashboard.
3. **Place in the flow**, with `AskUserQuestion`:
   - **Review lens (Recommended for a reviewer)**: runs in parallel with the other reviewers on
     the same `review.diff`, writes `04-review-<lens>.md` starting with a `Verdict:` line, and
     its findings use the protocol's format, so the dashboard lists them for the dev to decide.
   - **Stage in the sequence**: runs before or after an existing stage (ask which), writes its
     own file starting with a `Status:` line, and the stages after it require it.
   - **Outside the flow**: an agent the dev or the orchestrator calls by name when needed; no
     stage file and no gate.
4. **What it reads** (files and product sources) and **its learning tags** (a lens's `tags`).
5. **Tools and model.** Read-only (`Read, Grep, Glob, Bash`) for a reviewer; writing tools only
   for a stage that changes code. Recommend the most capable model for a reviewer.
6. **Room**, with `AskUserQuestion`: one of the rooms of `rooms`, or a new room (an id, its name
   in English and in the dev's language). Offer the room the place suggests: the review hall for a
   lens, the room of the neighbor stage for a stage.
7. **Look on the dashboard**: a color (`#rrggbb`) and an emblem among `doc`, `wrench`, `check`,
   `eye`, `shield`, `bug`, `star`, `loop`, `gear`, `gauge`, `lock`, `db`, `globe`, `chart`. Suggest
   one that fits the specialty.

Then write, after the dev's ok:

- `.claude/agents/<name>.md`, in the shape of the agents already there: frontmatter with `name`,
  `description` (what it does and when to use it, so it is picked correctly), `tools` and
  `model`; then its role, what it reads first (`00-purpose.md`, the stage files before it, its
  reading list, `learnings.py --lens <lens>` for a lens), what it writes, the protocol's rules it
  follows (`.claude/kit/PROTOCOL.md`), and its red flags: the shortcuts it must refuse.
- `.claude/flow.json`:
  - a lens: a `stages` entry `{"file": "04-review-<lens>.md", "verdict": true, "requires":
    ["refiner", "executor", "tester"], "sections": ["Findings"]}` and a `lenses` entry
    `{"tags": [...], "read": [...]}`;
  - a stage: a `stages` entry `{"file": "0N-<name>.md", "status": true, "requires": [...],
    "sections": [...]}` at its place in the order, and the stages after it list it in `requires`;
  - the room: the agent added to the room's `agents` (or a new `rooms` entry
    `{"id": ..., "name": {"en": ..., "<lang>": ...}, "agents": ["<name>"]}`);
  - `agents`: `"<name>": {"label": {"en": ..., "<lang>": ...}, "color": ..., "emblem": ...}`.
- Then run `python3 .claude/kit/scripts/export.py` (Cursor, Codex and Copilot see the new agent)
  and `bash .claude/kit/scripts/work.sh status` (the gate reads the new stage).

The task skill runs every stage of `stages` in order and every stage with `"verdict": true` in
parallel as a review lens, so a new agent takes part in the next task without any other change.
Say so, and say where it will show up on the dashboard (its room, its node in the steps).

## move

Ask where to (another room, another place in the flow), show the diff of `.claude/flow.json`,
and write it after the ok. Moving a lens out of the flow removes its `stages` and `lenses` entries
but keeps the agent file.

## remove

Show what goes (the agent file, its `stages`, `lenses`, `rooms` and `agents` entries, and the
`requires` that name it) and remove it after the ok. Never remove the default agents
(refiner, executor, tester, reviewer, security-reviewer, qa-reviewer, product-reviewer,
retrospective) without asking twice: the flow and its gates rely on them. A room left empty is
removed too.
