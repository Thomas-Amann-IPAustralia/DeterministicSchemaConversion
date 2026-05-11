import csv
import os
import sys
import time
import random
import logging
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth
from markdownify import markdownify as md

# --- Configuration ---
CSV_FILE = 'metatable-Content.csv'
OUTPUT_DIR = 'IPFR-Webpages'
HTML_OUTPUT_DIR = 'IPFR-Webpages-html'
REPORTS_DIR = os.path.join('DeterministicSchemaConversion', 'reports', 'scrape_reports')

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Scraper")

def initialize_driver():
    """Sets up a stealthy Headless Chrome driver."""
    logger.info("  -> Initializing Selenium Driver...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
    
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
        )
        return driver
    except Exception as e:
        logger.error(f"  [x] Failed to initialize WebDriver: {e}")
        return None

def normalize_text(text):
    """Replaces smart quotes and dashes with standard ASCII versions."""
    replacements = {
        '\u2018': "'",  # Left single quote
        '\u2019': "'",  # Right single quote
        '\u201c': '"',  # Left double quote
        '\u201d': '"',  # Right double quote
        '\u2013': '-',  # En dash
        '\u2014': '--', # Em dash
        '…': '...',     # Ellipsis
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

def clean_markdown(text, url, title, overtitle):
    """Post-processing to match the 'Ideal' format."""
    text = normalize_text(text)
    text = re.sub(r'^## ', '### ', text, flags=re.MULTILINE)
    text = re.sub(r'(\]\([^\)]+\))\s+\.', r'\1.', text)
    text = re.sub(r'(\]\([^\)]+\))\s+,', r'\1,', text)

    noise_patterns = [
        r'Was this information useful\?',
        r'Thumbs UpThumbs Down',
        r'\[Give feedback.*?\]\([^\)]+\)', 
        r'\(Opens in a new tab/window\)',
        r'Opens in a new tab/window'
    ]
    for pattern in noise_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)

    disclaimer_start = "This IP First Response website has been designed"
    if disclaimer_start in text:
        if f"*{disclaimer_start}" not in text: 
            pattern = r'(' + re.escape(disclaimer_start) + r'.*?)(\n\n|$)'
            text = re.sub(pattern, r'*\1*\2', text, count=1, flags=re.DOTALL)

    text = re.sub(r'([^\n])\n(### )', r'\1\n\n\2', text)
    
    header_block = f'PageURL: "[{url}]({url})"\n\n'
    
    if overtitle:
        header_block += f"## {overtitle}\n\n"
    
    if title:
        header_block += f"# {title}\n\n"

    final_text = header_block + text.strip()
    final_text = re.sub(r'\n{3,}', '\n\n', final_text)
    
    return final_text

def sanitize_filename(name):
    """Removes illegal characters from filenames."""
    if not name:
        return "Untitled"
    cleaned = re.sub(r'[\\/*?:"<>|]', "", str(name))
    return cleaned.strip()


def strip_bom_fieldnames(reader):
    """Strip any stray BOM characters left on the first column name.

    Python's `utf-8-sig` codec only strips a single BOM; a CSV that has
    been written by a tool that prepends a BOM to an already-BOM'd file
    will leave a `\\ufeff` glued to the first fieldname, silently breaking
    every `row.get('UDID', ...)` lookup in the pipeline.
    """
    if reader.fieldnames and reader.fieldnames[0]:
        reader.fieldnames[0] = reader.fieldnames[0].lstrip("﻿")


def reconcile_output_dirs(expected_basenames, md_dir, html_dir, logger):
    """Delete stale .md and .html files that don't correspond to any
    current CSV row.  expected_basenames is the set of filename stems
    (without extension) the scraper should have produced this run.

    Returns (md_removed_count, html_removed_count).
    """
    md_removed = 0
    html_removed = 0

    if os.path.isdir(md_dir):
        for entry in os.listdir(md_dir):
            if not entry.endswith(".md"):
                continue
            stem = entry[:-3]
            if stem in expected_basenames:
                continue
            path = os.path.join(md_dir, entry)
            try:
                os.remove(path)
                md_removed += 1
                logger.warning(f"  [RECONCILE] Removed stale markdown: {entry}")
            except OSError as e:
                logger.error(f"  [RECONCILE] Failed to remove {entry}: {e}")

    if os.path.isdir(html_dir):
        for entry in os.listdir(html_dir):
            if not entry.endswith("-html.html"):
                continue
            stem = entry[: -len("-html.html")]
            if stem in expected_basenames:
                continue
            path = os.path.join(html_dir, entry)
            try:
                os.remove(path)
                html_removed += 1
                logger.warning(f"  [RECONCILE] Removed stale html: {entry}")
            except OSError as e:
                logger.error(f"  [RECONCILE] Failed to remove {entry}: {e}")

    return md_removed, html_removed

