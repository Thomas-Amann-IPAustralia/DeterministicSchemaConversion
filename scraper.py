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
HTML_OUTPUT_DIR = 'IPFR-Webpages-html'  # <--- NEW CONFIG

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

def fetch_and_convert(driver, url):
    """Scrapes URL via Selenium and returns both Markdown and raw HTML."""
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

        # --- STEP 3: Convert ---
        markdown_text = md(
            content_html, 
            heading_style="ATX",
            strip=['script', 'style', 'iframe', 'noscript', 'button'],
            newline_style="BACKSLASH"
        )

        if not markdown_text:
            logger.warning(f"  [!] Markdownify produced empty text for {url}")
            return None, None # Return Tuple

        # --- STEP 4: Clean and Polish ---
        final_markdown = clean_markdown(markdown_text, url, page_title, page_overtitle)
        
        # Return both the processed markdown AND the raw content HTML
        return final_markdown, content_html

    except Exception as e:
        logger.error(f"  [x] Error scraping {url}: {e}")
        return None, None

def main():
    if not os.path.exists(SOURCES_FILE):
        logger.critical(f"Error: {SOURCES_FILE} not found.")
        sys.exit(1)

    # Ensure both output directories exist
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    
    if not os.path.exists(HTML_OUTPUT_DIR):
        os.makedirs(HTML_OUTPUT_DIR)

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

        # Unpack the tuple returned by fetch_and_convert
        md_content, html_content = fetch_and_convert(driver, url)
        
        if md_content:
            # 1. Save Markdown
            md_filepath = os.path.join(OUTPUT_DIR, filename)
            with open(md_filepath, 'w', encoding='utf-8') as f:
                f.write(md_content)
            
            # 2. Save HTML
            # Create base name by stripping .md extension
            base_name = os.path.splitext(filename)[0]
            html_filename = f"{base_name}-html.html"
            html_filepath = os.path.join(HTML_OUTPUT_DIR, html_filename)
            
            with open(html_filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)

            logger.info(f"  -> Saved MD to {md_filepath}")
            logger.info(f"  -> Saved HTML to {html_filepath}")
        else:
            logger.warning(f"  -> Skipped saving {filename} (No content)")

    driver.quit()
    logger.info("--- Scrape Run Complete ---")

if __name__ == "__main__":
    main()
