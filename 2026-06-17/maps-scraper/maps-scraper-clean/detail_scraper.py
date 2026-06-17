#!/usr/bin/env python3
"""
Google Maps detail scraper — Phase 2.

For each facility from Phase 1 JSON, visits the Google Maps detail page to
collect: full address, hours, plus code, coordinates, About section, photos.

Outputs: CSV, JSON, XLSX
"""

import asyncio
import csv
import json
import logging
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

OUTPUT_DIR  = Path(__file__).parent / "outputs"
PHASE1_DIR  = OUTPUT_DIR / "phase1"
PHASE2_DIR  = OUTPUT_DIR / "phase2"
DELAY_MS    = 2500
MAX_PHOTOS  = 25
RESTART_EVERY = 10

BROWSER_ARGS = [
    "--incognito",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--window-size=1920,1080",
]
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

FIELDS = [
    # ── Phase 1 (carried over) ────────────────────────────────────────
    "name", "rating", "reviews", "category",
    "address_lane1", "phone", "status", "website", "maps_url",
    # ── Phase 2 additions ────────────────────────────────────────────
    "address",
    "plus_code", "hours",
    "about",
    "lat", "lng", "photos",
]

HEADERS = [
    "Name", "Rating", "Reviews", "Category",
    "Address Lane 1", "Phone", "Status", "Website", "Maps URL",
    "Address (Full)", "Plus Code", "Hours",
    "About", "Latitude", "Longitude", "Photos",
]


# ── Formatters ────────────────────────────────────────────────────────────────

def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]} {digits[6:]}"
    return raw.strip()


def extract_coords(url: str):
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    return (m.group(1), m.group(2)) if m else ("", "")


# ── Playwright helpers ────────────────────────────────────────────────────────

async def safe_text(locator) -> str:
    try:
        if await locator.count():
            return (await locator.first.inner_text()).strip()
    except Exception:
        pass
    return ""


async def safe_attr(locator, attr: str) -> str:
    try:
        if await locator.count():
            return (await locator.first.get_attribute(attr) or "").strip()
    except Exception:
        pass
    return ""


# ── Hours ─────────────────────────────────────────────────────────────────────

async def expand_hours(page):
    try:
        btn = page.locator(
            'button[aria-label*="hour" i][aria-expanded="false"],'
            'button[aria-label*="Hour" i][aria-expanded="false"]'
        ).first
        if await btn.count():
            await btn.click()
            await page.wait_for_timeout(700)
            return
        toggle = page.locator('[jsaction*="openhours"]').first
        if await toggle.count():
            await toggle.click()
            await page.wait_for_timeout(700)
    except Exception:
        pass


async def extract_hours(page) -> str:
    """
    Returns hours as a JSON array string, e.g.
    '["Monday: 9 am–6 pm", "Tuesday: 9 am–6 pm", ...]'
    """
    await expand_hours(page)
    entries = []
    try:
        rows = page.locator("table.eK4R0e tr, tr.y0skZc")
        for i in range(await rows.count()):
            text = re.sub(r"[ \t]+", " ", await rows.nth(i).inner_text()).replace("\n", " ").strip()
            for day in DAYS:
                if text.lower().startswith(day.lower()):
                    time_part = text[len(day):].strip().lstrip(".,: \t")
                    time_part = re.split(r"\s*\(", time_part)[0].strip()
                    if time_part:
                        entries.append(f"{day}: {time_part}")
                    break
    except Exception as e:
        log.debug("Hours error: %s", e)
    return json.dumps(entries) if entries else ""


# ── Maps About / Description ──────────────────────────────────────────────────

