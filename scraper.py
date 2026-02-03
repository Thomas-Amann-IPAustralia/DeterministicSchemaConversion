import json
import os
import sys
import time
import random
import logging
import re
import trafilatura
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# --- Configuration ---
SOURCES_FILE = 'sources.json'
OUTPUT_DIR = 'IPFR-Webpages'

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

def fetch_and_convert(driver, url):
    """Scrapes URL via Selenium and converts to Markdown via Trafilatura."""
    try:
        logger.info(f"Processing: {url}")
        driver.get(url)
        
        # Wait for body and scroll to trigger lazy loading
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(random.uniform(2.0, 4.0)) # Polite wait

        # --- FIX 1: Manual Header Extraction ---
        # Trafilatura often views the top banner/H1 as "navigation boilerplate" and removes it.
        # We manually grab the H1 and the lead paragraph to ensure they are present.
        page_title = ""
        page_subtitle = ""
        try:
            h1_elem = driver.find_element(By.TAG_NAME, "h1")
            page_title = h1_elem.text.strip()
            
            # Attempt to find the immediate sub-text (often the next paragraph sibling)
            # This XPath looks for the first <p> tag immediately following the <h1>
            intro_elem = driver.find_element(By.XPATH, "//h1/following-sibling::p[1]")
            page_subtitle = intro_elem.text.strip()
        except Exception:
            # Proceed even if specific elements aren't found
            pass

        html_content = driver.page_source
        
        # Check for common block signatures
        block_sigs = ["access denied", "verify you are human", "security check"]
        if any(sig in html_content.lower() for sig in block_sigs):
            logger.warning(f"  [!] Possible block detected for {url}")
            return None

        # --- FIX 2: Enhanced Extraction Settings ---
        # Added `include_formatting=True`. This preserves bolding and, crucially,
        # helps maintain vertical lists (resolving the "Jumbled List" issue).
        markdown_text = trafilatura.extract(
            html_content,
            output_format='markdown',
            include_tables=True,
            include_links=True,
            include_images=True,
            include_formatting=True 
        )

        if not markdown_text:
            logger.warning(f"  [!] Trafilatura could not extract text from {url}")
            return None

        # --- FIX 3: Post-Processing Cleanups ---
        
        # 3a. Prepend Title if missing
        # We check if the manually extracted title appears in the first 500 characters.
        # If not, we prepend it to the top of the file.
        if page_title and page_title not in markdown_text[:500]:
            header_block = f"# {page_title}\n"
            if page_subtitle:
                header_block += f"\n{page_subtitle}\n"
            markdown_text = f"{header_block}\n{markdown_text}"

        # 3b. Fix Run-on Link Spacing
        # Solves: `(ASBFEO)](https://...)provides` -> `...](...) provides`
        # Regex finds: A closing markdown link `](...)` immediately followed by a letter/number
        markdown_text = re.sub(r'(\]\([^\)]+\))([a-zA-Z0-9])', r'\1 \2', markdown_text)

        # 3c. Cleanup dangling bold markers (from original script)
        markdown_text = re.sub(r'(\*\*[^\n]+)\n\s*(\*\*)', r'\1\2', markdown_text)
        
        return markdown_text

    except Exception as e:
        logger.error(f"  [x] Error scraping {url}: {e}")
        return None

def main():
    if not os.path.exists(SOURCES_FILE):
        logger.critical(f"Error: {SOURCES_FILE} not found.")
        sys.exit(1)

    # Ensure output directory exists
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    with open(SOURCES_FILE, 'r') as f:
        sources = json.load(f)

    driver = initialize_driver()
    if not driver:
        sys.exit(1)

    for item in sources:
        url = item.get('url')
        filename = item.get('filename', 'output.md')
        
        # Enforce .md extension
        if not filename.endswith('.md'):
            filename += '.md'

        content = fetch_and_convert(driver, url)
        
        if content:
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"  -> Saved to {filepath}")
        else:
            logger.warning(f"  -> Skipped saving {filename} (No content)")

    driver.quit()
    logger.info("--- Scrape Run Complete ---")

if __name__ == "__main__":
    main()
