"""_audit/probe_vnapi.py -- what does the non-deprecated vnstock.api look like?

The deprecation banner in every job log says the Vnstock() class and
stock/fx/crypto/... accessors were retired on 2025-08-31 in favour of
`vnstock.api`. This dumps the actual surface so the migration is written
against what is installed, not against a blog post.
"""
from __future__ import annotations

import inspect
import pkgutil
import traceback
import warnings

warnings.filterwarnings("ignore")

import vnstock  # noqa: E402

print("vnstock version:", getattr(vnstock, "__version__", "?"))

try:
    import vnstock.api as api
    mods = sorted(m.name for m in pkgutil.iter_modules(api.__path__))
    print("vnstock.api submodules:", ", ".join(mods))
except Exception:
    print("vnstock.api NOT importable:")
    traceback.print_exc()
    raise SystemExit(1)


def show(label, cls, methods):
    print(f"\n--- {label} ---")
    try:
        print(f"  __init__{inspect.signature(cls.__init__)}")
    except Exception as e:
        print(f"  __init__ signature unavailable: {e}")
    for m in methods:
        fn = getattr(cls, m, None)
        if fn is None:
            print(f"  .{m}  -- NOT PRESENT")
            continue
        try:
            print(f"  .{m}{inspect.signature(fn)}")
        except Exception as e:
            print(f"  .{m}  signature unavailable: {e}")


try:
    from vnstock.api.quote import Quote
    show("Quote", Quote, ["history", "intraday"])
except Exception:
    traceback.print_exc()

try:
    from vnstock.api.trading import Trading
    show("Trading", Trading, ["price_board"])
except Exception:
    traceback.print_exc()

try:
    from vnstock.api.listing import Listing
    show("Listing", Listing, ["symbols_by_industries", "all_symbols",
                              "symbols_by_exchange"])
except Exception:
    traceback.print_exc()

print("\n" + "=" * 70)
print("  Live smoke test against the new API")
print("=" * 70)
try:
    from vnstock.api.quote import Quote
    q = Quote(symbol="VCB", source="KBS")
    df = q.history(start="2026-08-01", end="2026-08-22", interval="1D")
    print(f"  Quote.history -> {df.shape}, columns={list(df.columns)}")
    print(df.tail(3).to_string(index=False))
except Exception:
    print("  Quote.history FAILED:")
    traceback.print_exc()

try:
    from vnstock.api.trading import Trading
    t = Trading(symbol="VCB", source="KBS")
    b = t.price_board(["VCB"])
    print(f"\n  Trading.price_board -> {b.shape}")
except Exception:
    print("\n  Trading.price_board FAILED:")
    traceback.print_exc()

print("\ndone.")
