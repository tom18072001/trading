"""
Seed script: Fetch initial stock data for key symbols.

Usage:
    python scripts/seed_data.py                    # Fetch VN30 blue-chip stocks
    python scripts/seed_data.py VCB FPT HPG        # Fetch specific symbols
    python scripts/seed_data.py --sector "Ngân hàng"  # Fetch entire sector
"""

import argparse

from database.connection import init_db, get_session
from services.data_service import DataService
from config import SECTOR_MAP, VN30_SYMBOLS, START_DATE, END_DATE


def seed_symbols(symbols: list[str], start_date: str = START_DATE, end_date: str = END_DATE):
    """Fetch and store data for a list of symbols."""
    # Build reverse lookup
    sym_to_sector = {}
    for sector_name, syms in SECTOR_MAP.items():
        for s in syms:
            sym_to_sector[s] = sector_name

    init_db()
    with get_session() as session:
        svc = DataService(session)
        svc.register_all_sectors()

        total = 0
        for i, sym in enumerate(symbols, 1):
            sym = sym.upper()
            sector = sym_to_sector.get(sym, "Other")
            print(f"\n[{i}/{len(symbols)}] Fetching {sym} ({sector})...")
            try:
                count = svc.fetch_and_store_stock(sym, start_date, end_date, sector=sector)
                total += count
                print(f"  -> {count} rows stored")
            except Exception as e:
                print(f"  -> ERROR: {e}")

        print(f"\n{'='*50}")
        print(f"DONE: {total} total rows for {len(symbols)} symbols")
        print(f"{'='*50}")

        # Show summary
        summary = svc.get_data_summary()
        if summary:
            print(f"\nStored data summary:")
            for item in summary:
                print(f"  {item['symbol']:6s} | {item['sector']:20s} | {item['num_rows']:5d} rows | {item['first_date']} -> {item['last_date']}")


def seed_sector(sector_name: str, start_date: str = START_DATE, end_date: str = END_DATE):
    """Fetch and store data for an entire sector."""
    symbols = SECTOR_MAP.get(sector_name)
    if not symbols:
        print(f"Unknown sector: {sector_name}")
        print(f"Available sectors: {', '.join(SECTOR_MAP.keys())}")
        return
    print(f"Fetching sector '{sector_name}' ({len(symbols)} symbols)...")
    seed_symbols(symbols, start_date, end_date)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed stock market data")
    parser.add_argument("symbols", nargs="*", help="Stock symbols to fetch (e.g. VCB FPT HPG)")
    parser.add_argument("--sector", type=str, help="Fetch entire sector by name")
    parser.add_argument("--vn30", action="store_true", help="Fetch all VN30 blue-chip stocks")
    parser.add_argument("--start", type=str, default=START_DATE, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=END_DATE, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.sector:
        seed_sector(args.sector, args.start, args.end)
    elif args.vn30:
        print("Fetching VN30 blue-chip stocks...")
        seed_symbols(VN30_SYMBOLS, args.start, args.end)
    elif args.symbols:
        seed_symbols(args.symbols, args.start, args.end)
    else:
        # Default: fetch top 5 blue-chips as demo
        demo_symbols = ["VCB", "FPT", "HPG", "VNM", "MWG"]
        print("No symbols specified. Fetching top 5 blue-chips as demo...")
        seed_symbols(demo_symbols, args.start, args.end)