async def extract_maps_about(page) -> str:
    """
    Clicks the About tab on the Maps detail page.
    Reads h2.iL3Qke section headers and span[aria-label] item labels to
    produce clean text: "Accessibility: Wheelchair-accessible entrance, ..."
    """
    try:
        # Click the About tab
        clicked = False
        for sel in [
            'button[aria-label^="About"]',
            'button[data-tab-index][aria-label*="About" i]',
            '[role="tab"][aria-label*="About" i]',
        ]:
            btn = page.locator(sel).first
            if await btn.count():
                await btn.click()
                await page.wait_for_timeout(1200)
                clicked = True
                break

        if not clicked:
            return ""

        # About panel — aria-label="About <place name>" role="region"
        panel = page.locator('[aria-label*="About"][role="region"]').first
        if not await panel.count():
            panel = page.locator(".m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde").first
        try:
            await panel.wait_for(state="visible", timeout=5000)
        except Exception:
            return ""

        # Read each section: h2 header + span[aria-label] items
        sections = []
        for sec in await panel.locator("div.iP2t7d").all():
            header = (await safe_text(sec.locator("h2.iL3Qke").first)).strip()
            items = []
            for span in await sec.locator("span[aria-label]").all():
                label = re.sub(r"^Has\s+", "", (await span.get_attribute("aria-label") or "").strip(), flags=re.I)
                if label:
                    items.append(label)
            if header and items:
                sections.append(f"{header}: {', '.join(items)}")

        result = json.dumps(sections) if sections else ""

        # Go back to Overview before continuing
        for back_sel in ['button[aria-label*="Overview" i]', 'button[aria-label*="Back" i]']:
            back = page.locator(back_sel).first
            if await back.count():
                await back.click()
                await page.wait_for_timeout(500)
                break

        return result[:800]

    except Exception as e:
        log.debug("About extract error: %s", e)
    return ""


# ── Address ───────────────────────────────────────────────────────────────────

async def extract_address(page) -> str:
    """Returns the full address string as-is from the Maps detail page."""
    try:
        for sel in [
            'button[data-item-id="address"]',
            'button[aria-label^="Address"]',
            '[data-tooltip="Copy address"]',
        ]:
            el = page.locator(sel).first
            if await el.count():
                aria = re.sub(
                    r"^Address[:\s]+", "",
                    (await el.get_attribute("aria-label") or "").strip(),
                    flags=re.I,
                ).strip()
                full = aria or (await el.inner_text()).strip()
                if full:
                    # Strip trailing ", United States" suffix
                    full = re.sub(r",?\s*United States\s*$", "", full, flags=re.I).strip()
                    return full
    except Exception as e:
        log.debug("Address error: %s", e)
    return ""


# ── Photos ────────────────────────────────────────────────────────────────────

def _normalize_image_url(url: str) -> str:
    """Ported from scraper_HG_v2.py — normalize to s2000 resolution."""
    url = (url.replace("&quot;", "")
              .replace("\\u003d", "=")
              .replace("\\u0026", "&")
              .replace("&amp;",   "&"))
    url = re.sub(r"=w\d+-h\d+-k-no", "=s2000-k-no", url)
    url = re.sub(r"=s\d+-k-no",      "=s2000-k-no", url)
    return url


async def extract_photos(page) -> str:
    """
    Ported from scraper_HG_v2.get_photos():
      1. Click Photos button
      2. Wait for scroll panel  (.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde)
      3. Scroll panel to bottom to load all images
      4. Scroll back up 1800 px at a time, harvest lh3.googleusercontent URLs from source
    Returns comma-separated photo URLs.
    """
    photo_urls = []
    seen_urls  = set()

    try:
        # Step 1 — click the Photos button
        clicked = False
        for sel in ['button[aria-label*="Photos"]', 'button[aria-label*="Photo"]']:
            btn = page.locator(sel).first
            if await btn.count():
                await btn.click()
                await page.wait_for_timeout(800)
                clicked = True
                break
        if not clicked:
            return ""

        # Step 2 — wait for the scroll panel
        PANEL_CSS = ".m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde"
        panel = page.locator(PANEL_CSS).first
        try:
            await panel.wait_for(state="visible", timeout=8000)
        except Exception:
            return ""

        # Step 3 — scroll to bottom to load all images
        last_top = -1
        for _ in range(40):
            await panel.evaluate("el => el.scrollTop = el.scrollHeight")
            await page.wait_for_timeout(200)
            cur = int(await panel.evaluate("el => el.scrollTop") or 0)
            if cur == last_top:
                break
            last_top = cur

        # Step 4 — scroll back up collecting URLs from page source
        step = 1800
        cur  = last_top
        while cur > 0:
            cur = max(cur - step, 0)
            await panel.evaluate(f"el => el.scrollTop = {cur}")
            await page.wait_for_timeout(200)
            source = await page.content()
            for url in re.findall(
                r"https://lh3\.googleusercontent\.com/[^\"'\s)]+", source
            ):
                url = _normalize_image_url(url)
                if url not in seen_urls:
                    seen_urls.add(url)
                    photo_urls.append(url)
            if len(photo_urls) >= MAX_PHOTOS:
                break

        # Navigate back to the place detail page
        await page.go_back()
        await page.wait_for_timeout(1000)

    except Exception as e:
        log.debug("Photo error: %s", e)

    return ", ".join(photo_urls[:MAX_PHOTOS])


