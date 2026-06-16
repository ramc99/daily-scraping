#!/usr/bin/env python3
"""
Phase 2 entry point — detail scraper per city.

Reads all {city}_phase1.json files from outputs/ and produces {city}_phase2 files.

Usage:
    python run_details.py                   # all cities, headless
    python run_details.py Birmingham        # single city
    python run_details.py Birmingham 5      # single city, first 5 (testing)
    python run_details.py --visible         # visible browser
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from detail_scraper import main

if __name__ == "__main__":
    headless  = "--visible" not in sys.argv
    limit_arg = next((int(a) for a in sys.argv[1:] if a.isdigit()), 0)
    city_arg  = next((a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()), "")
    asyncio.run(main(headless=headless, limit=limit_arg, city=city_arg))
