"""
Sitemap Monitor for IP First Response.

Fetches the IPFR sitemap via Selenium stealth (site is behind a WAF),
extracts /options/ URLs, compares against metatable-Content.csv,
and appends new entries for any discovered pages.

Can be run manually or on a weekly schedule via GitHub Actions.
"""

import csv
import os
import sys
import re
import logging
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
    """Fetches sitemap XML content via Selenium and returns parsed URLs."""
    logger.info(f"Fetching sitemap: {url}")
    driver.get(url)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.TAG_NAME, 'body'))
    )

    page_source = driver.page_source

    # The browser may wrap XML in an HTML document; extract the XML content.
    # Try to find raw XML in the page source first.
    urls = []

    # Try parsing as XML directly from page source
    # Browsers often render XML inside <pre> or directly
    try:
        # Strip any HTML wrapper the browser may add
        xml_match = re.search(r'(<\?xml.*?\?>.*?</(?:urlset|sitemapindex)>)',
                              page_source, re.DOTALL)
        if xml_match:
            xml_content = xml_match.group(1)
        else:
            # Try getting just the text content (browser-rendered XML)
            body = driver.find_element(By.TAG_NAME, 'body')
            xml_content = body.text
            # If body text doesn't look like XML, try page_source with tag stripping
            if '<loc>' not in xml_content and '<loc>' in page_source:
                xml_content = page_source

        # Parse XML - handle namespace
        # Remove default namespace to simplify parsing
        xml_content = re.sub(r'\sxmlns="[^"]+"', '', xml_content)
        root = ElementTree.fromstring(xml_content)

        # Check if this is a sitemap index
        sitemapindex_entries = root.findall('.//sitemap/loc')
        if sitemapindex_entries:
            logger.info(f"Found sitemap index with {len(sitemapindex_entries)} sub-sitemaps")
            for loc in sitemapindex_entries:
                sub_urls = fetch_sitemap(driver, loc.text.strip())
                urls.extend(sub_urls)
        else:
            # Regular sitemap - extract URLs
            for loc in root.findall('.//url/loc'):
                urls.append(loc.text.strip())

    except ElementTree.ParseError:
        # Fallback: extract URLs via regex from raw source
        logger.warning("XML parsing failed, falling back to regex extraction")
        loc_matches = re.findall(r'<loc>\s*(https?://[^<]+)\s*</loc>', page_source)
        urls.extend(loc_matches)

    logger.info(f"Extracted {len(urls)} total URLs from sitemap")
    return urls


def filter_options_urls(urls):
    """Filter URLs to only include /options/ paths."""
    filtered = []
    for url in urls:
        parsed = urlparse(url)
        if OPTIONS_PATH_PREFIX in parsed.path:
            filtered.append(url)
    return filtered


def read_existing_csv(csv_path):
    """Read existing CSV and return rows, fieldnames, and set of existing URLs."""
    rows = []
    fieldnames = []
    existing_urls = set()

    if not os.path.exists(csv_path):
        logger.error(f"CSV file not found: {csv_path}")
        return rows, fieldnames, existing_urls

    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
            url = row.get('Canonical-url', '').strip()
            if url:
                existing_urls.add(url)

    logger.info(f"Read {len(rows)} existing entries from CSV")
    return rows, fieldnames, existing_urls


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
    # Capitalize first letter only
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

    # Rewrite the full CSV to preserve formatting
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
        # Running locally - just log it
        logger.info(f"[Output] {name}={value}")


def main():
    # Read existing CSV
    rows, fieldnames, existing_urls = read_existing_csv(CSV_FILE)
    if not fieldnames:
        logger.critical(f"Could not read CSV headers from {CSV_FILE}")
        sys.exit(1)

    # Initialize browser
    driver = initialize_driver()
    if not driver:
        logger.critical("Failed to initialize browser")
        sys.exit(1)

    try:
        # Fetch and parse sitemap
        all_urls = fetch_sitemap(driver, SITEMAP_URL)
        options_urls = filter_options_urls(all_urls)
        logger.info(f"Found {len(options_urls)} /options/ URLs in sitemap")

        # Compare with existing CSV
        new_urls = [url for url in options_urls if url not in existing_urls]
        logger.info(f"New URLs not in CSV: {len(new_urls)}")

        if new_urls:
            next_num = get_next_udid(rows)
            append_new_urls(CSV_FILE, fieldnames, rows, new_urls, next_num)
            set_github_output('new_urls_found', 'true')
            set_github_output('new_url_count', str(len(new_urls)))
            logger.info(f"SUCCESS: Added {len(new_urls)} new URLs to {CSV_FILE}")
        else:
            set_github_output('new_urls_found', 'false')
            set_github_output('new_url_count', '0')
            logger.info("No new URLs found - CSV is up to date")

    except Exception as e:
        logger.error(f"Error during sitemap check: {e}")
        set_github_output('new_urls_found', 'false')
        set_github_output('new_url_count', '0')
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("--- Sitemap Check Complete ---")


if __name__ == "__main__":
    main()