# ── Google Maps detail scraper ────────────────────────────────────────────────

async def scrape_maps_detail(page, url: str, fallback_name: str) -> dict:
    data = {f: "" for f in FIELDS}
    data["maps_url"] = url
    data["name"]     = fallback_name
    data["lat"], data["lng"] = extract_coords(url)

    try:
        await page.goto(url, wait_until="load", timeout=45_000)
        await page.wait_for_selector("h1", timeout=20_000)
        await page.wait_for_timeout(2000)
    except Exception as e:
        log.warning("Could not load Maps page for %s: %s", fallback_name, e)
        return data

    # Name
    t = await safe_text(page.locator("h1").first)
    if t:
        data["name"] = t

    # Rating + Reviews — try combined element first (aria-label="4.7 stars 187 reviews")
    for sel in ['[aria-label*="star" i]']:
        for el in await page.locator(sel).all():
            aria = (await el.get_attribute("aria-label") or "").strip()
            if not aria:
                continue
            m_rating = re.search(r"([\d.]+)\s+star", aria, re.I)
            m_review = re.search(r"([\d,]+)\s+review", aria, re.I)
            if m_rating and not data["rating"]:
                data["rating"] = m_rating.group(1)
            if m_review and not data["reviews"]:
                data["reviews"] = m_review.group(1).replace(",", "")
            if data["rating"] and data["reviews"]:
                break
        if data["rating"] and data["reviews"]:
            break

    # Fallback: review count from dedicated review button / any visible count
    if not data["reviews"]:
        for sel in [
            'button[jsaction*="review"]',
            '[aria-label*="review" i]',
            'span[aria-label*="review" i]',
            'div[aria-label*="review" i]',
        ]:
            for el in await page.locator(sel).all():
                txt = await safe_attr(el, "aria-label") or await safe_text(el)
                m = re.search(r"([\d,]+)\s+review", txt, re.I)
                if m:
                    data["reviews"] = m.group(1).replace(",", "")
                    break
            if data["reviews"]:
                break

    # Category
    for sel in ["button.DkEaL", "[jsaction*='category']", ".fontBodyMedium .DkEaL"]:
        el = page.locator(sel).first
        if await el.count():
            t = await safe_text(el)
            if t:
                data["category"] = t
                break

    # Address — full string, no splitting
    data["address"] = await extract_address(page)

    # Phone
    for sel in ['button[data-item-id^="phone"]', 'a[href^="tel:"]']:
        el = page.locator(sel).first
        if await el.count():
            raw = await safe_text(el) or re.sub(r"^tel:", "", await safe_attr(el, "href"))
            data["phone"] = normalize_phone(raw)
            break

    # Website
    for sel in ['a[data-item-id="authority"]', 'a[data-tooltip="Open website"]']:
        el = page.locator(sel).first
        if await el.count():
            data["website"] = await safe_attr(el, "href")
            break

    # Plus code
    el = page.locator('button[data-item-id="oloc"], [aria-label*="Plus code" i]').first
    if await el.count():
        data["plus_code"] = re.sub(r"\s+", " ", await safe_text(el)).strip()

    # Hours — stored as JSON array string e.g. '["Monday: 9 am–6 pm", ...]'
    data["hours"] = await extract_hours(page)

    # About — Maps About tab, JSON array of sections
    data["about"] = await extract_maps_about(page)

    # Photos
    data["photos"] = await extract_photos(page)

    return data


# ── Website scraper (scraper1.py) ─────────────────────────────────────────────

