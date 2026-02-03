import json
import os
import sys
import time
import random
import logging
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth
from markdownify import markdownify as md

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

def clean_markdown(text, url, title, overtitle):
    """Post-processing to match the 'Ideal' format."""
    
    # 1. Demote Headers (## -> ###)
    # The user wants H2s (##) to be treated as H3s (###) in the body
    text = re.sub(r'^## ', '### ', text, flags=re.MULTILINE)

    # 2. Fix Link Spacing
    # Solves: `[Link](url) .` -> `[Link](url).`
    text = re.sub(r'(\]\([^\)]+\))\s+\.', r'\1.', text)
    # Solves: `[Link](url) ,` -> `[Link](url),`
    text = re.sub(r'(\]\([^\)]+\))\s+,', r'\1,', text)

    # 3. Remove Footer Noise & Artifacts
    noise_patterns = [
        r'Was this information useful\?',
        r'Thumbs UpThumbs Down',
        r'\[Give feedback.*?\]\([^\)]+\)', # Removes the "Give feedback" button links
        r'\(Opens in a new tab/window\)',
        r'Opens in a new tab/window'
    ]
    for pattern in noise_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)

    # 4. Italicize Disclaimer
    # Finds the standard disclaimer text and wraps it in *...*
    disclaimer_start = "This IP First Response website has been designed"
    if disclaimer_start in text:
        if f"*{disclaimer_start}" not in text: # Prevent double italicizing
            pattern = r'(' + re.escape(disclaimer_start) + r'.*?)(\n\n|$)'
            text = re.sub(pattern, r'*\1*\2', text, count=1, flags=re.DOTALL)

    # 5. Enforce Blank Lines Before Headers
    # Ensures there is always a double newline before a ### header
    text = re.sub(r'([^\n])\n(### )', r'\1\n\n\2', text)
    
    # 6. Construct Top Metadata Block
    # Adds PageURL, Overtitle (##), and Title (#)
    header_block = f'PageURL: "[{url}]({url})"\n\n'
    
    if overtitle:
        header_block += f"## {overtitle}\n\n"
    
    if title:
        header_block += f"# {title}\n\n"

    # Combine
    final_text = header_block + text.strip()
    
    # Final cleanup of excessive newlines created by removals
    final_text = re.sub(r'\n{3,}', '\n\n', final_text)
    
    return final_text

def fetch_and_convert(driver, url):
    """Scrapes URL via Selenium and converts to Markdown via Markdownify."""
    try:
        logger.info(f"Processing: {url}")
        driver.get(url)
        
        # Wait for body
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        
        # Lazy load scroll
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(random.uniform(2.0, 4.0)) 

        # --- STEP 1: Metadata Extraction ---
        page_title = ""
        page_overtitle = ""
        
        try:
            page_title = driver.find_element(By.TAG_NAME, "h1").text.strip()
        except:
            pass

        try:
            # UPDATED: Specifically target the class found by the user
            overtitle_elem = driver.find_element(By.CLASS_NAME, "option-detail-page-tag")
            page_overtitle = overtitle_elem.text.strip()
        except:
            # Fallback if the specific tag isn't found (optional)
            pass

        # --- STEP 2: Main Content Extraction ---
        content_html = ""
        try:
            # Target <main> to exclude nav/footer
            try:
                main_element = driver.find_element(By.TAG_NAME, "main")
                content_html = main_element.get_attribute('innerHTML')
            except:
                # Fallback for GovCMS structure
                main_element = driver.find_element(By.CLASS_NAME, "region-content")
                content_html = main_element.get_attribute('innerHTML')
        except Exception as e:
            logger.warning(f"  [!] Could not isolate main content, using body. ({e})")
            content_html = driver.find_element(By.TAG_NAME, "body").get_attribute('innerHTML')

        # --- STEP 3: Convert ---
        # heading_style="ATX" gives us ## style headers
        markdown_text = md(
            content_html, 
            heading_style="ATX",
            strip=['script', 'style', 'iframe', 'noscript', 'button'],
            newline_style="BACKSLASH"
        )

        if not markdown_text:
            logger.warning(f"  [!] Markdownify produced empty text for {url}")
            return None

        # --- STEP 4: Clean and Polish ---
        final_markdown = clean_markdown(markdown_text, url, page_title, page_overtitle)
        
        return final_markdown

    except Exception as e:
        logger.error(f"  [x] Error scraping {url}: {e}")
        return None

def main():
    if not os.path.exists(SOURCES_FILE):
        logger.critical(f"Error: {SOURCES_FILE} not found.")
        sys.exit(1)

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
