---
description: Set up or change Forecrew for this repository by interviewing the dev - task tracker, product documentation, what each reviewer reads, how the stack builds and tests, and which optional plugins and MCP servers to add
argument-hint: "[existing|tracker|docs|lenses|stack|extensions]  (no argument: all, in order)"
---

# Agent flow setup

Input: `$ARGUMENTS`. With no argument, run every part in order (part 0 only when there is
something to handle); with one, run only it.

Run it after installing the kit, and again **whenever anything changes**: the team moves to
another tracker, documentation moves, a reviewer must read a new policy, a plugin is added or
dropped. On a rerun, read the current configuration first and offer each current value as the
default answer. Write only what the dev changed, and ask explicitly before removing anything.

Rules for the whole interview:

- **Look before asking.** Read the repository first (README, CI config, package manifests,
  existing docs, `.claude/`, `AGENTS.md`, `.cursor/`) and the connectors and CLIs you can
  reach. Every question carries your recommendation, taken from what you found. A question the
  repository answers is not asked.
- Ask with `AskUserQuestion` when available (at most 4 questions per call), otherwise as a
  numbered list in one message. One round per part.
- Show what you will write and wait for the dev's "ok" before writing it.
- Never record a credential, a token or a personal contact. Record roles, not people.

## Part 0: existing

The AI configuration the repository already had: instructions for other tools, its own agents
and commands, another workflow framework, a memory folder. List it with
`python3 .claude/kit/scripts/detect.py`; items marked `kit` are the kit's own and are skipped.
Nothing found: say so and go to part 1.

For each item, read it, then propose **one** action with the reason, using the table below.
Group similar items in one question (for example all `.cursor/rules` files) when the same
action fits them all.

