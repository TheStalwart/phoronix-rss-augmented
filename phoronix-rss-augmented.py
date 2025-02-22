import sys
from bs4 import BeautifulSoup
import hashlib
import math
import os
import pathlib
import requests
import time
from lxml.etree import CDATA, parse
import sentry_sdk

# Source RSS URL
WEBSITE_ROOT_URL = 'https://www.phoronix.com'
SOURCE_RSS_URL = f"{WEBSITE_ROOT_URL}/rss.php"

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
    response = requests.get(url)
    if not response.ok:
        print(f"\nFailed to request content of {item_url}")
        print(f"\nResponse:")
        print(response)
        print(f"\nResponse.text:")
        print(response.text)
        sys.exit(1)
    with open(cache_path, "w", encoding='utf-8') as f:
        f.write(response.text)
    return response.text

# Init Sentry before doing anything that might raise exception
try:
    sentry_sdk.init(
        dsn=pathlib.Path(os.path.join(PROJECT_ROOT, "sentry.dsn")).read_text(),
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
    )
except:
    pass

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
try:
    source_rss_tree = parse(CACHE_SOURCE_RSS_FILE_PATH)
except Exception as e:
    print(f"Failed to parse {CACHE_SOURCE_RSS_FILE_PATH}:")
    print(e)
    print(f"\nContents of file:")
    with open(CACHE_SOURCE_RSS_FILE_PATH, encoding='utf-8') as f:
        print(f.read())
        sys.exit(1)

for item in source_rss_tree.iter('item'):
    item_url = item.find('link').text
    item_url_hash = hashlib.md5(item_url.encode('utf-8')).hexdigest()
    item_url_relative = item_url.removeprefix(WEBSITE_ROOT_URL)
    item_cache_file_name = f'{item_url_hash}.html'
    item_cache_file_path = CACHE_SOURCE_RSS_FILE_PATH = os.path.join(CACHE_ROOT, item_cache_file_name)
    print(f"---\nURL: {item_url_relative.ljust(40)} cache file name: {item_cache_file_name}")

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
    for page_selector in article_html.findAll('select', {"id": "phx_article_page_selector"}):
        page_selector.extract()

    # Delete <h1> and <div class="author"> elements
    # because readers like Feedly provide their own
    # based on RSS metadata
    article_html.find('h1').extract()
    article_html.find('div', {'class': 'author'}).extract()

    # Some category images are way too big,
    # and Feedly ignores size tags set for these images
    # <div class="content"> <div style="float: left; padding: 0 10px 10px;"><img alt="APPLE" height="100" src="/assets/categories/apple.webp" width="100"/></div>
    # <div class="content"> <div style="float: left; padding: 0 10px 10px;"><img alt="MICROSOFT" height="100" src="/assets/categories/microsoft.webp" width="100"/></div>
    # <div class="content"> <div style="float: left; padding: 0 10px 10px;"><img alt="MESA" height="100" src="/assets/categories/mesa.webp" width="100"/></div>
    # I could not find a way to limit image size in px/pt/%
    # that would work in Feedly web UI,
    # so replace category image tag with its alt value.
    category_img_tag_container = article_html.find('div', {'class': 'content'}).find('div')
    if category_img_tag_container:
        category_img_tag = category_img_tag_container.select_one('img[src^="/assets/categories/"]')
        if category_img_tag:
            category_replacement_tag = soup.new_tag("div")
            category_replacement_tag.string = category_img_tag['alt']
            category_img_tag.replace_with(category_replacement_tag)

    # Replace <description> tag value with full content of the article
    description = item.find('description')
    description.text = CDATA(str(article_html))

# Output augmented RSS file
source_rss_tree.write(OUTPUT_RSS_FILE_PATH, encoding = 'utf-8', xml_declaration = True)
