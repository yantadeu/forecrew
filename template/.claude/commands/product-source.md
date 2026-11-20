---
description: Register one or more new product sources (or sync the registered ones), interviewing the dev about each before recording it in .claude/product-sources.md
argument-hint: "<url|path|repo> [more...]  |  sync  |  list"
---

# Product sources

Input: `$ARGUMENTS`.

The registry `.claude/product-sources.md` (path in `.claude/flow.json`, `product_sources`) is
what the refiner and the product reviewer read to know where product truth lives, how to
read it fresh and which source wins a conflict. A source registered without the dev's
answers is a guess about authority, so this command always asks.

## `list`

Print the registry's table and stop.

## `sync`

For every registered source: run its "Sync" line, compare with its "Last read" version and
report, per source, changed or unchanged and, when changed, what changed in the areas it
decides. Then check the open work directories (`.work/*/01-contract.md`, "Sources read"):
name each one whose contract read an older version of a changed source. Update "Last read"
only for the sources actually reached. Do not change anything else.

## New sources

For each source in the arguments:

1. **Look before asking.** Identify the kind (git repo, local file, an issue tracker such as
   Jira, Linear, GitHub Issues or Azure Boards, a wiki or doc such as Confluence, Notion or
   Google Docs, a published API spec, a public URL) and try to read it with the tools you
   have. Summarize what it contains in three lines and suggest an answer for every question
   below from what you read. A question the source answers is not asked. If it cannot be
   read, say why and ask how the agents should reach it.
2. **Check overlap.** Compare with the sources already registered: what both decide, and
   where they disagree today, quoting both.
3. **Interview**, in one round with `AskUserQuestion` (at most 4 questions per call, a second
   call if needed), each with your recommendation first:
   - **Decides**: what this source is the truth for (scope and acceptance, business rules,
     external API contract, plan and dates, decisions, open questions, architecture, other).
   - **Authority**: when it disagrees with the sources it overlaps, which wins. Name them.
   - **Change rhythm**: how often it changes, and whether a change must stop work in progress
     or only be flagged in the review.
   - **Lenses**: who reads it (product, qa, security, contract).
   - **Reach**: how an agent syncs it (the command, tool or URL), and whether reading it needs
     a login the agents do not have.
   - **Owner**: the role that decides when it is wrong (a role, not a person's contact).
4. **Show the entry** you will write and wait for the dev's "ok". Then write it, update the
   table, and record "Last read" with the version you read (commit, page version or date).
5. If the new source changes the authority order of existing ones, show the reordered list
   and update it only with the dev's "ok".

## Entry format

```
## <short name>
- **Location**: <path, URL or repo>
- **Kind**: git repo | file | issue tracker | wiki/doc | API spec | URL | other
- **Decides**: ...
- **Authority**: wins over <x>; loses to <y> on <area>
- **Sync**: `<command>` or the tool and query an agent uses
- **Change rhythm**: ... ; on change: stop work | flag in review
- **Lenses**: product, qa, ...
- **Owner**: <role>
- **Last read**: <YYYY-MM-DD> @ <version>
```

Never copy a source's content into the registry: it holds where truth lives and how to read
it, not the truth itself, which would go stale the day the source changes. Never record a
credential or a token in it.
