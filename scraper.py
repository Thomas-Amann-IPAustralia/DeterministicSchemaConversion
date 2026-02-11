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

def initialize_driver(ethical_mode=True):
    """
    Sets up a Chrome driver. 
    If ethical_mode=True, adds contact info headers/UA.
    If ethical_mode=False, runs in maximum stealth.
    """
    mode_name = "ETHICAL" if ethical_mode else "STEALTH"
    logger.info(f"  -> Initializing Selenium Driver ({mode_name} Mode)...")
    
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')

    # 1. User-Agent Configuration
    base_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    
    if ethical_mode:
        # Append Contact Info for "Polite" Mode
        contact_info = " (compatible; IPFR-Bot/1.0; +mailto:your-email@example.com)"
        chrome_options.add_argument(f'user-agent={base_ua}{contact_info}')
    else:
        # Use Standard User-Agent for "Stealth" Mode
        chrome_options.add_argument(f'user-agent={base_ua}')
    
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        # 2. Header Injection (Only in Ethical Mode)
        if ethical_mode:
            driver.execute_cdp_cmd('Network.enable', {})
            driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {
                'headers': {
                    'X-Scraper-Contact': 'mailto:your-email@example.com',
                    'X-Bot-Name': 'IPFR-Content-Aggregator'
                }
            })

        # Apply Stealth settings to both (essential for avoiding bot detection signatures)
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
        logger.error(f"  [x] Failed to initialize {mode_name} WebDriver: {e}")
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

    # Initialize Main Driver (Ethical Mode by default)
    main_driver = initialize_driver(ethical_mode=True)
    if not main_driver:
        sys.exit(1)

    session_report = []

    try:
        # Read the CSV File
        logger.info(f"Reading targets from {CSV_FILE}...")
        
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            if reader.fieldnames:
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
            
            # DEBUG: Print what headers Python actually sees
            logger.info(f"Detected CSV Headers: {reader.fieldnames}")

            row_count = 0
            for row in reader:
                row_count += 1
                # Robust extraction: defaults to empty string if key is missing
                url = row.get('Canonical-url', '').strip()
                udid = row.get('UDID', '').strip()
                main_title = row.get('Main-title', '').strip()

                # DEBUG: Alert if URL is missing so you know WHY it skipped
                if not url:
                    logger.warning(f"  [?] Row {row_count} (UDID: {udid}) skipped: 'Canonical-url' column is empty.")
                    continue

                if not url.lower().startswith('http'):
                    logger.warning(f"  [?] Row {row_count} skipped: Invalid URL format '{url}'")
                    continue
                
                clean_title = sanitize_filename(main_title)
                filename = f"{udid} - {clean_title}.md"

                # --- ATTEMPT 1: Ethical Scrape ---
                md_content, html_content, stats = fetch_and_convert(main_driver, url)

                # --- FALLBACK LOGIC ---
                if stats["status"] != "SUCCESS":
                    logger.warning(f"  [!] Ethical scrape failed ({stats['error']}). Attempting Stealth Fallback...")
                    
                    # Spin up a temporary Stealth Driver
                    fallback_driver = initialize_driver(ethical_mode=False)
                    
                    if fallback_driver:
                        # ATTEMPT 2: Stealth Scrape
                        md_content, html_content, stats = fetch_and_convert(fallback_driver, url)
                        
                        # Update status if successful so we know it worked via fallback
                        if stats["status"] == "SUCCESS":
                            stats["status"] = "SUCCESS_VIA_FALLBACK"
                        else:
                            stats["status"] = "FAILED_BOTH"
                        
                        # Close the stealth driver immediately
                        fallback_driver.quit()
                    else:
                        logger.error("  [x] Could not initialize Stealth Driver.")
                
                # --- SAVE & REPORT ---
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

                if md_content and "SUCCESS" in stats["status"]:
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

                    logger.info(f"  -> Saved: {filename} (Status: {stats['status']})")
                else:
                    logger.warning(f"  -> Skipped: {filename} (Reason: {stats['error']})")

    except Exception as e:
        logger.critical(f"An unexpected error occurred during execution: {e}")
    finally:
        if main_driver:
            main_driver.quit()
        save_session_report(session_report)
        logger.info("--- Scrape Run Complete ---")
