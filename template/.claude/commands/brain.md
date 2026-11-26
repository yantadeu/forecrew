---
description: The project's second brain - capture a source or a note into linked markdown pages, ask it with citations, and lint it. Optional; on once the brain folder exists.
argument-hint: on | add <url|path|note> | ask <question> | lint
---

# Brain

A second brain in the sense of Tiago Forte's CODE (capture, organize, distill, express) kept the
way of an LLM wiki: the dev curates sources and asks questions, the agent writes and maintains
the pages. The pages are plain markdown with `[[wikilinks]]`, so the folder opens as an Obsidian
vault. Raw sources are never copied in: a page cites them (a URL, a path, a ticket) and holds
only what was distilled from them.

The folder is `brain` in `.claude/flow.json` (default `docs/brain`, outside `.claude/`, whose
files Claude Code asks before every edit). Inside the repository it
is the team's, committed and reviewed. An absolute path (`~/notes/work`) makes it the dev's
personal vault: the same commands, nothing committed. Either way the brain is on when the folder
exists.

What it holds, and what it does not:

| It holds | It does not hold (already kept elsewhere) |
| --- | --- |
| concepts of the domain, a glossary, how the modules fit, who owns which system, external systems and their quirks, open questions | learnings (`LEARNINGS.md`), decisions (`DECISIONS.md`), finished tasks (`TASKS.md`), product truth (`product-sources.md` points to it), anything the code or git history answers |

Page format, one concept per page, file name in kebab case:

```
# <Concept>
Tags: <from the learnings tags, plus any the brain needs>
Sources: <url, path or task ID, with the date read>
Updated: <YYYY-MM-DD>

<what it is, in a few lines> ... [[other-page]] where another concept is meant.

## Open questions
- <what nobody has confirmed yet>
```

`index.md` lists every page with one line each. `log.md` is append-only: one line per change,
`YYYY-MM-DD <add|update|lint> <page>: <what>`.

## `/brain on`

Create the folder (from `brain` in `flow.json`; ask the dev whether it is the team's, in the
repository, or a personal path, and write the answer to `flow.json`), with `index.md` and
`log.md`. Nothing else.

## `/brain add <url|path|note>`

Capture. Read the source (a URL with WebFetch, a path, a ticket through its MCP, or the note the
dev typed). Search first, `python3 .claude/kit/scripts/learnings.py --search <key words>`, so you
update a page instead of writing a second one about the same thing. Then show the dev, in one
message, the pages you would create or change and the lines of each; write only after the dev
confirms. Update `index.md` and `log.md`. A fact that belongs in learnings, decisions or product
sources goes there instead: say which and stop.

Never write a secret, a credential, personal data of a customer or a person's private details
into a page, even when the source has them.

## `/brain ask <question>`

Express. `learnings.py --search <the question>` (ranked; by meaning when `embeddings` is set), read the pages it returns and
the ones they link, and answer citing each page (`[[page]]`) and, under it, its sources. What the
brain does not answer, say so; offer `/brain add` for the source that would. Write nothing.

## `/brain lint`

Distill. Read every page and report, without changing anything:

- a page whose claim the code now contradicts (read the code it names), with the line;
- two pages that say different things about the same concept;
- a `[[link]]` to a page that does not exist, and a page nothing links to and `index.md` omits;
- a page not updated in 180 days whose sources changed since;
- open questions a later page or task answered.

Then ask, with `AskUserQuestion` `multiSelect`, which fixes to apply, apply only those, and
append them to `log.md`.

## After a task

When the folder exists, the retrospective also proposes brain updates (`## Proposed brain
updates` in `05-retro.md`): a concept the task had to learn the hard way. The task skill applies
the ones the dev approves, as `/brain add` would.
