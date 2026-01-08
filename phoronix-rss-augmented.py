import sys
from bs4 import BeautifulSoup
import hashlib
import math
import os
import pathlib
import humanize
from requests import Session
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import time
from lxml.etree import CDATA, parse, ElementTree, Element
from glob import glob
import sentry_sdk
import re
import logging
import logging.config

# Source RSS URL
WEBSITE_ROOT_URL = 'https://www.phoronix.com'
SOURCE_RSS_URL = f"{WEBSITE_ROOT_URL}/rss.php"

# HTTP request properties
HTTP_REQUEST_INTERVAL = 15 # also used as backoff_factor when retrying failed requests
HTTP_RETRY_ATTEMPT_COUNT = 5

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

def report_failure_and_exit():
    if betterstack_heartbeat_url:
        logger.info(f"Reporting heartbeat to {betterstack_heartbeat_url}/fail")
        response = requests.get(f"{betterstack_heartbeat_url}/fail")
        if not response.ok:
            logger.error(f"Failed!")
        logger.info(f"Response: [{response.status_code}]")
    sys.exit(1)

def fetch_and_cache(url, cache_path):
    logger.info(f"Fetching fresh copy of {url}")
    time.sleep(HTTP_REQUEST_INTERVAL)
    response = requests.get(url)
    if not response.ok:
        logger.error(f"\nFailed to request content of {url}")
        logger.error(f"\nResponse:")
        logger.error(response)
        logger.error(f"\nResponse.text:")
        logger.error(response.text)
        report_failure_and_exit()
    with open(cache_path, "w", encoding='utf-8') as f:
        f.write(response.text)
    return response.text

# Init Sentry before doing anything that might raise exception
try:
    sentry_sdk.init(
        dsn=pathlib.Path(os.path.join(PROJECT_ROOT, "sentry.dsn")).read_text().strip(),
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
    )
except:
    pass

# Attempt to load Better Stack heartbeat token
betterstack_heartbeat_url = None
try:
    betterstack_heartbeat_url = pathlib.Path(os.path.join(PROJECT_ROOT, "heartbeat.url")).read_text().strip()
except:
    pass

# Set up logging
logger = logging.getLogger()
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
logging.Formatter.converter = time.gmtime
try:
    # Attempt to initialize Loggly
    logging.config.fileConfig(pathlib.Path(os.path.join(PROJECT_ROOT, "loggly.conf")))
except:
    pass

# Set up a customized instance of Requests library
# to avoid crashing on monthly DNS resolution failures
# https://stackoverflow.com/questions/23013220/max-retries-exceeded-with-url-in-requests
requests = Session()
request_retry_config = Retry(total=HTTP_RETRY_ATTEMPT_COUNT, backoff_factor=HTTP_REQUEST_INTERVAL)
http_adapter = HTTPAdapter(max_retries=request_retry_config)
requests.mount('http://', http_adapter)
requests.mount('https://', http_adapter)

current_timestamp = time.time()

# Check for Source RSS cache, [re]download if necessary
if not os.path.isfile(CACHE_SOURCE_RSS_FILE_PATH):
    logger.info(f"Source RSS cache not found")
    fetch_and_cache(SOURCE_RSS_URL, CACHE_SOURCE_RSS_FILE_PATH)
else:
    cache_source_rss_modification_timestamp = os.path.getmtime(CACHE_SOURCE_RSS_FILE_PATH)
    cache_source_rss_age_seconds = current_timestamp - cache_source_rss_modification_timestamp
    cache_source_rss_age_minutes = math.floor(cache_source_rss_age_seconds / 60)
    logger.info(f"Source RSS cache is {cache_source_rss_age_minutes} minutes old")

    if cache_source_rss_age_minutes < CACHE_SOURCE_TTL:
        logger.info("Reusing cached source RSS...")
    else:
        fetch_and_cache(SOURCE_RSS_URL, CACHE_SOURCE_RSS_FILE_PATH)

# Parse Source RSS
try:
    source_rss_tree = parse(CACHE_SOURCE_RSS_FILE_PATH)
except Exception as e:
    logger.error(f"Failed to parse {CACHE_SOURCE_RSS_FILE_PATH}:")
    logger.error(e)
    logger.error(f"\nContents of file:")
    with open(CACHE_SOURCE_RSS_FILE_PATH, encoding='utf-8') as f:
        logger.error(f.read())
    report_failure_and_exit()

# Fix metadata as suggested by RSS validator
# https://www.rssboard.org/rss-validator/
namespace_map = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "atom": "http://www.w3.org/2005/Atom",
}
original_root_element = source_rss_tree.getroot()
new_root_element = Element(original_root_element.tag, {"version": "2.0"}, namespace_map)
new_root_element.extend(original_root_element)
new_rss_tree = ElementTree(new_root_element)

