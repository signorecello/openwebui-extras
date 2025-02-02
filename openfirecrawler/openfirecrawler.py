"""
title: Firecrawl Crawler
description: Web crawler using FireCrawl with Langchain integration
author: @signorecello
author_url: https://openwebui.com/u/signorecelloo/
funding_url: https://github.com/signorecello
version: 0.3.0
license: MIT
"""

# v0.3.0 - Made crawling more reliable (perhaps even working). Did my best to clean up the content but truth is that crawls will almost always blow up your context window

import logging
from typing import Callable, Any
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
from firecrawl import FirecrawlApp
import sys
import asyncio
import json

# Configure logging
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, force=True)
logger = logging.getLogger(__name__)


class EventEmitter:
    def __init__(
        self, event_emitter: Callable[[dict], Any] = None, show_logs: bool = True
    ):
        """
        :param event_emitter: Function to emit events to the chat.
        :param show_logs: Toggle to enable or disable event emitting (for debugging).
        """
        self.event_emitter = event_emitter
        self.show_logs = show_logs

    async def progress_update(self, description):
        if self.show_logs:
            await self.emit(description)

    async def error_update(self, description):
        if self.show_logs:
            await self.emit(description, "error")

    async def success_update(self, description):
        if self.show_logs:
            await self.emit(description, "success", True)

    async def emit(self, description="Unknown State", status="in_progress", done=False):
        if self.event_emitter:
            event_data = {
                "type": "status",
                "data": {
                    "status": status,
                    "description": description,
                    "done": done,
                },
            }

            # Handle both async and sync event emitters
            if asyncio.iscoroutinefunction(self.event_emitter):
                await self.event_emitter(event_data)
            else:
                self.event_emitter(event_data)


