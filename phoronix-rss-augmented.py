from bs4 import BeautifulSoup
import hashlib
import math
import os
import pathlib
import requests
import time
from lxml.etree import CDATA, parse

# Source RSS URL
SOURCE_RSS_URL = 'https://www.phoronix.com/rss.php'

# Define file paths
PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()

# Define cache properties
CACHE_ROOT = os.path.join(PROJECT_ROOT, "cache")
CACHE_SOURCE_RSS_FILE_PATH = os.path.join(CACHE_ROOT, 'source_rss.xml')
CACHE_SOURCE_TTL = 55 # minutes
CACHE_ITEM_TTL = 24 # hours

# Define output properties
OUTPUT_ROOT = os.path.join(PROJECT_ROOT, "output")
OUTPUT_RSS_FILE_PATH = os.path.join(OUTPUT_ROOT, 'phoronix-rss-augmented.xml')

def fetch_and_cache(url, cache_path):
    print(f"Fetching fresh copy of {url}")
    text = requests.get(url).text
    with open(cache_path, "w", encoding='utf-8') as f:
        f.write(text)
    return text

# Check for Source RSS cache, [re]download if necessary
if not os.path.isfile(CACHE_SOURCE_RSS_FILE_PATH):
    print(f"Source RSS cache not found")
    fetch_and_cache(SOURCE_RSS_URL, CACHE_SOURCE_RSS_FILE_PATH)
else:
    current_timestamp = time.time()
    cache_source_rss_modification_timestamp = os.path.getmtime(CACHE_SOURCE_RSS_FILE_PATH)
    cache_source_rss_age_seconds = current_timestamp - cache_source_rss_modification_timestamp
    cache_source_rss_age_minutes = math.floor(cache_source_rss_age_seconds / 60)
    print(f"Source RSS cache is {cache_source_rss_age_minutes} minutes old")

    if cache_source_rss_age_minutes < CACHE_SOURCE_TTL:
        print("Loading cached source RSS...")
    else:
        fetch_and_cache(SOURCE_RSS_URL, CACHE_SOURCE_RSS_FILE_PATH)

# Parse Source RSS
source_rss_tree = parse(CACHE_SOURCE_RSS_FILE_PATH)

for item in source_rss_tree.iter('item'):
    item_url = item.find('link').text
    item_url_hash = hashlib.md5(item_url.encode('utf-8')).hexdigest()
    item_cache_file_path = CACHE_SOURCE_RSS_FILE_PATH = os.path.join(CACHE_ROOT, f'{item_url_hash}.html')
    print(f"URL: {item_url.ljust(70)} cache path: {item_cache_file_path}")

    # Check for item HTML cache, [re]download if necessary
    soup = None
    if not os.path.isfile(item_cache_file_path):
        print(f"{item_url} cache not found")
        html_contents = fetch_and_cache(item_url, item_cache_file_path)
        soup = BeautifulSoup(html_contents, 'html.parser')
    else:
        current_timestamp = time.time()
        cache_item_modification_timestamp = os.path.getmtime(item_cache_file_path)
        cache_item_age_seconds = current_timestamp - cache_item_modification_timestamp
        cache_item_age_hours = math.floor(cache_item_age_seconds / 60 / 60)
        print(f"{item_url} cache is {cache_item_age_hours} hours old")

        if cache_item_age_hours < CACHE_ITEM_TTL:
            print(f"Loading cached {item_url}...")
            with open(item_cache_file_path, encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
        else:
            html_contents = fetch_and_cache(item_url, item_cache_file_path)
            soup = BeautifulSoup(html_contents, 'html.parser')

    # Extract article
    article_html = soup.find('article')

    # Delete JavaScript
    for script_tag in article_html.findAll('script'):
        script_tag.extract()

    # Delete sharebar
    for sharebar in article_html.findAll('div', {"id": "sharebar"}):
        sharebar.extract()

    # Multipage articles contain page selector element
    # that has invalid (for RSS) onchange attribute.
    # Delete it for now to pass validation
    # but maybe later i could implement 
    # fetching the entire content of multipage articles.
    for sharebar in article_html.findAll('select', {"id": "phx_article_page_selector"}):
        sharebar.extract()

    # Replace <description> tag value with full content of the article
    description = item.find('description')
    description.text = CDATA(str(article_html))

# Output augmented RSS file
source_rss_tree.write(OUTPUT_RSS_FILE_PATH, encoding = 'utf-8', xml_declaration = True)
