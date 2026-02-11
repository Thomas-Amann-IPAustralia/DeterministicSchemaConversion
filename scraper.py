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

# --- FIX 1: FORCE UNBUFFERED OUTPUT ---
# This ensures logs appear immediately in GitHub Actions
sys.stdout.reconfigure(line_buffering=True)

# --- Configuration ---
CSV_FILE = 'metatable-Content.csv'
OUTPUT_DIR = 'IPFR-Webpages'
HTML_OUTPUT_DIR = 'IPFR-Webpages-html'
REPORTS_DIR = os.path.join('DeterministicSchemaConversion', 'reports', 'scrape_reports')

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)] # Force stream to stdout
)
logger = logging.getLogger("Scraper")

def initialize_driver(ethical_mode=True):
    """
    Sets up the Driver. 
    If ethical_mode=True: Identifies as a Bot.
    If ethical_mode=False: Falls back to Stealth (Original Logic).
    """
    mode_name = "ETHICAL" if ethical_mode else "STEALTH"
    logger.info(f"  -> Initializing Selenium Driver ({mode_name} Mode)...")
    
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')

    base_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    
    if ethical_mode:
        # Polite User-Agent
        contact_info = " (compatible; IPFR-Bot/1.0; +mailto:your-email@example.com)"
        chrome_options.add_argument(f'user-agent={base_ua}{contact_info}')
    else:
        # Stealth User-Agent (Original)
        chrome_options.add_argument(f'user-agent={base_ua}')
    
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        # Timeout to prevent hanging
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(30)

        # Inject Headers (Only in Ethical Mode)
        if ethical_mode:
            try:
                driver.execute_cdp_cmd('Network.enable', {})
                driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {
                    'headers': {'X-Bot-Name': 'IPFR-Content-Aggregator'}
                })
            except Exception:
                pass # Ignore if CDP fails

        # Apply Stealth (Essential for both modes to pass WAFs)
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

