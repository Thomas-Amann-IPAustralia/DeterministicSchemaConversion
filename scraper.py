import os
import re
import time
import json
import random
from selenium import webdriver
from selenium_stealth import stealth
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from dateutil import parser  # Optional: For parsing messy dates if needed, but strict string extraction is safer for now.

# --- Configuration ---
OUTPUT_DIR = 'outputs'
URLS_FILE = 'urls.txt'

def setup_directory():
    """Ensures the output directory exists."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_urls():
    """Reads URLs from the external text file."""
    if not os.path.exists(URLS_FILE):
        print(f"Error: {URLS_FILE} not found.")
        return []
    
    with open(URLS_FILE, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return urls

def slugify_filename(url):
    """Converts a URL into a safe filename."""
    clean_name = re.sub(r'^https?://(www\.)?', '', url)
    return re.sub(r'[^a-zA-Z0-9]+', '_', clean_name).strip('_') + ".txt"

def initialize_driver():
    """Initializes a stealth-configured WebDriver."""
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
    
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

def get_last_updated_date(soup):
    """
    Attempts to find the Last Modified Date using multiple strategies.
    Returns the date string or 'Not Found'.
    """
    
    # Strategy 1: Schema.org JSON-LD (The Gold Standard)
    # This looks for hidden JSON data used by search engines.
    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        try:
            if script.string:
                data = json.loads(script.string)
                # JSON-LD can be a dict or a list of dicts
                if isinstance(data, dict):
                    data = [data]
                
                for item in data:
                    # Check for standard schema date fields
                    if 'dateModified' in item:
                        return f"{item['dateModified']} (Source: JSON-LD)"
                    if 'datePublished' in item:
                        return f"{item['datePublished']} (Source: JSON-LD - Published)"
        except (json.JSONDecodeError, TypeError):
            continue

    # Strategy 2: HTML Meta Tags (The Silver Standard)
    # Common meta tags used by CMSs like WordPress, Drupal, etc.
    meta_targets = [
        {'property': 'article:modified_time'},
        {'property': 'og:updated_time'},
        {'name': 'date'},
        {'name': 'last-modified'},
        {'name': 'revised'},
        {'itemprop': 'dateModified'}
    ]

    for target in meta_targets:
        meta = soup.find('meta', target)
        if meta and meta.get('content'):
            return f"{meta.get('content')} (Source: Meta Tag - {list(target.values())[0]})"

    # Strategy 3: Heuristic Text Search (The Bronze Standard)
    # Looks for visible text on the page containing "Last updated"
    # Note: This is a basic regex and might be hit-or-miss depending on formatting.
    try:
        text_date = soup.find(string=re.compile(r'Last updated|Updated on|Amended on', re.IGNORECASE))
        if text_date:
            # Try to grab the parent text which likely contains the actual date
            return f"{text_date.parent.get_text(strip=True)} (Source: Visible Text)"
    except Exception:
        pass

    return "Not Detected"

def scrape_url(driver, url):
    print(f"Scraping: {url}")
    try:
        driver.get(url)
        
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(random.uniform(1, 2))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(1, 2))

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # Extract Date Metadata
        last_updated = get_last_updated_date(soup)
        
        # Extract Body Text
        text_content = soup.get_text(separator='\n', strip=True)
        
        return text_content, last_updated

    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None, None

def main():
    setup_directory()
    urls_to_scrape = load_urls()

    if not urls_to_scrape:
        print("No URLs found to scrape.")
        return

    driver = initialize_driver()
    
    try:
        for url in urls_to_scrape:
            content, last_updated = scrape_url(driver, url)
            
            if content:
                filename = slugify_filename(url)
                filepath = os.path.join(OUTPUT_DIR, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(f"Source URL: {url}\n")
                    f.write(f"Scrape Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Last Updated Meta: {last_updated}\n")
                    f.write("-" * 50 + "\n\n")
                    f.write(content)
                
                print(f"Saved to {filepath} (Updated: {last_updated})")
            else:
                print(f"Failed to retrieve content for {url}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