link_self = Element("{http://www.w3.org/2005/Atom}link")
link_self.set("href", "https://phoronix.retromultiplayer.com/phoronix-rss-augmented.xml")
link_self.set("rel", "self")
link_self.set("type", "application/rss+xml")
new_rss_tree.find("channel").insert(0, link_self)

for item in new_rss_tree.iter('item'):
    item_url = item.find('link').text
    item_url_hash = hashlib.md5(item_url.encode('utf-8')).hexdigest()
    item_url_relative = item_url.removeprefix(WEBSITE_ROOT_URL)
    item_cache_file_name = f'item_{item_url_hash}.html'
    item_cache_file_path = CACHE_SOURCE_RSS_FILE_PATH = os.path.join(CACHE_ROOT, item_cache_file_name)
    logger.info(f"---\nURL: {item_url_relative.ljust(40)} cache file name: {item_cache_file_name}")

    # Check for item HTML cache, [re]download if necessary
    soup = None
    if not os.path.isfile(item_cache_file_path):
        logger.info(f"{item_url} cache not found")
        html_contents = fetch_and_cache(item_url, item_cache_file_path)
        soup = BeautifulSoup(html_contents, 'html.parser')
    else:
        cache_item_modification_timestamp = os.path.getmtime(item_cache_file_path)
        cache_item_age_seconds = current_timestamp - cache_item_modification_timestamp
        cache_item_age_hours = math.floor(cache_item_age_seconds / 60 / 60)
        logger.info(f"{item_url} cache is {cache_item_age_hours} hours old")

        if cache_item_age_hours < CACHE_ITEM_TTL:
            logger.info(f"Reusing cached {item_url}...")
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

    # Delete <ins class="adsbygoogle"> RSS validator is complaining about
    for ins_tag in article_html.findAll('ins', {"class": "adsbygoogle"}):
        ins_tag.extract()

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

    # Fix relative links RSS validator is complaining about
    for relative_a_element in article_html.select('a[href^="/"]:not([href^="//"])'):
        relative_a_element['href'] = f"{WEBSITE_ROOT_URL}{relative_a_element.get('href')}"

    # _Then_, fix a and img tags missing https:// protocol declaration
    for relative_a_element in article_html.select('a[href^="//"]'):
        relative_a_element['href'] = f"https:{relative_a_element.get('href')}"
    for relative_img_element in article_html.select('img[src^="//"]'):
        relative_img_element['src'] = f"https:{relative_img_element.get('src')}"

    # Comment counter is almost always wrong,
    # replace its text with a more honest one.
    # The tags we are looking for,
    # after the code above replaces all the URLs with the absolute ones,
    # look like this:
    # <a href="https://www.phoronix.com/forums/node/1551155">Add A Comment</a>
    # <a href="https://www.phoronix.com/forums/node/1551633">9 Comments</a>
    comments_a_element = article_html.find(href=re.compile('/forums/node/'), string=re.compile('Comment[s]?$'))
    if comments_a_element:
        comments_a_element.string = "[Comments]"

    # Replace <description> tag value with full content of the article
    description = item.find('description')
    description.text = CDATA(str(article_html))
logger.info(f"---")

# Output augmented RSS file
new_rss_tree.write(OUTPUT_RSS_FILE_PATH, encoding = 'utf-8', xml_declaration = True)

# Clean up old item cache files
current_time = time.time()
for item_cache_file_path in glob(os.path.join(CACHE_ROOT, "item_*.html")):
    cache_item_modification_timestamp = os.path.getmtime(item_cache_file_path)
    cache_item_age_seconds = current_timestamp - cache_item_modification_timestamp
    cache_item_age_hours = cache_item_age_seconds / 60 / 60

    if cache_item_age_hours > CACHE_ITEM_TTL:
        logger.info(f"Item cache file {os.path.basename(item_cache_file_path)} is >{math.floor(cache_item_age_hours)} hours old, deleting")
        os.remove(item_cache_file_path)

humanized_execution_duration = humanize.precisedelta(time.time() - current_timestamp, minimum_unit="seconds", format="%.0f")
logger.info(f"Completed in {humanized_execution_duration}")

# Report success to Better Stack
if betterstack_heartbeat_url:
    logger.info(f"Reporting heartbeat to {betterstack_heartbeat_url}")
    response = requests.get(betterstack_heartbeat_url)
    if not response.ok:
        logger.error(f"Failed!")
    logger.info(f"Response: [{response.status_code}]")
