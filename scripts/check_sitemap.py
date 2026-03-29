"""
Sitemap Monitor for IP First Response.

Fetches the IPFR sitemap via Selenium stealth (site is behind a WAF),
extracts /options/ URLs, compares against metatable-Content.csv,
and appends new entries for any discovered pages.

Also detects pages already in the CSV whose sitemap <lastmod> date is
newer than the recorded Last-updated value, and flags them for re-scraping.

Can be run manually or on a weekly schedule via GitHub Actions.
"""

import csv
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
CSV_FILE = 'metatable-Content.csv'
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


def read_existing_csv(csv_path):
    """Read existing CSV and return rows, fieldnames, set of existing URLs,
    and a dict mapping url -> Last-updated string."""
    rows = []
    fieldnames = []
    existing_urls = set()
    url_last_updated = {}

    if not os.path.exists(csv_path):
        logger.error(f"CSV file not found: {csv_path}")
        return rows, fieldnames, existing_urls, url_last_updated

    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
            url = row.get('Canonical-url', '').strip()
            if url:
                existing_urls.add(url)
                url_last_updated[url] = row.get('Last-updated', '').strip()

    logger.info(f"Read {len(rows)} existing entries from CSV")
    return rows, fieldnames, existing_urls, url_last_updated


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


def append_new_urls(csv_path, fieldnames, existing_rows, new_urls, next_udid_num):
    """Append new URL entries to the CSV file without modifying existing rows."""
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

    with open(csv_path, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info(f"Appended {len(new_rows)} new entries to {csv_path}")
    return new_rows


def set_github_output(name, value):
    """Set a GitHub Actions output variable."""
    output_file = os.environ.get('GITHUB_OUTPUT')
    if output_file:
        with open(output_file, 'a') as f:
            f.write(f"{name}={value}\n")
    else:
        logger.info(f"[Output] {name}={value}")


def main():
    # Read existing CSV
    rows, fieldnames, existing_urls, url_last_updated = read_existing_csv(CSV_FILE)
    if not fieldnames:
        logger.critical(f"Could not read CSV headers from {CSV_FILE}")
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

        # --- Detect new pages (not yet in CSV) ---
        new_urls = {url: lm for url, lm in options_url_map.items()
                    if url not in existing_urls}
        logger.info(f"New URLs not in CSV: {len(new_urls)}")

        # --- Detect updated pages (in CSV, but sitemap lastmod is newer) ---
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

        logger.info(f"Updated URLs (sitemap newer than CSV): {len(updated_urls)}")

        # --- Act on new pages ---
        if new_urls:
            next_num = get_next_udid(rows)
            append_new_urls(CSV_FILE, fieldnames, rows, list(new_urls.keys()), next_num)
            logger.info(f"SUCCESS: Added {len(new_urls)} new URLs to {CSV_FILE}")

        # --- Set GitHub Actions outputs ---
        needs_rescrape = bool(new_urls or updated_urls)

        set_github_output('new_urls_found',     'true' if new_urls else 'false')
        set_github_output('new_url_count',      str(len(new_urls)))
        set_github_output('updated_urls_found', 'true' if updated_urls else 'false')
        set_github_output('updated_url_count',  str(len(updated_urls)))
        set_github_output('needs_rescrape',     'true' if needs_rescrape else 'false')

        if not needs_rescrape:
            logger.info("No new or updated URLs found - CSV is up to date")

    except Exception as e:
        logger.error(f"Error during sitemap check: {e}")
        set_github_output('new_urls_found',     'false')
        set_github_output('new_url_count',      '0')
        set_github_output('updated_urls_found', 'false')
        set_github_output('updated_url_count',  '0')
        set_github_output('needs_rescrape',     'false')
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("--- Sitemap Check Complete ---")


if __name__ == "__main__":
    main()