# --- Original Helper Functions (Unchanged) ---
def normalize_text(text):
    if not text: return ""
    replacements = {'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '\u2013': '-', '\u2014': '--', '…': '...'}
    for k, v in replacements.items(): text = text.replace(k, v)
    return text

def clean_markdown(text, url, title, overtitle):
    text = normalize_text(text)
    text = re.sub(r'^## ', '### ', text, flags=re.MULTILINE)
    text = re.sub(r'(\]\([^\)]+\))\s+\.', r'\1.', text)
    text = re.sub(r'(\]\([^\)]+\))\s+,', r'\1,', text)
    noise_patterns = [r'Was this information useful\?', r'Thumbs UpThumbs Down', r'\[Give feedback.*?\]\([^\)]+\)', r'\(Opens in a new tab/window\)', r'Opens in a new tab/window']
    for pattern in noise_patterns: text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
    
    disclaimer_start = "This IP First Response website has been designed"
    if disclaimer_start in text and f"*{disclaimer_start}" not in text:
        pattern = r'(' + re.escape(disclaimer_start) + r'.*?)(\n\n|$)'
        text = re.sub(pattern, r'*\1*\2', text, count=1, flags=re.DOTALL)

    text = re.sub(r'([^\n])\n(### )', r'\1\n\n\2', text)
    header_block = f'PageURL: "[{url}]({url})"\n\n'
    if overtitle: header_block += f"## {overtitle}\n\n"
    if title: header_block += f"# {title}\n\n"
    return re.sub(r'\n{3,}', '\n\n', header_block + text.strip())

def sanitize_filename(name):
    if not name: return "Untitled"
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def save_session_report(report_data):
    if not os.path.exists(REPORTS_DIR): os.makedirs(REPORTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORTS_DIR, f"scrape_report_{timestamp}.csv")
    fieldnames = ["Timestamp", "UDID", "Filename", "URL", "Status", "Error_Message", "HTML_Size_Bytes", "MD_Size_Bytes", "Title_Detected"]
    try:
        with open(report_path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_data)
        logger.info(f"--- Session Report Saved: {report_path} ---")
    except Exception as e:
        logger.error(f"Failed to save session report: {e}")

def fetch_and_convert(driver, url):
    telemetry = {"status": "FAILURE", "error": "", "html_len": 0, "md_len": 0, "title_found": False}
    try:
        logger.info(f"Processing: {url}")
        driver.get(url)
        
        # Wait for body (Basic check)
        try:
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        except:
            pass # Try scraping anyway
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(random.uniform(2.0, 4.0)) 

        # Metadata
        page_title = ""
        page_overtitle = ""
        try:
            page_title = driver.find_element(By.TAG_NAME, "h1").text.strip()
            if page_title: telemetry["title_found"] = True
        except: pass
        try:
            page_overtitle = driver.find_element(By.CLASS_NAME, "option-detail-page-tag").text.strip()
        except: pass

        # --- FIX 3: IMPROVED CONTENT SELECTOR ---
        # Prioritize finding the cleanest content block
        content_html = ""
        selectors = [
            (By.TAG_NAME, "main"),
            (By.CLASS_NAME, "region-content"),
            (By.ID, "content"),
            (By.CLASS_NAME, "layout-content")
        ]
        
        found = False
        for by_method, selector in selectors:
            try:
                elem = driver.find_element(by_method, selector)
                content_html = elem.get_attribute('innerHTML')
                if content_html and len(content_html) > 100:
                    found = True
                    break
            except: continue
            
        if not found:
            logger.warning("  [!] Fallback to body content (expect noise).")
            content_html = driver.find_element(By.TAG_NAME, "body").get_attribute('innerHTML')

        telemetry["html_len"] = len(content_html)

        # Convert
        markdown_text = md(content_html, heading_style="ATX", strip=['script', 'style', 'iframe', 'noscript', 'button'], newline_style="BACKSLASH")
        if not markdown_text:
            telemetry["error"] = "Markdownify empty"
            return None, None, telemetry

        final_markdown = clean_markdown(markdown_text, url, page_title, page_overtitle)
        telemetry["md_len"] = len(final_markdown)
        telemetry["status"] = "SUCCESS"
        return final_markdown, content_html, telemetry

    except Exception as e:
        telemetry["error"] = str(e).split('\n')[0]
        logger.error(f"  [x] Error scraping: {telemetry['error']}")
        return None, None, telemetry

def main():
    if not os.path.exists(CSV_FILE):
        logger.critical(f"Error: {CSV_FILE} not found.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(HTML_OUTPUT_DIR, exist_ok=True)

    # Start with Ethical Driver
    main_driver = initialize_driver(ethical_mode=True)
    if not main_driver: sys.exit(1)

    session_report = []

    try:
        logger.info(f"Reading targets from {CSV_FILE}...")
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            # FIX: Sanitize headers to prevent skips
            if reader.fieldnames: reader.fieldnames = [name.strip() for name in reader.fieldnames]

            for row in reader:
                url = row.get('Canonical-url', '').strip()
                udid = row.get('UDID', '').strip()
                main_title = row.get('Main-title', '').strip()

                if not url or not url.lower().startswith('http'): continue
                
                filename = f"{udid} - {sanitize_filename(main_title)}.md"

                # --- FIX 2: FALLBACK LOGIC ---
                # Attempt 1: Ethical
                md_content, html_content, stats = fetch_and_convert(main_driver, url)

                # Attempt 2: Stealth Fallback (If Ethical failed)
                if stats["status"] != "SUCCESS":
                    logger.warning(f"  [!] Ethical scrape failed. Retrying in Stealth Mode...")
                    fallback_driver = initialize_driver(ethical_mode=False)
                    if fallback_driver:
                        md_content, html_content, stats = fetch_and_convert(fallback_driver, url)
                        if stats["status"] == "SUCCESS":
                            stats["status"] = "SUCCESS_VIA_FALLBACK"
                        fallback_driver.quit()

                # Report & Save
                session_report.append({
                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "UDID": udid, "Filename": filename, "URL": url,
                    "Status": stats["status"], "Error_Message": stats["error"],
                    "HTML_Size_Bytes": stats["html_len"], "MD_Size_Bytes": stats["md_len"],
                    "Title_Detected": stats["title_found"]
                })

                if md_content and "SUCCESS" in stats["status"]:
                    with open(os.path.join(OUTPUT_DIR, filename), 'w', encoding='utf-8') as f: f.write(md_content)
                    html_fname = f"{os.path.splitext(filename)[0]}-html.html"
                    with open(os.path.join(HTML_OUTPUT_DIR, html_fname), 'w', encoding='utf-8') as f: f.write(html_content)
                    logger.info(f"  -> Saved: {filename}")
                else:
                    logger.warning(f"  -> Skipped: {filename}")

    except Exception as e:
        logger.critical(f"Execution Error: {e}")
    finally:
        if main_driver: main_driver.quit()
        save_session_report(session_report)
        logger.info("--- Scrape Run Complete ---")

if __name__ == "__main__":
    main()