def scrape_website(website_url: str) -> dict:
    """
    Visit the facility's own website using scraper1.py helpers.
    Returns contact info + about/services text.
    """
    result = {
        "website_email":   "",
        "website_fax":     "",
        "website_phone":   "",
        "website_address": "",
        "website_social":  "",
        "website_about":   "",
        "website_services": "",
    }
    if not website_url:
        return result

    try:
        resp = requests.get(website_url, headers=WEB_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        contact = extract_contact(soup, website_url)
        result["website_email"]   = "; ".join(contact.get("emails", []))
        result["website_fax"]     = "; ".join(contact.get("faxes", []))
        result["website_phone"]   = "; ".join(
            normalize_phone(p) for p in contact.get("phones", [])
        )
        result["website_address"] = "; ".join(contact.get("addresses", []))
        result["website_social"]  = "; ".join(contact.get("social", []))

        sections = extract_sections(soup)
        about_blocks = [s for s in sections if s["type"] == "about"]
        service_blocks = [s for s in sections if s["type"] == "services"]

        if about_blocks:
            result["website_about"] = about_blocks[0]["content"][:500]
        if service_blocks:
            result["website_services"] = service_blocks[0]["content"][:500]

    except Exception as e:
        log.debug("Website scrape failed for %s: %s", website_url, e)

    return result


# ── Save helpers ──────────────────────────────────────────────────────────────

def write_row(csv_writer, csv_file, record: dict):
    csv_writer.writerow({f: record.get(f, "") for f in FIELDS})
    csv_file.flush()


# ── Browser helper ────────────────────────────────────────────────────────────

async def new_browser(p, headless: bool):
    """Launch a fresh incognito browser. Always call browser.close() when done."""
    browser = await p.chromium.launch(headless=headless, slow_mo=40, args=BROWSER_ARGS)
    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=UA,
    )
    page = await context.new_page()
    await page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return browser, page


# ── Main ──────────────────────────────────────────────────────────────────────

async def scrape_city(p, city_slug: str, query_s: str, facilities: list, headless: bool) -> list[dict]:
    """
    Scrape detail pages for one (city × query) set.
    Restarts browser every RESTART_EVERY facilities.
    Saves {city_slug}_phase2_{query_s}.csv
    """
    if not facilities:
        return []

    csv_path   = PHASE2_DIR / f"{city_slug}_phase2_{query_s}.csv"
    csv_file   = open(csv_path, "w", newline="", encoding="utf-8")
    csv_writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
    csv_writer.writeheader()
    csv_file.flush()

    results = []
    browser = page = None

    try:
        async with async_playwright() as p_inner:
            for idx, fac in enumerate(facilities, start=1):
                url  = fac.get("maps_url", "")
                name = fac.get("name", f"Facility {idx}")

                # Launch / restart browser every RESTART_EVERY
                if browser is None or (idx - 1) % RESTART_EVERY == 0:
                    if browser:
                        await browser.close()
                        log.info("  [%s] Browser closed — restarting at #%d", city_slug, idx)
                    browser, page = await new_browser(p_inner, headless)
                    log.info("  [%s] Browser started", city_slug)

                log.info("[%s] %d/%d %s", city_slug, idx, len(facilities), name)

                detail = await scrape_maps_detail(page, url, name)

                # Carry over Phase 1 fields as fallback
                for field in ("name", "rating", "reviews", "category",
                              "address_lane1", "phone", "status", "website"):
                    if not detail.get(field) and fac.get(field):
                        detail[field] = fac[field]

                results.append(detail)
                write_row(csv_writer, csv_file, detail)
                log.info("  ✓ [%s] %d/%d saved", city_slug, idx, len(facilities))

                await page.wait_for_timeout(DELAY_MS)

            if browser:
                await browser.close()
                log.info("  [%s] Browser closed (done)", city_slug)

    finally:
        csv_file.close()

    log.info("CSV  → %s", csv_path)
    return results


