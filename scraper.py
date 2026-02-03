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
        # Read lines, strip whitespace, and ignore empty lines or comments
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return urls

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

def scrape_url(driver, url):
    print(f"Scraping: {url}")
    try:
        driver.get(url)
        
        # Wait for body presence
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, 'body'))
        )

        # Human-like scrolling
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(random.uniform(1, 2))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(1, 2))

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # Extract all text, including headers and footers
        text_content = soup.get_text(separator='\n', strip=True)
        
        return text_content

    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None

def main():
    setup_directory()
    urls_to_scrape = load_urls()

    if not urls_to_scrape:
        print("No URLs found to scrape.")
        return

    driver = initialize_driver()
    
    try:
        for url in urls_to_scrape:
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
