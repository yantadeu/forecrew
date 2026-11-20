# Learnings

Only what was verified in a session, changes future behavior and cannot be derived from the
code or the git history. Agents load it by tag, never whole:
`python3 .claude/kit/scripts/learnings.py <tag>`; `--untagged` lists entries no lens will load.

```
## <short-slug>
- **Tags**: comma-separated, from: security, qa, product, integration, workflow, data, tooling, process.
- **What**: the fact, in one sentence.
- **How we knew**: the command, test or observation that proved it.
- **Apply**: what to do differently because of it.
```
