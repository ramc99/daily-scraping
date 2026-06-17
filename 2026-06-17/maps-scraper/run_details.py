#!/usr/bin/env python3
"""
Phase 2 standalone entry point.

Reads *_phase1_*.csv files, skips any city+query already done, runs Phase 2.

Usage:
    python run_details.py                        # all remaining, 1 worker, headless
    python run_details.py --workers 3            # 3 concurrent workers
    python run_details.py Houston                # single city
    python run_details.py Houston 5              # single city, first 5 (testing)
    python run_details.py --visible              # visible browser
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from detail_scraper import main

if __name__ == "__main__":
    headless    = "--visible" not in sys.argv
    limit_arg   = next((int(a) for a in sys.argv[1:] if a.isdigit()), 0)
    workers_arg = next((int(a.split("=")[1]) for a in sys.argv[1:] if a.startswith("--workers")), 1)
    city_arg    = next((a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()), "")
    asyncio.run(main(headless=headless, limit=limit_arg, city=city_arg, workers=workers_arg))
