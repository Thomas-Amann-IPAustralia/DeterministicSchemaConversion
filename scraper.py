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

def clean_markdown(text, url):
    """Post-processing to match the 'Ideal' format."""
    
    # 1. Remove excessive newlines (more than 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 2. Fix the Disclaimer formatting
    # The ideal format wants the standard disclaimer text to be italicized.
    # We look for the specific starting phrase and wrap the paragraph in asterisks.
    disclaimer_start = "This IP First Response website has been designed"
    if disclaimer_start in text:
        # Regex to find the disclaimer paragraph and italicize it if not already
        pattern = r'(' + re.escape(disclaimer_start) + r'.*?)(?=\n\n|\n$)'
        # The re.DOTALL flag ensures . matches newlines inside the paragraph if needed
        text = re.sub(pattern, r'*\1*', text, count=1, flags=re.DOTALL)

    # 3. Clean up link spacing (run-on links)
    # Solves: `(ASBFEO)](https://...)provides` -> `...](...) provides`
    text = re.sub(r'(\]\([^\)]+\))([a-zA-Z0-9])', r'\1 \2', text)
    
    # 4. Remove empty links or breadcrumb artifacts often found in scrapes
    text = re.sub(r'\[\s*\]\([^\)]+\)', '', text)

    # 5. Append URL Source for reference (Optional, but good practice)
    # text += f"\n\n\n*Source: {url}*"

    return text.strip()

def fetch_and_convert(driver, url):
    """Scrapes URL via Selenium and converts to Markdown via Markdownify."""
    try:
        logger.info(f"Processing: {url}")
        driver.get(url)
        
        # Wait for body to ensure page load
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        
        # Lazy load scroll
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(random.uniform(2.0, 4.0)) 

        # --- STEP 1: Targeted Extraction ---
        # Instead of grabbing the whole page (which includes nav/footer), 
        # we target the main content container. 
        # GovCMS/Drupal sites usually use <main>, <div id="content">, or <article>.
        content_html = ""
        try:
            # Try finding the specific main content wrapper to exclude site navigation
            # Priority: <main> tag -> class="region-content" -> <body>
            try:
                main_element = driver.find_element(By.TAG_NAME, "main")
                content_html = main_element.get_attribute('innerHTML')
            except:
                try:
                    # Fallback for standard Drupal content regions
                    main_element = driver.find_element(By.CLASS_NAME, "region-content")
                    content_html = main_element.get_attribute('innerHTML')
                except:
                    # Last resort fallback
                    logger.warning("  [!] Could not find <main> tag, using <body>")
                    content_html = driver.find_element(By.TAG_NAME, "body").get_attribute('innerHTML')

        except Exception as e:
            logger.error(f"  [x] Error extracting HTML content: {e}")
            return None

        # --- STEP 2: Convert with Markdownify ---
        # heading_style="ATX" ensures we get ### Header instead of underlined headers
        markdown_text = md(
            content_html, 
            heading_style="ATX",
            strip=['script', 'style', 'iframe', 'noscript'], # Remove code noise
            newline_style="BACKSLASH" # Helps prevent run-on lines
        )

        if not markdown_text:
            logger.warning(f"  [!] Markdownify produced empty text for {url}")
            return None

        # --- STEP 3: Clean and Polish ---
        final_markdown = clean_markdown(markdown_text, url)
        
        return final_markdown

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
