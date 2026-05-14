"""Phoronix RSS Augmented.

Injects full content of Phoronix news articles into RSS feed.
"""

import hashlib
import logging
import logging.config
import math
import re
import sys
import time
from pathlib import Path

import humanize
import newrelic.agent
import sentry_sdk
from bs4 import BeautifulSoup
from lxml.etree import CDATA, Element, ElementTree, parse
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Source RSS URL
WEBSITE_ROOT_URL = "https://www.phoronix.com"
SOURCE_RSS_URL = f"{WEBSITE_ROOT_URL}/rss.php"

# HTTP request properties
HTTP_REQUEST_INTERVAL = 15  # also used as backoff_factor when retrying failed requests
HTTP_RETRY_ATTEMPT_COUNT = 5

# Define file paths
PROJECT_ROOT = Path(__file__).parent.resolve()

# Define cache properties
CACHE_ROOT = PROJECT_ROOT / "cache"
CACHE_SOURCE_RSS_FILE_PATH = CACHE_ROOT / "source_rss.xml"
CACHE_SOURCE_TTL = 55  # minutes
CACHE_ITEM_TTL = 24  # hours

# Define output properties
OUTPUT_ROOT = PROJECT_ROOT / "output"
OUTPUT_RSS_FILE_PATH = OUTPUT_ROOT / "phoronix-rss-augmented.xml"


def report_failure_and_exit():
    if betterstack_heartbeat_url:
        logger.info("Reporting heartbeat to %s/fail", betterstack_heartbeat_url)
        response = requests.get(f"{betterstack_heartbeat_url}/fail")
        if not response.ok:
            logger.error("Failed!")
        logger.info("Response: [%d]", response.status_code)
    sys.exit(1)


def fetch_and_cache(url, cache_path):
    logger.info("Fetching fresh copy of %s", url)
    time.sleep(HTTP_REQUEST_INTERVAL)
    response = requests.get(url)
    if not response.ok:
        logger.error("\nFailed to request content of %s", url)
        logger.error("\nResponse:")
        logger.error(response)
        logger.error("\nResponse.text:")
        logger.error(response.text)
        report_failure_and_exit()
    with cache_path.open("w", encoding="utf-8") as f:
        f.write(response.text)
    return response.text


# Init Sentry before doing anything that might raise exception
try:
    sentry_sdk.init(
        dsn=(PROJECT_ROOT / "sentry.dsn").read_text().strip(),
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
    )
except OSError:
    pass

# Attempt to load Better Stack heartbeat token
betterstack_heartbeat_url = None
try:
    betterstack_heartbeat_url = (PROJECT_ROOT / "heartbeat.url").read_text().strip()
except OSError:
    pass

# Set up logging
logger = logging.getLogger()
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
logging.Formatter.converter = time.gmtime

if not (sys.gettrace() or "debugpy" in sys.modules):
    # Attempt to initialize Loggly
    try:
        logging.config.fileConfig(PROJECT_ROOT / "loggly.conf")
    except OSError:
        pass

    # Attempt to set up New Relic
    try:
        newrelic.agent.initialize(PROJECT_ROOT / "newrelic.ini")

        # without timeout parameter,
        # the entire script often executes faster than New Relic can initialize itself
        newrelic.agent.register_application(timeout=10)
    except OSError:
        pass

# Set up a customized instance of Requests library
# to avoid crashing on monthly DNS resolution failures
# https://stackoverflow.com/questions/23013220/max-retries-exceeded-with-url-in-requests
requests = Session()
request_retry_config = Retry(
    total=HTTP_RETRY_ATTEMPT_COUNT,
    backoff_factor=HTTP_REQUEST_INTERVAL,
)
http_adapter = HTTPAdapter(max_retries=request_retry_config)
requests.mount("http://", http_adapter)
requests.mount("https://", http_adapter)

current_timestamp = time.time()

