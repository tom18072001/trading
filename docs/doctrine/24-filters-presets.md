# §24 — Filter, preset stealth và giá của tranh cãi P1-1

> Tách khỏi `CLAUDE.md` ngày 2026-09-16 để doctrine trở lại ngân sách context
> (135.718 B nạp lại **mỗi lượt**; ngân sách của `claude/CLAUDE.md` mẹ là 10 KB).
> **Nội dung dưới đây nguyên văn** — không tóm tắt, không sửa số, không sửa ngày.
> `CLAUDE.md` giữ lại: kết luận: một bộ từ vựng filter, preset mở ở Vừa, và §24.5 còn mở, và trỏ về file này.

## 24. Filters, presets and the P1-1 price tag — 2026-08-23

### 24.1 One filter vocabulary
Every sector table drew all 15 rows in one fixed order. `lib/filters.tsx` is
now the single source for search, action filter, "chỉ ngành tôi đang nắm",
column sorting and CSV, used by Ranking and Money Flow Monitor.

State lives in the **URL**, not in component state (`?rk_act=BUY&rk_sort=score`,
`replace: true`, one prefix per table). A tuned view is a thing you send to
someone, and F5 must not clear it — the same reasoning as §22.9's tabs.

Two details that are load-bearing rather than incidental:
- **Filter, then sort.** The other order sorts rows you are about to discard.
- **CSV carries a UTF-8 BOM.** Without it Excel on a Vietnamese locale opens
  "Ngân hàng" as mojibake, which makes the export useless to its only user.

"Chỉ ngành tôi đang nắm" is answered entirely from the §22.10 store — the app
already knew the book, no page had ever asked it a question.

### 24.2 The stealth presets are an argument, not a convenience
**Chặt / Vừa / Rộng**, not tight/loose. The presets were shipped to price the
§20.3 P1-1 doctrine-vs-code disagreement **in sectors** — the only unit in which
anyone would care enough to close it.

**They did their job on the day they shipped, and the answer killed the
question.** Running all three returned `active: []` at *every* setting,
including maximally-wide. Both sides of P1-1 were worth zero sectors, because
the AND gate underneath them was unreachable (§16.1). The conflict was
three-way, not two — `api/routers/stealth.py` had its own third set of defaults
— so the page could show a sector the scanner would never record.

Rewritten 2026-08-23 around the knob that now matters, `min_conditions`:

| preset | numbers | what it is |
|---|---|---|
| Chặt | 5/5, N=5 | the original doctrine, **kept so you can watch it return 0** |
| Vừa | ≥4/5, N=3 | what runs now — 23 events / 11 sectors in 3.5 years |
| Rộng | ≥3/5, N=1, mọi ngưỡng hạ | a probe — "ngành nào gần đạt", not a buy list |

The page **opens on Vừa**, not Chặt: a default that shows a gate nobody is
running is a default that misleads. Selecting Chặt raises the warning now,
naming the 2-session measurement that retired it.

Two other things this pass reconciled:
- `api/routers/stealth.py` classified `active` only at `passes == 5`. Both
  knobs are now imported from `analysis/stealth.py`, so the page and the
  scanner cannot drift apart again without a test failing.
- The endpoint's cond4 compared a **raw** `atr_pct` (~0.006) against a
  threshold literally named `atr_rank_max` (0.5) — it passed for free on all 15
  sectors, so the endpoint's "five-condition" gate was really four. It takes a
  0..1 percentile within the sector's own window now, which is what §16.1
  condition 4 means.

### 24.3 Send the report without a terminal
`POST /api/state/report/send` runs `generate_report.py` as a **subprocess**.
Importing it would send mail as a side effect of the `import` statement, once
per process and never again, because it is 1,629 module-level lines driven by
`sys.argv` with no `main()` (§20.3 P3-2). A subprocess is the honest way to
call a script that is a script.

It sits under `/api/state/*` rather than a new router because it is an operator
action — the same category as the kill-switch and the position book.

The double-click guard is on the **backend** (`already_running`), not on the
disabled button. A disabled button is a hint; two emails is a fact.

### 24.4 Words on the screen
`lib/glossary.tsx` defines 13 column names behind a native `title`. The
definitions existed only in `CLAUDE.md` §16.2 and `docs/reference/GLOSSARY_VI.md`
— neither of which is open while you are reading the table.

`foreign_hit_20d`'s entry said out loud that `foreign_net` was zero across the
whole history (§20.3 P0-5) — a tooltip that explains a column doing nothing,
without saying so, is worse than no tooltip. **That warning was already false
when it shipped**: the backfill had landed the same morning. Corrected the same
day, along with a new `conditions_met` entry for the §16.1 score.

### 24.5 Not done
- `Th` / `FilterBar` are on two tables. Risk, Stealth and Regime still have
  their own headers.
- Native `title`: no touch support, ~1s delay. Fine for a definition, not for
  a formula or a link.
- Report run history is in memory only. It survives no restart; the log file on
  disk is the durable record.

