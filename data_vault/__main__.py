"""Interactive CLI for DataVault — fetch OHLCV data by exchange and sector.

Usage::

    python -m data_vault
"""

import json
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from .logging_config import setup_logging
setup_logging()

logger = logging.getLogger("data_vault")

# ── constants ─────────────────────────────────────────────────────────────────

_MARKETS_FILE = os.path.join(os.path.dirname(__file__), "markets.json")
_YF_SCREENER_PAGE_SIZE = 250


# ── helpers ───────────────────────────────────────────────────────────────────


def _load_markets() -> dict:
    """Load exchange and sector definitions from markets.json."""
    with open(_MARKETS_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _prompt_selection(label: str, options: list[str]) -> list[str]:
    """Present a numbered list, accept comma/space-separated selection.

    Returns the selected option strings. Exits on invalid input.
    """
    print(f"\n{'=' * 50}")
    print(f"  Select {label}")
    print(f"{'=' * 50}")
    for i, option in enumerate(options, 1):
        print(f"  {i:>3}. {option}")
    print()

    raw = input(f"Enter {label.lower()} numbers (comma or space separated): ").strip()
    if not raw:
        print(f"ERROR: No {label.lower()} selected.")
        sys.exit(1)

    # Parse comma or space separated numbers.
    tokens = raw.replace(",", " ").split()
    selected = []
    for token in tokens:
        try:
            idx = int(token)
        except ValueError:
            print(f"ERROR: '{token}' is not a valid number.")
            sys.exit(1)
        if idx < 1 or idx > len(options):
            print(f"ERROR: {idx} is out of range (1-{len(options)}).")
            sys.exit(1)
        selected.append(options[idx - 1])

    return selected


def _fetch_tickers(exchanges: list[dict], sectors: list[str]) -> list[str]:
    """Use yfinance screener to find tickers for given exchanges and sectors.

    Paginates through results (max 250 per call).
    """
    from yfinance.screener import EquityQuery, screen

    all_tickers: set[str] = set()

    for exchange in exchanges:
        yf_code = exchange["yf_code"]
        display_name = exchange["display_name"]

        for sector in sectors:
            logger.info("Screening %s / %s ...", display_name, sector)

            query = EquityQuery("and", [
                EquityQuery("eq", ["exchange", yf_code]),
                EquityQuery("eq", ["sector", sector]),
            ])

            offset = 0
            while True:
                try:
                    result = screen(query, size=_YF_SCREENER_PAGE_SIZE, offset=offset)
                except Exception as exc:
                    logger.warning(
                        "Screener error for %s/%s: %s — skipping", display_name, sector, exc,
                    )
                    break

                quotes = result.get("quotes", [])
                if not quotes:
                    if offset == 0:
                        logger.warning(
                            "No tickers found for %s / %s", display_name, sector,
                        )
                    break

                for quote in quotes:
                    symbol = quote.get("symbol")
                    if symbol:
                        all_tickers.add(symbol)

                total = result.get("total", 0)
                offset += len(quotes)
                if offset >= total:
                    break

            count_for_combo = len([
                q for q in result.get("quotes", []) if q.get("symbol")
            ]) if offset > 0 else 0
            logger.info(
                "Found %d tickers for %s / %s",
                min(offset, result.get("total", 0)) if offset > 0 else 0,
                display_name, sector,
            )

    from .data_vault import is_preferred_share
    preferred = {t for t in all_tickers if is_preferred_share(t)}
    filtered = all_tickers - preferred
    if preferred:
        logger.info(
            "Filtered %d preferred share tickers (e.g. %s)",
            len(preferred), ", ".join(sorted(preferred)[:5]),
        )

    tickers = sorted(filtered)
    logger.info("Total unique tickers discovered: %d", len(tickers))
    return tickers


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Run the interactive DataVault CLI."""
    markets = _load_markets()

    # Select exchanges.
    exchange_names = sorted(markets["exchanges"].keys())
    selected_exchange_names = _prompt_selection("Exchanges", exchange_names)
    selected_exchanges = [
        markets["exchanges"][name] for name in selected_exchange_names
    ]

    # Select sectors.
    sectors = sorted(markets["sectors"])
    selected_sectors = _prompt_selection("Sectors", sectors)

    logger.info(
        "Configuration: exchanges=%s, sectors=%s",
        [e["display_name"] for e in selected_exchanges],
        selected_sectors,
    )

    # Discover tickers via yfinance screener.
    tickers = _fetch_tickers(selected_exchanges, selected_sectors)

    if not tickers:
        logger.warning("No tickers found for selected criteria. Exiting.")
        return

    # Fetch OHLCV data via DataVault.
    from .data_vault import DataVault
    vault = DataVault()

    # Prune any previously cached preferred share data.
    vault.prune_preferred_shares()

    total = len(tickers)
    logger.info("Starting OHLCV fetch for %d tickers...", total)

    for i, ticker in enumerate(tickers, 1):
        logger.info("Fetching %s: %d of %d", ticker, i, total)
        vault.get_data(ticker)

    logger.info("Done. %d tickers processed.", total)


if __name__ == "__main__":
    main()