def save_session_report(report_data):
    """Saves a rich CSV report of the scraping session."""
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"scrape_report_{timestamp}.csv"
    report_path = os.path.join(REPORTS_DIR, report_filename)
    
    fieldnames = [
        "Timestamp", "UDID", "Filename", "URL", "Status", 
        "Error_Message", "HTML_Size_Bytes", "MD_Size_Bytes", "Title_Detected"
    ]
    
    try:
        with open(report_path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in report_data:
                writer.writerow(row)
        logger.info(f"--- Session Report Saved: {report_path} ---")
    except Exception as e:
        logger.error(f"Failed to save session report: {e}")

def fetch_and_convert(driver, url):
    """
    Scrapes URL via Selenium and returns content + telemetry.
    Returns: (markdown_text, html_content, telemetry_dict)
    """
    telemetry = {
        "status": "FAILURE",
        "error": "",
        "html_len": 0,
        "md_len": 0,
        "title_found": False
    }

    try:
        logger.info(f"Processing: {url}")
        driver.get(url)
        
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(random.uniform(2.0, 4.0)) 

        # --- STEP 1: Metadata Extraction ---
        page_title = ""
        page_overtitle = ""
        
        try:
            page_title = driver.find_element(By.TAG_NAME, "h1").text.strip()
            if page_title:
                telemetry["title_found"] = True
        except:
            pass

        try:
            overtitle_elem = driver.find_element(By.CLASS_NAME, "option-detail-page-tag")
            page_overtitle = overtitle_elem.text.strip()
        except:
            pass

        # --- STEP 2: Main Content Extraction ---
        content_html = ""
        try:
            try:
                main_element = driver.find_element(By.TAG_NAME, "main")
                content_html = main_element.get_attribute('innerHTML')
            except:
                main_element = driver.find_element(By.CLASS_NAME, "region-content")
                content_html = main_element.get_attribute('innerHTML')
        except Exception as e:
            logger.warning(f"  [!] Could not isolate main content, using body. ({e})")
            content_html = driver.find_element(By.TAG_NAME, "body").get_attribute('innerHTML')

        telemetry["html_len"] = len(content_html)

        # --- STEP 3: Convert ---
        markdown_text = md(
            content_html, 
            heading_style="ATX",
            strip=['script', 'style', 'iframe', 'noscript', 'button'],
            newline_style="BACKSLASH"
        )

        if not markdown_text:
            telemetry["error"] = "Markdownify returned empty string"
            logger.warning(f"  [!] Markdownify produced empty text for {url}")
            return None, None, telemetry

        # --- STEP 4: Clean and Polish ---
        final_markdown = clean_markdown(markdown_text, url, page_title, page_overtitle)
        
        telemetry["md_len"] = len(final_markdown)
        telemetry["status"] = "SUCCESS"
        
        return final_markdown, content_html, telemetry

    except Exception as e:
        telemetry["error"] = str(e)
        logger.error(f"  [x] Error scraping {url}: {e}")
        return None, None, telemetry

def main():
    # Check if CSV exists
    if not os.path.exists(CSV_FILE):
        logger.critical(f"Error: {CSV_FILE} not found.")
        sys.exit(1)

    # Ensure output directories exist
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    if not os.path.exists(HTML_OUTPUT_DIR):
        os.makedirs(HTML_OUTPUT_DIR)

    # Initialize Driver
    driver = initialize_driver()
    if not driver:
        sys.exit(1)

    session_report = []

    try:
        # Read the CSV File
        logger.info(f"Reading targets from {CSV_FILE}...")
        
        expected_basenames = set()

        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            strip_bom_fieldnames(reader)

            for row in reader:
                url = row.get('Canonical-url', '').strip()
                udid = row.get('UDID', '').strip()
                main_title = row.get('Main-title', '').strip()

                # Validation
                if not url or not url.lower().startswith('http'):
                    logger.debug(f"Skipping row ID {udid}: Invalid URL '{url}'")
                    continue

                if not udid:
                    logger.error(
                        f"  [x] Skipping row with empty UDID (title={main_title!r}, url={url!r}). "
                        "Refusing to write file without a UDID prefix — check the CSV for missing/corrupt UDID values."
                    )
                    continue

                clean_title = sanitize_filename(main_title)
                filename = f"{udid} - {clean_title}.md"
                expected_basenames.add(os.path.splitext(filename)[0])

                # Scrape
                md_content, html_content, stats = fetch_and_convert(driver, url)
                
                # Add to Report
                report_entry = {
                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "UDID": udid,
                    "Filename": filename,
                    "URL": url,
                    "Status": stats["status"],
                    "Error_Message": stats["error"],
                    "HTML_Size_Bytes": stats["html_len"],
                    "MD_Size_Bytes": stats["md_len"],
                    "Title_Detected": stats["title_found"]
                }
                session_report.append(report_entry)

                if md_content and stats["status"] == "SUCCESS":
                    # 1. Save Markdown
                    md_filepath = os.path.join(OUTPUT_DIR, filename)
                    with open(md_filepath, 'w', encoding='utf-8') as f_md:
                        f_md.write(md_content)
                    
                    # 2. Save HTML
                    base_name = os.path.splitext(filename)[0]
                    html_filename = f"{base_name}-html.html"
                    html_filepath = os.path.join(HTML_OUTPUT_DIR, html_filename)
                    
                    with open(html_filepath, 'w', encoding='utf-8') as f_html:
                        f_html.write(html_content)

                    logger.info(f"  -> Saved: {filename}")
                else:
                    logger.warning(f"  -> Skipped: {filename} (Reason: {stats['error']})")

    except Exception as e:
        logger.critical(f"An unexpected error occurred during execution: {e}")
    finally:
        driver.quit()
        save_session_report(session_report)

        # Reconcile output directories: remove stale files left over from
        # earlier runs when UDIDs/titles change or CSV rows are removed.
        # Only runs if we built the expected set (i.e. CSV read succeeded).
        if 'expected_basenames' in locals() and expected_basenames:
            md_removed, html_removed = reconcile_output_dirs(
                expected_basenames, OUTPUT_DIR, HTML_OUTPUT_DIR, logger
            )
            if md_removed or html_removed:
                sep = "!" * 70
                logger.warning(sep)
                logger.warning(
                    f"!!! RECONCILIATION: removed {md_removed} stale .md and "
                    f"{html_removed} stale .html file(s) !!!"
                )
                logger.warning(sep)

        logger.info("--- Scrape Run Complete ---")

if __name__ == "__main__":
    main()
