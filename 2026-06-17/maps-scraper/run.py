#!/usr/bin/env python3
"""
Combined runner — Phase 1 and Phase 2 run concurrently.

Phase 1 scrapes each city and immediately signals Phase 2.
Phase 2 starts processing a city as soon as Phase 1 finishes it.

Usage:
    python run.py              # headless (default)
    python run.py --visible    # visible browser
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scraper import scrape
from detail_scraper import scrape_from_queue


async def main():
    headless = "--visible" not in sys.argv
    queue    = asyncio.Queue()

    await asyncio.gather(
        scrape(headless=headless, queue=queue),
        scrape_from_queue(queue, headless=headless),
    )


if __name__ == "__main__":
    asyncio.run(main())