| Found | Recommended action |
| --- | --- |
| `conflict`: your file at a kit path (an agent or command with the same name) | **Merge.** Start from the kit's version in `.claude/kit/originals/<path>` and carry over what is specific to this project from yours: stack, commands, conventions, traps already paid for. Keep the kit's stage file and required `##` sections, or the gate fails. If yours is a different role that happens to share the name, **rename** yours instead. |
| Project instructions (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.github/copilot-instructions.md`, `.windsurfrules`, `.clinerules`) | **Keep** the facts about the project. **Edit out** workflow instructions that contradict the flow ("review your own code", "commit straight to main", "skip tests for small changes"). When several files repeat the same content for different tools, propose one source and pointers to it (for example `AGENTS.md` as the source and `@AGENTS.md` in `CLAUDE.md`). |
| `.cursorrules` | **Migrate** its content to `.cursor/rules/*.mdc` (Cursor's current format), then remove it. |
| Other agents, skills or commands (`overlap`) | **Keep** what the flow does not do. One that repeats a stage (another code reviewer, another test writer): **merge** its useful checks into the matching kit agent, or **remove** it. Two agents doing one job split the findings. |
| A workflow framework (Spec Kit `.specify/`, BMAD `.bmad-core/`, Task Master `.taskmaster/`, or a plugin with its own flow) | Two orchestrators compete for the same task. Offer: **feed** it (its spec or task output becomes the input of `/task`, and its folder is registered as a product source), **replace** it with the flow, or **scope** both (which kind of work goes to which). |
| A memory folder (`memory-bank/`, notes from another tool) | **Migrate** the verified, still-true facts into `LEARNINGS.md`, each with tags, then keep or remove the folder. |
| Conventions or policies (`CONVENTIONS.md`, rule files) | **Keep**, and add them to the `read` list of the lens they serve in part 3. |
| MCP servers and settings | **Keep.** Note the servers that help a stage for part 5. |

Rules for every action:

- Show the exact result before writing: the merged file, or the diff of the edit.
- **Replace and remove always back up first**, to `.agent-flow-backup/<YYYYMMDD-HHMMSS>/<same path>`
  (git-ignored). Tell the dev where the backup is.
- Nothing is changed without the dev's "ok", item by item or group by group.
- When nothing fits the table, ask: keep, merge, replace or remove, with your recommendation.

## Language

Ask once, with the current value as the default: which language does the dev read (`en`,
`pt-BR`, `es`, ...)? Write it to `language` in `.claude/flow.json`. From the next session on,
every agent writes its messages, questions and work files in it (PROTOCOL.md, rule 12); the
dashboard has its own PT/EN switch.

## Part 1: tracker

Where tasks and their acceptance criteria live.

Ask:
1. **Which tool**: Jira, Linear, GitHub Issues, GitLab Issues, Azure Boards, Trello, Notion,
   a file in the repository, none (requests come in chat).

   **None** is a full answer, not a gap: skip questions 2 to 4, write no tracker entry, and
   tell the dev how they will start work: `/task <what you want done>` in plain words; the
   agent proposes the acceptance criteria and a short ID (`csv-export`) for them to confirm.
2. **How an agent reaches it**: an MCP connector (check which ones are connected), a CLI
   (`gh`, `glab`, `jira`, `az`), a URL, or "the dev pastes the task".
3. **Task id format**, so `/task PROJ-123` can be recognized (for example `[A-Z]+-\d+`,
   `#\d+`), and where the acceptance criteria sit in a task (description, a field, a checklist).
4. **Write-back**: may the agents comment on or move a task, or is the tracker read-only for them.
   Recommend read-only.

Write it as the first entry of `.claude/product-sources.md`, in the entry format of
`.claude/commands/product-source.md`, with **Decides**: "tasks and acceptance criteria" and the
answers above in **Sync** (the exact tool or command and query) and **Location**. Put it at
the top of the authority order for acceptance criteria.

## Part 2: product documentation

Where the product is described: specs, plans, decisions, open questions, API contracts. It can
be a repository, Confluence, Notion, Google Docs, a published API spec, a wiki, a folder here.

Ask for the list of sources, then for each one follow `.claude/commands/product-source.md`
(read it, check overlap, interview, show, write). Finish by showing the authority order of all
sources together and asking the dev to confirm it.

## Part 3: review lenses

What each review lens must read, beyond the code. Propose files you found and ask about the
rest:

- **security**: security policy, data classification, rules for secrets and sensitive data,
  compliance requirements (for example PCI, LGPD, GDPR, HIPAA), threat model.
- **qa**: testing guidelines, test layers and how CI runs them, definition of done.
- **product**: product principles; the product sources registry is always included.
- **contract**: architecture decisions, coding conventions, the project's constitution if any.

Write the paths into `lenses.<lens>.read` of `.claude/flow.json`. A document that lives outside
the repository goes into `product-sources.md` instead, with the lens in **Lenses**.

## Part 4: stack

How this repository builds and tests, so the executor and the tester stop guessing. Detect,
then confirm:

1. Build and lint commands.
2. Test commands per layer (unit, integration, end to end), what infrastructure each needs,
   and which CI job runs which layer.
3. Conventions a reviewer would reject (language of identifiers and comments, file layout,
   migration rules, commit message format).
4. Irreversible or dangerous operations in this project (deploys, data migrations, anything
   that cannot be undone), which the agents must never run without the dev.
5. Model per stage (the `model:` line of each agent): recommend the most capable model for the
   refiner and the four reviewers, where a miss is expensive, and offer a cheaper one for the
   tester or the executor on mechanical work. Keep what the dev already chose.
6. The checks the machine runs before any reviewer (`checks` in `flow.json`): the lint, build
   and fast test commands from 1 and 2, each `{"name": "lint", "run": "<command>"}` with an
   optional `"timeout"` in seconds (default 900). Only what runs here without infrastructure the
   agent cannot start; a slow layer stays with the tester. Run each once to confirm it passes
   on the base branch. A tool that is not installed fails its check, it is never skipped.
7. How many fix rounds before the dev decides (`max_fix_rounds` in `flow.json`, default 3).
8. Where pull or merge requests are opened, which is what marks a task done on the dashboard.
   Detect it from the `origin` remote: github.com is GitHub and any other host is taken as a
   GitLab, so ask only when that guess is wrong (GitHub Enterprise: `"forge": "github"`; no
   forge, or one with neither API: `"forge": "none"`, tasks then close on a merge git can see or
   with `work.sh done`). Say which token the dashboard reads (`GITHUB_TOKEN`/`GH_TOKEN`,
   optional for a public repository, or `GITLAB_TOKEN`), set in the shell that starts it, never
   in a file. A host other than github.com goes into `forge_hosts`, or the token is never sent
   there. Ask for `base_branches` only when the base is not `main`, `master` or `develop`.
9. Whether the agent may ship a finished task: push its branch and open the PR/MR itself
   (`"ship": {"enabled": true, "tool": "auto", "push": true, "draft": true}` in `flow.json`; off by
   default). `auto` picks `gh` for github.com and `glab` for a GitLab; for another forge or a
   company script, `"tool": "custom"` with `"command"`, a template using `{base}`, `{branch}`,
   `{title}`, `{body_file}` and `{draft}`. Check the tool is installed and logged in (`gh auth
   status`, `glab auth status`) and say what to run if not.

Edit only the sections of `.claude/agents/executor.md`, `tester.md` and `reviewer.md` (and the
`model:` lines, and `checks`, `forge`, `forge_hosts`, `base_branches` or `ship` in `flow.json`) that these answers change, show the diff, and wait for the "ok". Then offer to
run the evals on the adapted agents: `python3 .claude/kit/evals/run.py --runs 3` (it calls the
model and costs tokens).

## Part 5: extensions

Optional plugins and MCP servers that help specific stages. The catalog, with what each one is
for, which stage it helps, its install commands and its overlaps, is
`.claude/kit/extensions.json`.

1. **See what is already there**: `claude plugin list`, `.mcp.json`, `.claude/settings.json`,
   `.cursor/mcp.json`, `~/.codex/config.toml`. Already installed is not offered again.
2. **Match the repository**: offer only the entries whose `signal` fits what you found (a web
   frontend suggests playwright; tasks in Jira suggest atlassian; the tracker chosen in part 1
   suggests its connector). Include the ones the dev names, even if they are not in the catalog.
3. **Ask** with a multi-select question: one line each with what it does in this flow, the
   stage it helps, its author and trust level, and its `overlaps` warning when it has one.
4. **For each one chosen**, before installing:
   - check it still exists and read what it adds (`claude plugin details <name>`, or its
     repository). A name not in the catalog gets the same check, and the dev sees its source;
   - for Claude Code, show the `claude` commands from the catalog. `--scope project` writes it to
     `.claude/settings.json`, so the whole team gets it; `--scope user` keeps it personal;
   - for Cursor and Codex, show the MCP entry you will add to `.cursor/mcp.json` or
     `~/.codex/config.toml`. A Claude plugin with no `mcp` entry has no equivalent there: say so;
   - run the commands only after the dev's "ok". Installing runs third-party code.
5. **Tell the agents**: record each installed extension in `extensions` of `.claude/flow.json`
   as `"<id>": {"stages": [...], "use_for": "<one sentence>"}`. Agents read it through the
   protocol and use an extension only for what is recorded there.

Removing one: uninstall with the dev's "ok" (`claude plugin uninstall`, or delete the MCP entry)
and remove it from `extensions`.

**Telegram (built in, per dev).** Offer it when the dev wants what waits on them on their phone,
answered from there. It needs nothing installed and nothing in the repository: the dev creates a
bot with @BotFather, exports `FORECREW_TELEGRAM_TOKEN` in their shell profile, sends the bot any
message, runs `bash .claude/kit/scripts/work.sh telegram chat-id` and exports
`FORECREW_TELEGRAM_CHAT` with the id it prints; then `work.sh telegram start`. Say what it
does before they turn it on: while it runs, a permission dialog waits for an answer from
Telegram (or "Answer in the terminal"), the command shown there is masked, and
`"telegram": {"details": false}` in `flow.json` sends only the kind of each alert. Never write
the token or the chat id to a file.

## Close

Run `python3 .claude/kit/scripts/export.py` so Cursor and Codex see the changes, then
`python3 .claude/kit/test_kit.py`. Print what was configured and what was left empty, and
suggest the first task: `/task <ticket or request>`.