# Check for Source RSS cache, [re]download if necessary
if not CACHE_SOURCE_RSS_FILE_PATH.is_file():
    logger.info("Source RSS cache not found")
    fetch_and_cache(SOURCE_RSS_URL, CACHE_SOURCE_RSS_FILE_PATH)
else:
    cache_source_rss_modification_timestamp = CACHE_SOURCE_RSS_FILE_PATH.stat().st_mtime
    cache_source_rss_age_seconds = (
        current_timestamp - cache_source_rss_modification_timestamp
    )
    cache_source_rss_age_minutes = math.floor(cache_source_rss_age_seconds / 60)
    logger.info("Source RSS cache is %d minutes old", cache_source_rss_age_minutes)

    if cache_source_rss_age_minutes < CACHE_SOURCE_TTL:
        logger.info("Reusing cached source RSS...")
    else:
        fetch_and_cache(SOURCE_RSS_URL, CACHE_SOURCE_RSS_FILE_PATH)

# Parse Source RSS
try:
    source_rss_tree = parse(CACHE_SOURCE_RSS_FILE_PATH)
except Exception as e:
    logger.error("Failed to parse %s:", CACHE_SOURCE_RSS_FILE_PATH)
    logger.error(e)
    logger.error("\nContents of file:")
    with CACHE_SOURCE_RSS_FILE_PATH.open(encoding="utf-8") as f:
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
link_self.set(
    "href",
    "https://phoronix.retromultiplayer.com/phoronix-rss-augmented.xml",
)
link_self.set("rel", "self")
link_self.set("type", "application/rss+xml")
new_rss_tree.find("channel").insert(0, link_self)

