"""Report-building pieces extracted from `generate_report.py` (§20.3 P3-2).

`generate_report.py` is the sole daily-report generator (CLAUDE.md §2) and was
1,640 module-level lines that **sent mail as a side effect of `import`**. That
is why `/api/state/report/send` has to shell out to a subprocess (§24.3) and why
the one output read every day had zero tests.

What moved here is only what is genuinely pure — chart rendering, the SQL reads,
and two number formatters. They take their inputs as arguments instead of
closing over module globals, so they can be called from a test without a
database, a snapshot, or an SMTP server.

What did **not** move: the HTML weave. ~700 lines of `X = build_x()` at module
level feeding one `replacements` dict, where each builder reads several of the
others' globals. Pulling that apart is a rewrite, not an extraction, and the
harm it causes is already fixed by `generate_report.main()` — importing the
module now does nothing.

`ponytail:` — the render layer stays in `generate_report.py`. Move it when a
second output format needs it (a Telegram digest, a web view of the same memo);
until then a rewrite buys structure nobody is asking for and risks the one
artefact Tom reads every morning.
"""
