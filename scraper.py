import os
import re
import time
import random
from selenium import webdriver
from selenium_stealth import stealth
from bs4 import BeautifulSoup
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

# --- Configuration ---
OUTPUT_DIR = 'output'
URLS_TO_SCRAPE = [
    "https://ipfirstresponse.ipaustralia.gov.au/options/receiving-letter-demand",
    "https://www.tomamann.com/about"
]

def setup_directory():
    """Ensures the output directory exists."""
    if os.path.exists(OUTPUT_DIR):
        # Optional: Clear directory before run
        # shutil.rmtree(OUTPUT_DIR)
        pass
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def slugify_filename(url):
    """Converts a URL into a safe filename."""
    # Remove http/https and www
    clean_name = re.sub(r'^https?://(www\.)?', '', url)
    # Replace non-alphanumeric characters with underscores
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
    
    # Use webdriver-manager to handle the chromedriver binary
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Apply stealth measures
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )
    return driver

def scrape_url(driver, url):
    print(f"Scraping: {url}")
    try:
        driver.get(url)
        
        # Wait for body presence
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, 'body'))
        )

        # Human-like scrolling (helps trigger lazy loading)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(random.uniform(1, 2))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(1, 2))

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # NOTE: Unlike the original script, we do NOT decompose headers/footers here.
        # We extract all text visible on the page.
        text_content = soup.get_text(separator='\n', strip=True)
        
        return text_content

    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None

def main():
    setup_directory()
    driver = initialize_driver()
    
    try:
        for url in URLS_TO_SCRAPE:
            content = scrape_url(driver, url)
            
            if content:
                filename = slugify_filename(url)
                filepath = os.path.join(OUTPUT_DIR, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(f"Source URL: {url}\n")
                    f.write("-" * 50 + "\n\n")
                    f.write(content)
                
                print(f"Saved to {filepath}")
            else:
                print(f"Failed to retrieve content for {url}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
