"""
Sitemap Monitor for IP First Response.

Fetches the IPFR sitemap via Selenium stealth (site is behind a WAF),
extracts /options/ URLs, compares against metatable-Content.jsonl,
and appends new entries for any discovered pages.

Also detects pages already in the JSONL whose sitemap <lastmod> date is
newer than the recorded Last-updated value, and flags them for re-scraping.

Detects and removes JSONL entries whose URLs no longer appear in the sitemap,
logging each deletion loudly so they are easy to spot in the action log.

Can be run manually or on a weekly schedule via GitHub Actions.
"""

import json
import os
import sys
import re
import logging
from datetime import datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# --- Configuration ---
SITEMAP_URL = 'https://ipfirstresponse.ipaustralia.gov.au/sitemap.xml'
JSONL_FILE = 'metatable-Content.jsonl'
OPTIONS_PATH_PREFIX = '/options/'
UDID_PREFIX = 'A'
UDID_START = 1000

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SitemapMonitor")


def initialize_driver():
    """Sets up a stealthy Headless Chrome driver (same config as scraper)."""
    logger.info("Initializing Selenium Driver...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument(
        'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
    )

    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True)
        return driver
    except Exception as e:
        logger.error(f"Failed to initialize WebDriver: {e}")
        return None


def fetch_sitemap(driver, url):
    """Fetches sitemap XML via the browser's XHR (bypasses Chrome's XML viewer)
    and returns a dict mapping url -> lastmod string (or None if absent).

    Handles sitemap index files by recursively fetching sub-sitemaps.
    """
    logger.info(f"Fetching sitemap: {url}")

    # Navigate first so cookies / WAF session tokens are established,
    # then use a synchronous XHR inside the same browser context to retrieve
    # the raw XML text before Chrome has a chance to render it into its
    # shadow-DOM XML viewer (which hides <loc> tags from page_source).
    driver.get(url)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.TAG_NAME, 'body'))
    )

    xml_text = driver.execute_script("""
        var xhr = new XMLHttpRequest();
        xhr.open('GET', arguments[0], false);
        xhr.send(null);
        return xhr.responseText;
    """, url)

    url_map = {}  # url -> lastmod (str or None)

    try:
        # Strip default XML namespace so ElementTree findall paths stay simple
        xml_clean = re.sub(r'\sxmlns(?::[^=]+)?="[^"]+"', '', xml_text)
        root = ElementTree.fromstring(xml_clean)

        # Sitemap index — recurse into each sub-sitemap
        sitemapindex_entries = root.findall('.//sitemap/loc')
        if sitemapindex_entries:
            logger.info(f"Found sitemap index with {len(sitemapindex_entries)} sub-sitemaps")
            for loc_el in sitemapindex_entries:
                sub_map = fetch_sitemap(driver, loc_el.text.strip())
                url_map.update(sub_map)
        else:
            # Regular sitemap — collect loc + optional lastmod per <url> block
            for url_el in root.findall('.//url'):
                loc_el = url_el.find('loc')
                if loc_el is None or not loc_el.text:
                    continue
                loc = loc_el.text.strip()
                lastmod_el = url_el.find('lastmod')
                lastmod = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else None
                url_map[loc] = lastmod

    except ElementTree.ParseError:
        logger.warning("XML parsing failed, falling back to regex extraction")
        # Capture loc and the immediately following lastmod (if any)
        for loc, lastmod in re.findall(
            r'<loc>\s*(https?://[^<]+)\s*</loc>'
            r'(?:\s*<lastmod>\s*([^<]*?)\s*</lastmod>)?',
            xml_text
        ):
            url_map[loc.strip()] = lastmod.strip() if lastmod else None

    logger.info(f"Extracted {len(url_map)} total URLs from sitemap")
    return url_map


def filter_options_urls(url_map):
    """Filter url_map to only include /options/ paths."""
    return {
        url: lastmod
        for url, lastmod in url_map.items()
        if OPTIONS_PATH_PREFIX in urlparse(url).path
    }


def parse_sitemap_date(date_str):
    """Parse an ISO 8601 lastmod string to a date object, or None."""
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(s[:len(fmt)], fmt)
            return dt.date()
        except ValueError:
            continue
    logger.debug(f"Could not parse sitemap date: {date_str!r}")
    return None


