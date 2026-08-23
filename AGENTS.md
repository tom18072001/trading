# AGENTS.md

**This file is not the plan. [`CLAUDE.md`](./CLAUDE.md) is.**

Until 2026-08-22 this was a full 26 KB copy of `CLAUDE.md`, and the two had
already drifted apart in five passages — the agent-provider paragraph and four
test descriptions disagreed about which LLM the system uses. Both files opened
with "every future modification MUST append an entry to `MODIFICATION_LOG.md`",
a discipline that cannot hold with two competing sources of truth
(docs/reviews/CODE_REVIEW_2026-08-22.md, finding P3-1).

Any agent working in this repository should read, in order:

1. `CLAUDE.md` — the approved plan, doctrine and defaults.
2. `docs/reviews/CODE_REVIEW_2026-08-22.md` — known defects and their status.
3. `ARCHITECTURE.md` — layers, contracts, schema.
4. `MODIFICATION_LOG.md` — what changed, when and why.

Do not restore a second copy of the plan here. Edit `CLAUDE.md` instead.
