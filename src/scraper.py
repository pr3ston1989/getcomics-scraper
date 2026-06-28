"""Main scraper module - handles sitemap parsing and page scraping with pause/resume."""
import time
import random
import signal
import logging
from datetime import datetime
from typing import List, Optional
from xml.etree import ElementTree

import requests
from sqlalchemy.orm import Session

from .models import (
    Comic, Tag, DownloadLink, ScrapeState,
    get_session, init_db
)
from .parser import parse_comic_page
from .config import Config
from .link_resolver import LinkResolver

logger = logging.getLogger(__name__)


class Scraper:
    """GetComics scraper with pause/resume and rate limiting."""

    def __init__(self, config: Config):
        self.config = config
        self.session = get_session(config.database_url)
        self.resolver = LinkResolver(config)
        self._stop_requested = False
        self._pause_requested = False
        self._setup_signal_handlers()
        init_db(config.database_url)

    def _setup_signal_handlers(self):
        """Setup graceful shutdown on SIGINT/SIGTERM."""
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

    def _handle_stop(self, signum, frame):
        """Handle stop signal - finish current page then stop."""
        logger.info("Stop signal received. Finishing current page...")
        self._stop_requested = True

    def request_pause(self):
        """Request scraper to pause after current page."""
        self._pause_requested = True

    def request_stop(self):
        """Request scraper to stop after current page."""
        self._stop_requested = True

    def scrape_sitemap(self, resume: bool = True):
        """
        Scrape all comics from the sitemap.

        Args:
            resume: If True, resume from last saved position.
        """
        logger.info("Starting sitemap scrape...")

        # Get or create scrape state
        state = self._get_or_create_state()

        if resume and state.status == 'paused':
            logger.info(f"Resuming from URL #{state.processed_urls}")
        else:
            state.status = 'running'
            state.started_at = datetime.utcnow()
            state.processed_urls = 0

        # Fetch sitemap index
        urls = self._get_all_comic_urls()
        state.total_urls = len(urls)
        self.session.commit()

        logger.info(f"Found {len(urls)} comic URLs to process")

        # Skip already processed URLs if resuming
        start_index = state.processed_urls if resume else 0

        for i, url in enumerate(urls[start_index:], start=start_index):
            if self._stop_requested:
                state.status = 'stopped'
                state.paused_at = datetime.utcnow()
                self.session.commit()
                logger.info(f"Scraper stopped at URL #{i}")
                return

            if self._pause_requested:
                state.status = 'paused'
                state.paused_at = datetime.utcnow()
                state.processed_urls = i
                state.last_processed_url = url
                self.session.commit()
                logger.info(f"Scraper paused at URL #{i}")
                self._pause_requested = False
                return

            # Check if already scraped
            existing = self.session.query(Comic).filter_by(page_url=url).first()
            if existing:
                state.processed_urls = i + 1
                if (i + 1) % 100 == 0:
                    self.session.commit()
                continue

            # Scrape the page
            try:
                self._scrape_page(url)
                state.processed_urls = i + 1
                state.last_processed_url = url

                if (i + 1) % 10 == 0:
                    self.session.commit()
                    logger.info(f"Progress: {i + 1}/{len(urls)} pages scraped")

            except Exception as e:
                logger.error(f"Error scraping {url}: {e}")
                state.processed_urls = i + 1
                self.session.commit()

            # Rate limiting
            self._delay()

        state.status = 'completed'
        state.completed_at = datetime.utcnow()
        self.session.commit()
        logger.info("Sitemap scrape completed!")

    def _get_all_comic_urls(self) -> List[str]:
        """Fetch sitemap index and extract all comic page URLs."""
        logger.info("Fetching sitemap index...")
        urls = []

        try:
            resp = self._fetch_url(self.config.sitemap_url)
            if not resp:
                return urls

            # Parse sitemap index
            root = ElementTree.fromstring(resp.content)
            ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            sitemap_urls = []
            for sitemap in root.findall('.//sm:sitemap/sm:loc', ns):
                sitemap_urls.append(sitemap.text)

            # Also check for direct URL entries (in case it's a flat sitemap)
            for url_entry in root.findall('.//sm:url/sm:loc', ns):
                url = url_entry.text
                if url and self._is_comic_url(url):
                    urls.append(url)

            logger.info(f"Found {len(sitemap_urls)} sub-sitemaps")

            # Fetch each sub-sitemap
            for sitemap_url in sitemap_urls:
                self._delay()
                sub_urls = self._fetch_sub_sitemap(sitemap_url)
                urls.extend(sub_urls)
                logger.info(f"Sub-sitemap {sitemap_url}: {len(sub_urls)} URLs")

        except Exception as e:
            logger.error(f"Error fetching sitemap: {e}")

        return urls

    def _fetch_sub_sitemap(self, url: str) -> List[str]:
        """Fetch a sub-sitemap and extract comic URLs."""
        urls = []
        try:
            resp = self._fetch_url(url)
            if not resp:
                return urls

            root = ElementTree.fromstring(resp.content)
            ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            for url_entry in root.findall('.//sm:url/sm:loc', ns):
                page_url = url_entry.text
                if page_url and self._is_comic_url(page_url):
                    urls.append(page_url)

        except Exception as e:
            logger.error(f"Error fetching sub-sitemap {url}: {e}")

        return urls

    def _is_comic_url(self, url: str) -> bool:
        """Check if URL is a comic page (not a category/tag/page)."""
        skip_patterns = [
            '/tag/', '/category/', '/page/',
            '/wp-content/', '/wp-admin/',
            '/feed/', '/comment-page-',
            'getcomics.org/sitemap', '/author/'
        ]
        return not any(pattern in url for pattern in skip_patterns)

    def _scrape_page(self, url: str):
        """Scrape a single comic page and save to database."""
        resp = self._fetch_url(url)
        if not resp:
            return

        # Parse the page
        data = parse_comic_page(resp.text, url)

        # Create comic record
        comic = Comic(
            title=data['title'],
            page_url=url,
            language=data.get('language'),
            image_format=data.get('image_format'),
            year=data.get('year'),
            size=data.get('size'),
            series=data.get('series'),
            issue_number=data.get('issue_number'),
            description=data.get('description'),
            published_at=data.get('published_at'),
        )

        # Add tags
        for tag_name in data.get('tags', []):
            tag = self.session.query(Tag).filter_by(name=tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                self.session.add(tag)
            comic.tags.append(tag)

        # Add download links (save original URL from page + try to resolve)
        for link_data in data.get('download_links', []):
            original_url = link_data['url']
            host = link_data.get('host', 'unknown')
            is_external = host in ('mega', 'mediafire', 'google_drive', 'pixeldrain', 'workupload', 'uploadhaven')

            link = DownloadLink(
                original_url=original_url,
                host=host,
                label=link_data.get('label'),
                is_direct=not is_external,
                is_external=is_external,
            )

            # Try to resolve redirect links during scraping (cache the result)
            if not is_external and 'getcomics.org/dls/' in original_url:
                resolved, _ = self.resolver.resolve(original_url)
                if resolved and resolved != original_url:
                    link.resolved_url = resolved
                    link.resolved_at = datetime.utcnow()

            comic.download_links.append(link)

        self.session.add(comic)

    def _fetch_url(self, url: str) -> Optional[requests.Response]:
        """Fetch a URL with proper headers and error handling."""
        headers = {
            'User-Agent': self.config.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def _delay(self):
        """Apply rate limiting delay."""
        delay = random.uniform(
            self.config.scrape_delay_min,
            self.config.scrape_delay_max
        )
        time.sleep(delay)

    def _get_or_create_state(self) -> ScrapeState:
        """Get existing scrape state or create new one."""
        state = self.session.query(ScrapeState).filter_by(
            sitemap_url=self.config.sitemap_url
        ).first()

        if not state:
            state = ScrapeState(
                sitemap_url=self.config.sitemap_url,
                status='idle'
            )
            self.session.add(state)
            self.session.commit()

        return state

    def get_progress(self) -> dict:
        """Get current scraping progress."""
        state = self._get_or_create_state()
        total_comics = self.session.query(Comic).count()
        total_links = self.session.query(DownloadLink).count()

        return {
            'status': state.status,
            'processed': state.processed_urls,
            'total': state.total_urls,
            'percent': (state.processed_urls / state.total_urls * 100) if state.total_urls > 0 else 0,
            'total_comics_in_db': total_comics,
            'total_links_in_db': total_links,
            'started_at': state.started_at,
            'last_update': state.updated_at,
        }

    def scrape_updates(self):
        """
        Incremental scrape - only process new comics since last run.
        Compares sitemap URLs against what's already in the database.
        Stops when it encounters already-scraped pages (since sitemap is ordered newest first).
        """
        logger.info("Starting incremental update...")

        urls = self._get_all_comic_urls()
        new_count = 0
        skipped_streak = 0
        max_skipped_streak = 20  # Stop after 20 consecutive already-scraped pages

        for url in urls:
            if self._stop_requested:
                logger.info(f"Update stopped. Added {new_count} new comics.")
                return new_count

            # Check if already in database
            existing = self.session.query(Comic).filter_by(page_url=url).first()
            if existing:
                skipped_streak += 1
                if skipped_streak >= max_skipped_streak:
                    logger.info(
                        f"Found {max_skipped_streak} consecutive known comics. "
                        f"Assuming no more new content."
                    )
                    break
                continue

            skipped_streak = 0

            try:
                self._scrape_page(url)
                new_count += 1
                if new_count % 10 == 0:
                    self.session.commit()
                    logger.info(f"New comics found so far: {new_count}")
            except Exception as e:
                logger.error(f"Error scraping {url}: {e}")

            self._delay()

        self.session.commit()
        logger.info(f"Incremental update completed. Added {new_count} new comics.")
        return new_count