def parse_csv_date(date_str):
    """Parse a DD/MM/YYYY Last-updated string to a date object, or None."""
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in ('%d/%m/%Y', '%-d/%-m/%Y', '%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    logger.debug(f"Could not parse CSV date: {date_str!r}")
    return None


def read_existing_jsonl(jsonl_path):
    """Read existing JSONL and return rows, set of existing URLs,
    and a dict mapping url -> Last-updated string."""
    rows = []
    existing_urls = set()
    url_last_updated = {}

    if not os.path.exists(jsonl_path):
        logger.error(f"JSONL file not found: {jsonl_path}")
        return rows, existing_urls, url_last_updated

    with open(jsonl_path, mode='r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rows.append(row)
            url = row.get('Canonical-url', '').strip()
            if url:
                existing_urls.add(url)
                url_last_updated[url] = row.get('Last-updated', '').strip()

    logger.info(f"Read {len(rows)} existing entries from JSONL")
    return rows, existing_urls, url_last_updated


def get_next_udid(rows):
    """Find the next available A-prefix UDID number."""
    max_num = UDID_START - 1
    pattern = re.compile(rf'^{UDID_PREFIX}(\d+)$')

    for row in rows:
        udid = row.get('UDID', '').strip()
        match = pattern.match(udid)
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num

    return max_num + 1


def title_from_slug(url):
    """Derive a human-readable title from a URL slug.

    Example: /options/register-your-trade-mark -> Register your trade mark
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip('/')
    slug = path.split('/')[-1]
    title = slug.replace('-', ' ').strip()
    if title:
        title = title[0].upper() + title[1:]
    return title


def _write_jsonl(jsonl_path, rows):
    """Write a list of row dicts to a JSONL file."""
    with open(jsonl_path, mode='w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def append_new_urls(jsonl_path, existing_rows, new_urls, next_udid_num):
    """Append new URL entries to the JSONL file without modifying existing rows."""
    # Derive the field order from the first existing row so new rows match
    fieldnames = list(existing_rows[0].keys()) if existing_rows else [
        'UDID', 'Overtitle', 'Main-title', 'Description', 'Canonical-url',
        'Entry-point', 'Relevant-ip-right', 'Estimate-cost', 'Estimated-effort',
        'Resolution-rate', 'Archectype', 'Provider', 'Publication-date',
        'Last-updated', 'Additional-disclaimer', 'Keywords',
    ]

    new_rows = []
    for i, url in enumerate(sorted(new_urls)):
        udid = f"{UDID_PREFIX}{next_udid_num + i}"
        title = title_from_slug(url)

        new_row = {field: '' for field in fieldnames}
        new_row['UDID'] = udid
        new_row['Main-title'] = title
        new_row['Canonical-url'] = url

        new_rows.append(new_row)
        logger.info(f"  New entry: {udid} - {title} ({url})")

    all_rows = existing_rows + new_rows
    _write_jsonl(jsonl_path, all_rows)

    logger.info(f"Appended {len(new_rows)} new entries to {jsonl_path}")
    return new_rows


def remove_deleted_urls(jsonl_path, existing_rows, deleted_urls):
    """Remove rows for URLs no longer present in the sitemap.

    Logs each deletion loudly at WARNING/ERROR level so they are impossible
    to miss in the GitHub Actions log, then rewrites the JSONL without them.
    Returns the number of rows removed.
    """
    sep = "!" * 70
    logger.warning(sep)
    logger.warning(
        f"!!! SITEMAP DELETION ALERT: "
        f"{len(deleted_urls)} URL(s) no longer appear in the sitemap !!!"
    )
    logger.warning(sep)
    for url in sorted(deleted_urls):
        logger.error(f"  [DELETED FROM JSONL] {url}")
    logger.warning(sep)

    kept_rows = [
        row for row in existing_rows
        if row.get('Canonical-url', '').strip() not in deleted_urls
    ]
    removed_count = len(existing_rows) - len(kept_rows)

    _write_jsonl(jsonl_path, kept_rows)

    logger.warning(sep)
    logger.error(
        f"!!! {removed_count} row(s) permanently deleted from {jsonl_path} !!!"
    )
    logger.warning(sep)
    return removed_count


def set_github_output(name, value):
    """Set a GitHub Actions output variable."""
    output_file = os.environ.get('GITHUB_OUTPUT')
    if output_file:
        with open(output_file, 'a') as f:
            f.write(f"{name}={value}\n")
    else:
        logger.info(f"[Output] {name}={value}")


def main():
    # Read existing JSONL
    rows, existing_urls, url_last_updated = read_existing_jsonl(JSONL_FILE)
    if not rows:
        logger.critical(f"Could not read entries from {JSONL_FILE}")
        sys.exit(1)

    # Initialize browser
    driver = initialize_driver()
    if not driver:
        logger.critical("Failed to initialize browser")
        sys.exit(1)

    try:
        # Fetch and parse sitemap (returns url -> lastmod dict)
        all_url_map = fetch_sitemap(driver, SITEMAP_URL)
        options_url_map = filter_options_urls(all_url_map)
        logger.info(f"Found {len(options_url_map)} /options/ URLs in sitemap")

        # --- Detect new pages (not yet in JSONL) ---
        new_urls = {url: lm for url, lm in options_url_map.items()
                    if url not in existing_urls}
        logger.info(f"New URLs not in JSONL: {len(new_urls)}")

        # --- Detect updated pages (in JSONL, but sitemap lastmod is newer) ---
        updated_urls = {}
        for url, lastmod in options_url_map.items():
            if url not in existing_urls:
                continue  # handled above as new
            sitemap_date = parse_sitemap_date(lastmod)
            csv_date = parse_csv_date(url_last_updated.get(url, ''))
            if sitemap_date and csv_date and sitemap_date > csv_date:
                updated_urls[url] = lastmod
                logger.info(
                    f"  Updated page detected: {url}"
                    f" (sitemap: {sitemap_date}, csv: {csv_date})"
                )

        logger.info(f"Updated URLs (sitemap newer than JSONL): {len(updated_urls)}")

        # --- Detect deleted pages (in JSONL but absent from sitemap) ---
        # Only compare /options/ URLs so non-options JSONL rows are never flagged.
        existing_options_urls = {
            url for url in existing_urls
            if OPTIONS_PATH_PREFIX in urlparse(url).path
        }
        deleted_urls = existing_options_urls - set(options_url_map.keys())
        logger.info(f"URLs in JSONL but absent from sitemap: {len(deleted_urls)}")

        # --- Act on new pages ---
        if new_urls:
            next_num = get_next_udid(rows)
            append_new_urls(JSONL_FILE, rows, list(new_urls.keys()), next_num)
            logger.info(f"SUCCESS: Added {len(new_urls)} new URLs to {JSONL_FILE}")

        # --- Act on deleted pages ---
        if deleted_urls:
            # Re-read rows so we work on the post-append state when both
            # additions and deletions occur in the same run.
            current_rows, _, _ = read_existing_jsonl(JSONL_FILE)
            remove_deleted_urls(JSONL_FILE, current_rows, deleted_urls)

        # --- Set GitHub Actions outputs ---
        needs_rescrape = bool(new_urls or updated_urls)
        jsonl_changed = bool(new_urls or deleted_urls)

        set_github_output('new_urls_found',     'true' if new_urls else 'false')
        set_github_output('new_url_count',      str(len(new_urls)))
        set_github_output('updated_urls_found', 'true' if updated_urls else 'false')
        set_github_output('updated_url_count',  str(len(updated_urls)))
        set_github_output('deleted_urls_found', 'true' if deleted_urls else 'false')
        set_github_output('deleted_url_count',  str(len(deleted_urls)))
        set_github_output('needs_rescrape',     'true' if needs_rescrape else 'false')
        set_github_output('csv_changed',        'true' if jsonl_changed else 'false')

        if not (needs_rescrape or deleted_urls):
            logger.info("No new, updated, or deleted URLs found - JSONL is up to date")

    except Exception as e:
        logger.error(f"Error during sitemap check: {e}")
        set_github_output('new_urls_found',     'false')
        set_github_output('new_url_count',      '0')
        set_github_output('updated_urls_found', 'false')
        set_github_output('updated_url_count',  '0')
        set_github_output('deleted_urls_found', 'false')
        set_github_output('deleted_url_count',  '0')
        set_github_output('needs_rescrape',     'false')
        set_github_output('csv_changed',        'false')
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("--- Sitemap Check Complete ---")


if __name__ == "__main__":
    main()