for item in new_rss_tree.iter("item"):
    item_url = item.find("link").text
    item_url_hash = hashlib.md5(item_url.encode("utf-8")).hexdigest()
    item_url_relative = item_url.removeprefix(WEBSITE_ROOT_URL)
    item_cache_file_name = f"item_{item_url_hash}.html"
    item_cache_file_path = CACHE_ROOT / item_cache_file_name

    logger.info(
        "---\nURL: %s cache file name: %s",
        item_url_relative.ljust(40),
        item_cache_file_name,
    )

    # Check for item HTML cache, [re]download if necessary
    soup = None
    if not item_cache_file_path.is_file():
        logger.info("%s cache not found", item_url)
        html_contents = fetch_and_cache(item_url, item_cache_file_path)
        soup = BeautifulSoup(html_contents, "html.parser")
    else:
        cache_item_modification_timestamp = item_cache_file_path.stat().st_mtime
        cache_item_age_seconds = current_timestamp - cache_item_modification_timestamp
        cache_item_age_hours = math.floor(cache_item_age_seconds / 60 / 60)
        logger.info("%s cache is %d hours old", item_url, cache_item_age_hours)

        if cache_item_age_hours < CACHE_ITEM_TTL:
            logger.info("Reusing cached %s...", item_url)
            with item_cache_file_path.open(encoding="utf-8") as f:
                soup = BeautifulSoup(f, "html.parser")
        else:
            html_contents = fetch_and_cache(item_url, item_cache_file_path)
            soup = BeautifulSoup(html_contents, "html.parser")

    # Extract article
    article_html = soup.find("article")

    # Delete JavaScript
    for script_tag in article_html.find_all("script"):
        script_tag.extract()

    # Delete sharebar
    for sharebar in article_html.find_all("div", {"id": "sharebar"}):
        sharebar.extract()

    # Delete <ins class="adsbygoogle"> RSS validator is complaining about
    for ins_tag in article_html.find_all("ins", {"class": "adsbygoogle"}):
        ins_tag.extract()

    # Multipage articles contain page selector element
    # that has invalid (for RSS) onchange attribute.
    # Delete it for now to pass validation
    # but maybe later i could implement
    # fetching the entire content of multipage articles.
    for page_selector in article_html.find_all(
        "select",
        {"id": "phx_article_page_selector"},
    ):
        page_selector.extract()

    # Delete <h1> and <div class="author"> elements
    # because readers like Feedly provide their own
    # based on RSS metadata
    article_html.find("h1").extract()
    article_html.find("div", {"class": "author"}).extract()

    # Some category images are way too big,
    # and Feedly ignores size tags set for these images
    # <div class="content">
    #   <div style="float: left; padding: 0 10px 10px;">
    #       <img alt="APPLE" height="100"
    #           src="/assets/categories/apple.webp" width="100"/>
    #   </div>
    # <div class="content">
    #   <div style="float: left; padding: 0 10px 10px;">
    #       <img alt="MICROSOFT" height="100"
    #           src="/assets/categories/microsoft.webp" width="100"/>
    #   </div>
    # <div class="content">
    #   <div style="float: left; padding: 0 10px 10px;">
    #       <img alt="MESA" height="100"
    #           src="/assets/categories/mesa.webp" width="100"/>
    #   </div>
    # I could not find a way to limit image size in px/pt/%
    # that would work in Feedly web UI,
    # so replace category image tag with its alt value.
    category_img_tag_container = article_html.find("div", {"class": "content"}).find(
        "div",
    )
    if category_img_tag_container:
        category_img_tag = category_img_tag_container.select_one(
            'img[src^="/assets/categories/"]',
        )
        if category_img_tag:
            category_replacement_tag = soup.new_tag("div")
            category_replacement_tag.string = category_img_tag["alt"]
            category_img_tag.replace_with(category_replacement_tag)

    # Fix relative links RSS validator is complaining about
    for relative_a_element in article_html.select('a[href^="/"]:not([href^="//"])'):
        relative_a_element["href"] = (
            f"{WEBSITE_ROOT_URL}{relative_a_element.get('href')}"
        )

    # _Then_, fix a and img tags missing https:// protocol declaration
    for relative_a_element in article_html.select('a[href^="//"]'):
        relative_a_element["href"] = f"https:{relative_a_element.get('href')}"
    for relative_img_element in article_html.select('img[src^="//"]'):
        relative_img_element["src"] = f"https:{relative_img_element.get('src')}"

    # Comment counter is almost always wrong,
    # replace its text with a more honest one.
    # The tags we are looking for,
    # after the code above replaces all the URLs with the absolute ones,
    # look like this:
    # <a href="https://www.phoronix.com/forums/node/1551155">Add A Comment</a>
    # <a href="https://www.phoronix.com/forums/node/1551633">9 Comments</a>
    comments_a_element = article_html.find(
        href=re.compile("/forums/node/"),
        string=re.compile("Comment[s]?$"),
    )
    if comments_a_element:
        comments_a_element.string = "[Comments]"

    # Replace <description> tag value with full content of the article
    description = item.find("description")
    description.text = CDATA(str(article_html))
logger.info("---")

# Output augmented RSS file
new_rss_tree.write(OUTPUT_RSS_FILE_PATH, encoding="utf-8", xml_declaration=True)

# Clean up old item cache files
current_time = time.time()
for item_cache_file_path in CACHE_ROOT.glob("item_*.html"):
    cache_item_modification_timestamp = item_cache_file_path.stat().st_mtime
    cache_item_age_seconds = current_timestamp - cache_item_modification_timestamp
    cache_item_age_hours = cache_item_age_seconds / 60 / 60

    if cache_item_age_hours > CACHE_ITEM_TTL:
        logger.info(
            "Item cache file %s is >%d hours old, deleting",
            item_cache_file_path.name,
            math.floor(cache_item_age_hours),
        )
        item_cache_file_path.unlink()

humanized_execution_duration = humanize.precisedelta(
    time.time() - current_timestamp,
    minimum_unit="seconds",
    format="%.0f",
)
logger.info("Completed in %s", humanized_execution_duration)

# Report success to Better Stack
if betterstack_heartbeat_url:
    logger.info("Reporting heartbeat to %s", betterstack_heartbeat_url)
    response = requests.get(betterstack_heartbeat_url)
    if not response.ok:
        logger.error("Failed!")
    logger.info("Response: [%d]", response.status_code)