class Tools:
    class Valves(BaseModel):
        API_URL: str = Field(
            default="https://api.firecrawl.dev",
            description="Firecrawl API URL",
        )
        API_KEY: str = Field(
            default="api_key",
            description="Firecrawl API key for web crawling. Get one at https://firecrawl.dev.",
        )
        SHOW_LOGS: bool = Field(
            default=True,
            description="Toggle Event Emitters. If False, no status updates are shown.",
        )
        LIMIT: int = Field(default=100, description="Max number of pages to crawl")
        DEFAULT_FORMAT: str = Field(
            default="html", description="Default format for content return"
        )
        MAX_DEPTH: int = Field(
            default=2,
            description="Maximum crawling depth for nested pages",
        )
        CLEAN_CONTENT: bool = Field(
            default=True,
            description="Remove links and image urls from scraped content. This reduces the number of tokens.",
        )

    def __init__(self, valves: Valves = None):
        self.valves = valves or self.Valves()
        logger.debug(f"Initialized Tools with valves: {self.valves}")


    async def scrape_website(
        self,
        url: str,
        __event_emitter__: Callable[[dict], Any] = None,
        params: dict | None = None,
    ) -> str:
        """
        Scrape a website page, returning title and content
        
        :params url: The URL of the website page to scrape
        :return: The titles and contents of the website ºage
        """
        logger.debug(f"Starting scraping URL: {url}")
        emitter = EventEmitter(__event_emitter__, self.valves.SHOW_LOGS)
        await emitter.progress_update(f"Starting scraping of {url}")
        results = []

        # Prepare params with defaults
        scrape_params = {
            "formats": [self.valves.DEFAULT_FORMAT],
        }
        if params:
            scrape_params.update(params)
            logger.debug(f"Using custom params for scrape: {scrape_params}")

        logger.debug(
            f"Initializing FireCrawlLoader for scrape with params: {scrape_params}"
        )

        logger.debug("Starting scrape document load")
        await emitter.progress_update(f"Starting scrape document load")
        
        firecrawl = FirecrawlApp(
            api_key=self.valves.API_KEY, api_url=self.valves.API_URL
        )
        doc = firecrawl.scrape_url(url, scrape_params)

        await emitter.progress_update(
            f"Scrape successful. Processing..."
        )

        content = ""
        if "html" in doc:
            content = doc["html"]
            if self.valves.CLEAN_CONTENT:
                content = clean_links(content)
                content = clean_images(content)
        elif "markdown" in doc:
            content = doc["markdown"]

        # Extract metadata for each page
        title = doc["metadata"]["title"]
        source_url = doc["metadata"]["sourceURL"]

        results.append(
            {"url": source_url, "title": title, "content": content, "errors": []}
        )

        await emitter.success_update(f"Successfully processed scrape")
        return json.dumps(results)


    async def crawl_website(
        self,
        url: str,
        __event_emitter__: Callable[[dict], Any] = None,
        params: dict | None = None,
    ) -> str:
        """
        Crawl a website and its subpages, returning a list of dictionaries containing title, content, links, images and errors for each page.
        
        :params url: The URL of the website to crawl
        :return: The titles, contents and links for each page
        """
        logger.debug(f"Starting website crawl for URL: {url}")
        emitter = EventEmitter(__event_emitter__, self.valves.SHOW_LOGS)
        await emitter.progress_update(f"Starting crawl of {url}")
        results = []

        # Prepare params with defaults
        crawl_params = {
            "limit": self.valves.LIMIT,
            "maxDepth": self.valves.MAX_DEPTH,
            "scrapeOptions": {"formats": [self.valves.DEFAULT_FORMAT]},
        }
        if params:
            crawl_params.update(params)
            logger.debug(f"Using custom params for crawl: {crawl_params}")

        logger.debug(
            f"Initializing FireCrawlLoader for crawl with params: {crawl_params}"
        )

        logger.debug("Starting crawl document load")
        await emitter.progress_update(f"Starting crawl document load")
        
        firecrawl = FirecrawlApp(
            api_key=self.valves.API_KEY, api_url=self.valves.API_URL
        )
        docs = []
        firecrawl_docs = firecrawl.async_crawl_url(url, crawl_params)
        logger.debug(f"Crawl started with ID: {firecrawl_docs['id']}")

        # Wait for crawl completion
        while True:
            status = firecrawl.check_crawl_status(firecrawl_docs["id"])
            logger.debug(f"Crawl status: {status['status']}")
            # await emitter.progress_update(f"Crawl status: {status}")

            if status["status"] in ["completed", "failed"]:
                break

            await asyncio.sleep(2)  # Wait 2 seconds before checking again

        if status["status"] == "failed":
            error_msg = f"Crawl failed for URL: {url}"
            logger.debug(error_msg)
            await emitter.error_update(error_msg, True)
            return []

        docs = status["data"]

        await emitter.progress_update(
            f"Crawl successful. Received {len(docs)} documents. Processing..."
        )

        logger.debug(f"Before processing {len(docs)} pages: {len(json.dumps(docs))}")


        for i, doc in enumerate(docs, 1):
            logger.debug(f"Processing document {i}/{len(docs)}")
            await emitter.progress_update(f"Processing document {i}/{len(docs)}")

            content = ""
            if "html" in doc:
                content = doc["html"]
                if self.valves.CLEAN_CONTENT:
                    content = clean_links(content)
                    content = clean_images(content)
            elif "markdown" in doc:
                content = doc["markdown"]

            # Extract metadata for each page
            title = doc["metadata"]["title"]
            source_url = doc["metadata"]["sourceURL"]

            results.append(
                {"url": source_url, "title": title, "content": content, "errors": []}
            )

        await emitter.success_update(f"Successfully processed {len(results)} pages")
        logger.debug(f"After processing {len(results)} pages: {len(json.dumps(results))}")
        return json.dumps(results)


def clean_links(text) -> str:
    """Remove links, citations, and reference elements from HTML content."""
    soup = BeautifulSoup(text, "html.parser")

    # Remove all citation and reference elements
    citation_classes = ['citation', 'reference', 'cite', 'reflist', 'references']
    citation_elements = ['cite', 'sup', 'span']
    
    # Remove elements with citation-related classes
    for class_name in citation_classes:
        for element in soup.find_all(class_=lambda x: x and class_name in x.lower()):
            element.decompose()
    
    # Remove common citation elements
    for element in soup.find_all(citation_elements):
        element.decompose()
    
    # Remove links but keep their text
    for link in soup.find_all('a'):
        link.replace_with(link.get_text())
    
    # Remove any remaining elements with 'cite' or 'ref' in their id
    for element in soup.find_all(id=lambda x: x and ('cite' in x.lower() or 'ref' in x.lower())):
        element.decompose()
        
    # Clean up any empty list items that might remain
    for li in soup.find_all('li'):
        if len(li.get_text(strip=True)) == 0:
            li.decompose()
        
    return str(soup)

def clean_images(text) -> str:
    """Remove images from HTML content."""
    soup = BeautifulSoup(text, "html.parser")
    # Remove all images
    for img in soup.find_all('img'):
        img.decompose()
        
    # Remove figure elements (usually contain images with captions)
    for figure in soup.find_all('figure'):
        figure.decompose()
        
    return str(soup)
