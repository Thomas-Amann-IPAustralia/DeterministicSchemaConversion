import csv
import os
import sys
import time
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

# --- FORCE UNBUFFERED OUTPUT ---
# This ensures logs appear immediately in GitHub Actions
sys.stdout.reconfigure(line_buffering=True)

# --- Configuration ---
CSV_FILE = 'metatable-Content.csv'
OUTPUT_DIR = 'IPFR-Webpages'
HTML_OUTPUT_DIR = 'IPFR-Webpages-html'
REPORTS_DIR = os.path.join('DeterministicSchemaConversion', 'reports', 'scrape_reports')

# --- Helper: Raw Print ---
def log(msg):
    """Bypasses logging module to ensure output in CI/CD."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def initialize_driver(ethical_mode=True):
    mode_name = "ETHICAL" if ethical_mode else "STEALTH"
    log(f"-> Initializing Driver ({mode_name})...")
    
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    
    base_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    
    if ethical_mode:
        contact_info = " (compatible; IPFR-Bot/1.0; +mailto:your-email@example.com)"
        chrome_options.add_argument(f'user-agent={base_ua}{contact_info}')
    else:
        chrome_options.add_argument(f'user-agent={base_ua}')
    
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Set a hard timeout so it can't hang forever
        driver.set_page_load_timeout(30)

        if ethical_mode:
            try:
                driver.execute_cdp_cmd('Network.enable', {})
                driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {
                    'headers': {'X-Bot-Name': 'IPFR-Content-Aggregator'}
                })
            except Exception as e:
                log(f"Warning: CDP Headers failed: {e}")

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
        log(f"[X] Driver Init Failed: {e}")
        return None

# ... (Keep normalize_text, clean_markdown, sanitize_filename as is) ...
def normalize_text(text):
    if not text: return ""
    replacements = {'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '\u2013': '-', '\u2014': '--', '…': '...'}
    for k, v in replacements.items(): text = text.replace(k, v)
    return text

def clean_markdown(text, url, title, overtitle):
    text = normalize_text(text)
    header_block = f'PageURL: "[{url}]({url})"\n\n'
    return header_block + text[:500] # Truncated for brevity in this example

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", str(name or "Untitled")).strip()

def fetch_and_convert(driver, url):
    # Minimal version for debugging
    telemetry = {"status": "FAILURE", "error": "", "html_len": 0, "md_len": 0, "title_found": False}
    try:
        log(f"   Navigating to: {url}")
        driver.get(url)
        time.sleep(2)
        telemetry["status"] = "SUCCESS"
        return "Dummy Content", "Dummy HTML", telemetry
    except Exception as e:
        telemetry["error"] = str(e)
        return None, None, telemetry

def main():
    log("--- SCRIPT STARTED ---")

    if not os.path.exists(CSV_FILE):
        log(f"CRITICAL: {CSV_FILE} does not exist!")
        sys.exit(1)

    # --- DIAGNOSTIC: CHECK CSV CONTENT ---
    log(f"Inspecting {CSV_FILE}...")
    with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()
        log(f"File Line Count: {len(lines)}")
        if len(lines) > 0:
            log(f"Header Row: {lines[0].strip()}")
        else:
            log("CRITICAL: CSV FILE IS EMPTY.")
            sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(HTML_OUTPUT_DIR, exist_ok=True)

    main_driver = initialize_driver(ethical_mode=True)
    if not main_driver:
        sys.exit(1)

    try:
        log("Opening CSV Reader...")
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            # Sanitize headers (remove whitespace)
            if reader.fieldnames:
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
            log(f"Parsed Columns: {reader.fieldnames}")

            row_count = 0
            for row in reader:
                row_count += 1
                url = row.get('Canonical-url', '').strip()
                udid = row.get('UDID', '').strip()
                
                log(f"Processing Row {row_count}: {udid} | {url}")
                
                if not url:
                    continue

                # Test scrape
                md_c, html_c, stats = fetch_and_convert(main_driver, url)
                
                if stats["status"] != "SUCCESS":
                    log("   [!] Ethical Failed. Triggering Fallback...")
                    # Fallback logic here...
                else:
                    log("   [+] Success.")

            log(f"Total Rows Processed: {row_count}")
            if row_count == 0:
                log("WARNING: Loop finished with 0 rows processed.")

    except Exception as e:
        log(f"Global Crash: {e}")
    finally:
        main_driver.quit()
        log("--- SCRIPT FINISHED ---")

if __name__ == "__main__":
    main()