async def scrape_all(headless: bool = True, limit: int = 0, city: str = "", workers: int = 1):
    """
    Reads *_phase1_*.csv files and runs Phase 2.
    Skips any (city, query) pair whose phase2 CSV already exists.
    workers > 1 processes multiple files concurrently.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    PHASE1_DIR.mkdir(exist_ok=True)
    PHASE2_DIR.mkdir(exist_ok=True)

    phase1_files = sorted(PHASE1_DIR.glob("*_phase1_*.csv"))
    if city:
        slug = city.lower().replace(" ", "_").replace(".", "")
        phase1_files = [f for f in phase1_files if f.stem.startswith(f"{slug}_phase1_")]

    if not phase1_files:
        log.error("No *_phase1_*.csv files found in %s", PHASE1_DIR)
        sys.exit(1)

    # Build work list — skip phase2 files that are complete (same row count as phase1)
    work = []
    for phase1_file in phase1_files:
        parts = phase1_file.stem.split("_phase1_", 1)
        city_s  = parts[0]
        query_s = parts[1] if len(parts) > 1 else ""
        phase2_csv = PHASE2_DIR / f"{city_s}_phase2_{query_s}.csv"
        if phase2_csv.exists():
            p1_rows = sum(1 for _ in phase1_file.open()) - 1  # subtract header
            p2_rows = sum(1 for _ in phase2_csv.open()) - 1
            if p2_rows >= p1_rows:
                log.info("Skip (done): %s | %s (%d rows)", city_s, query_s, p2_rows)
                continue
            log.info("Incomplete phase2 detected: %s | %s (phase1=%d, phase2=%d) — redoing", city_s, query_s, p1_rows, p2_rows)
            phase2_csv.unlink()
        work.append((phase1_file, city_s, query_s))

    if not work:
        log.info("All phase2 files already done.")
        return []

    log.info("%d files to process with %d worker(s).", len(work), workers)

    sem = asyncio.Semaphore(workers)

    async def process(phase1_file, city_s, query_s):
        async with sem:
            log.info("=== %s | %s ===", city_s, query_s)
            with open(phase1_file, newline="", encoding="utf-8") as f:
                facilities = list(csv.DictReader(f))
            seen, unique = set(), []
            for fac in facilities:
                u = fac.get("maps_url", "")
                if u and u not in seen:
                    seen.add(u)
                    unique.append(fac)
            if limit:
                unique = unique[:limit]
            return await scrape_city(None, city_s, query_s, unique, headless)

    results = await asyncio.gather(*[process(f, c, q) for f, c, q in work])
    all_results = [r for batch in results if batch for r in batch]
    log.info("All done. Total: %d facilities.", len(all_results))
    return all_results


async def _phase2_worker(worker_id: int, queue: asyncio.Queue, headless: bool):
    """One Phase 2 worker — pulls (city_slug, query_slug) tuples from queue until sentinel."""
    while True:
        item = await queue.get()
        if item is None:
            queue.put_nowait(None)   # re-add sentinel for other workers
            log.info("Phase 2 worker %d done.", worker_id)
            break
        city_s, query_s = item
        phase1_csv = PHASE1_DIR / f"{city_s}_phase1_{query_s}.csv"
        if not phase1_csv.exists():
            log.warning("Phase 2 [W%d] — %s not found, skipping.", worker_id, phase1_csv)
            continue
        # Resume: skip if phase2 CSV is already complete
        phase2_csv = PHASE2_DIR / f"{city_s}_phase2_{query_s}.csv"
        if phase2_csv.exists():
            p1_rows = sum(1 for _ in phase1_csv.open(encoding="utf-8")) - 1
            p2_rows = sum(1 for _ in phase2_csv.open(encoding="utf-8")) - 1
            if p2_rows >= p1_rows > 0:
                log.info("Phase 2 [W%d] — skip (done): %s | %s (%d rows)", worker_id, city_s, query_s, p2_rows)
                continue
        log.info("Phase 2 [W%d] — %s | %s", worker_id, city_s, query_s)
        with open(phase1_csv, newline="", encoding="utf-8") as f:
            facilities = list(csv.DictReader(f))
        seen, unique = set(), []
        for fac in facilities:
            u = fac.get("maps_url", "")
            if u and u not in seen:
                seen.add(u)
                unique.append(fac)
        await scrape_city(None, city_s, query_s, unique, headless)


async def scrape_from_queue(queue: asyncio.Queue, headless: bool = True, workers: int = 2):
    """
    Runs `workers` Phase 2 workers in parallel, each consuming from the queue.
    Phase 1 feeds city slugs in; workers process them concurrently.
    """
    PHASE2_DIR.mkdir(exist_ok=True)
    await asyncio.gather(*[
        _phase2_worker(i + 1, queue, headless) for i in range(workers)
    ])


async def main(headless: bool = True, limit: int = 0, city: str = "", workers: int = 1):
    await scrape_all(headless=headless, limit=limit, city=city, workers=workers)


if __name__ == "__main__":
    headless  = "--visible" not in sys.argv
    limit_arg = next((int(a) for a in sys.argv[1:] if a.isdigit()), 0)
    city_arg  = next((a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()), "")
    asyncio.run(main(headless=headless, limit=limit_arg, city=city_arg))
