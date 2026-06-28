"""
Main scraper module - adaptive speed, retry logic, progress display.

Strategy:
- Start fast (minimal delay)
- On errors (429, 503, timeouts): exponential backoff + retry
- On success streak: speed back up
- Failed URLs are retried up to MAX_RETRIES times before being skipped
- Nothing is lost: failed URLs are logged and can be retried later
"""
import time
import signal
import logging
from datetime import datetime
from typing import List, Optional, Tuple
from xml.etree import ElementTree

import requests
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn,
    TimeRemainingColumn, TimeElapsedColumn, MofNCompleteColumn,
    TaskProgressColumn
)
from rich.console import Console
from sqlalchemy.orm import Session

from .models import (
    Comic, Tag, DownloadLink, ScrapeState,
    get_session, init_db
)
from .parser import parse_comic_page
from .config import Config
from .link_resolver import LinkResolver

logger = logging.getLogger(__name__)
console = Console()

# Adaptive speed constants
MIN_DELAY = 0.3          # Fastest we'll go (seconds)
DEFAULT_DELAY = 0.5      # Starting delay
MAX_DELAY = 60.0         # Slowest (after many errors)
SPEEDUP_AFTER = 10       # Speed up after N consecutive successes
SLOWDOWN_FACTOR = 2.0    # Multiply delay by this on error
SPEEDUP_FACTOR = 0.7     # Multiply delay by this on success streak
MAX_RETRIES = 3          # Max retries per URL


class Scraper:
    """GetComics scraper with adaptive speed, retry, and rich progress."""

    def __init__(self, config: Config):
        self.config = config
        self.session = get_session(config.database_url)
        self.resolver = LinkResolver(config)
        self._stop_requested = False
        self._pause_requested = False
        self._setup_signal_handlers()
        init_db(config.database_url)

        # Adaptive speed state
        self._current_delay = DEFAULT_DELAY
        self._consecutive_successes = 0
        self._total_errors = 0
        self._total_retries = 0

        # Failed URLs for retry
        self._failed_urls: List[Tuple[str, int]] = []  # (url, retry_count)

    def _setup_signal_handlers(self):
        """Setup graceful shutdown on SIGINT/SIGTERM."""
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

    def _handle_stop(self, signum, frame):
        """Handle stop signal - finish current page then stop."""
        console.print("\n[yellow]Stop signal received. Finishing current page...[/yellow]")
        self._stop_requested = True

    def request_pause(self):
        self._pause_requested = True

    def request_stop(self):
        self._stop_requested = True

    def _safe_commit(self):
        """Commit with retry on database lock. Handles rollback state."""
        for attempt in range(5):
            try:
                self.session.commit()
                return
            except Exception as e:
                error_str = str(e)
                if 'database is locked' in error_str:
                    self.session.rollback()
                    time.sleep(0.5 * (attempt + 1))
                    logger.debug(f"DB locked, retry commit {attempt + 1}/5")
                elif 'PendingRollbackError' in error_str or 'rolled back' in error_str:
                    self.session.rollback()
                    return  # After rollback, nothing to commit
                elif 'UNIQUE constraint' in error_str or 'IntegrityError' in error_str:
                    self.session.rollback()
                    return  # Duplicate - safe to ignore
                else:
                    self.session.rollback()
                    raise
        # Last attempt
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()

    # ==================== ADAPTIVE SPEED ====================

    def _on_success(self):
        """Called after a successful request."""
        self._consecutive_successes += 1
        if self._consecutive_successes >= SPEEDUP_AFTER:
            old_delay = self._current_delay
            self._current_delay = max(MIN_DELAY, self._current_delay * SPEEDUP_FACTOR)
            if self._current_delay != old_delay:
                logger.debug(f"Speed up: {old_delay:.2f}s -> {self._current_delay:.2f}s")
            self._consecutive_successes = 0

    def _on_error(self, is_rate_limit: bool = False):
        """Called after a failed request."""
        self._consecutive_successes = 0
        self._total_errors += 1

        old_delay = self._current_delay
        if is_rate_limit:
            # Aggressive slowdown for rate limits
            self._current_delay = min(MAX_DELAY, self._current_delay * SLOWDOWN_FACTOR * 2)
        else:
            self._current_delay = min(MAX_DELAY, self._current_delay * SLOWDOWN_FACTOR)

        logger.debug(f"Slowdown: {old_delay:.2f}s -> {self._current_delay:.2f}s")

    def _delay(self):
        """Apply current adaptive delay."""
        if self._current_delay > 0:
            time.sleep(self._current_delay)

    # ==================== FETCH WITH RETRY ====================

    def _fetch_url(self, url: str, retries: int = MAX_RETRIES) -> Optional[requests.Response]:
        """
        Fetch a URL with retry and adaptive speed.
        Rate limits (429) don't count against retry limit - we always wait and try again.
        """
        headers = {
            'User-Agent': self.config.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }

        attempt = 0
        rate_limit_hits = 0
        max_rate_limit_waits = 5  # Max consecutive 429s before giving up

        while attempt < retries:
            try:
                resp = requests.get(url, headers=headers, timeout=20)

                if resp.status_code == 200:
                    self._on_success()
                    return resp

                if resp.status_code == 429:
                    # Rate limited - DON'T count as a retry attempt
                    rate_limit_hits += 1
                    if rate_limit_hits > max_rate_limit_waits:
                        logger.error(f"Too many rate limits ({rate_limit_hits}) for: {url}")
                        return None

                    retry_after = int(resp.headers.get('Retry-After', 30))
                    # Increase wait with each consecutive 429
                    wait_time = retry_after * rate_limit_hits
                    self._on_error(is_rate_limit=True)
                    logger.warning(
                        f"Rate limited (429). Waiting {wait_time}s "
                        f"(hit #{rate_limit_hits})..."
                    )
                    time.sleep(wait_time)
                    self._total_retries += 1
                    continue  # Don't increment attempt

                if resp.status_code in (500, 502, 503, 504):
                    self._on_error()
                    wait = 5 * (attempt + 1)
                    logger.warning(f"Server error {resp.status_code}. Retry {attempt + 1}/{retries} in {wait}s...")
                    time.sleep(wait)
                    self._total_retries += 1
                    attempt += 1
                    continue

                if resp.status_code == 404:
                    logger.debug(f"404 Not Found: {url}")
                    return None

                resp.raise_for_status()

            except requests.Timeout:
                self._on_error()
                wait = 5 * (attempt + 1)
                logger.warning(f"Timeout. Retry {attempt + 1}/{retries} in {wait}s...")
                time.sleep(wait)
                self._total_retries += 1
                attempt += 1

            except requests.ConnectionError:
                self._on_error()
                wait = 10 * (attempt + 1)
                logger.warning(f"Connection error. Retry {attempt + 1}/{retries} in {wait}s...")
                time.sleep(wait)
                self._total_retries += 1
                attempt += 1

            except requests.RequestException as e:
                self._on_error()
                logger.warning(f"Request error for {url}: {e}")
                attempt += 1
                if attempt < retries:
                    time.sleep(5 * attempt)
                    self._total_retries += 1

        logger.error(f"All {retries} retries exhausted for: {url}")
        return None

    # ==================== MAIN SCRAPE ====================

    def scrape_sitemap(self, resume: bool = True):
        """Scrape all comics from sitemap with progress bar."""
        state = self._get_or_create_state()

        if resume and state.status in ('paused', 'stopped'):
            console.print(f"[green]Resuming from position #{state.processed_urls}[/green]")
        else:
            state.status = 'running'
            state.started_at = datetime.utcnow()
            state.processed_urls = 0

        # Fetch sitemap
        console.print("[cyan]Fetching sitemap index...[/cyan]")
        urls = self._get_all_comic_urls()
        state.total_urls = len(urls)
        self._safe_commit()

        if not urls:
            console.print("[red]No URLs found in sitemap![/red]")
            return

        console.print(f"[green]Found {len(urls)} comic URLs[/green]")

        start_index = state.processed_urls if resume else 0
        remaining_urls = urls[start_index:]

        # Main scraping loop with rich progress
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            TextColumn("[dim]{task.fields[status]}"),
            console=console,
            refresh_per_second=2,
        ) as progress:
            task = progress.add_task(
                "Scraping",
                total=len(remaining_urls),
                status=f"delay: {self._current_delay:.1f}s | errors: 0"
            )

            scraped_count = 0
            skipped_count = 0

            for i, url in enumerate(remaining_urls):
                if self._stop_requested:
                    state.status = 'stopped'
                    state.paused_at = datetime.utcnow()
                    state.processed_urls = start_index + i
                    self._safe_commit()
                    progress.stop()
                    self._print_summary(scraped_count, skipped_count, i)
                    return

                # Check if already scraped
                existing = self.session.query(Comic).filter_by(page_url=url).first()
                if existing:
                    skipped_count += 1
                    state.processed_urls = start_index + i + 1
                    progress.update(task, advance=1, status=self._status_text(scraped_count, skipped_count))
                    if skipped_count % 100 == 0:
                        self._safe_commit()
                    continue

                # Scrape the page
                success = self._scrape_page_safe(url)
                if success:
                    scraped_count += 1
                else:
                    self._failed_urls.append((url, 1))

                state.processed_urls = start_index + i + 1
                state.last_processed_url = url

                # Commit periodically
                if (scraped_count + skipped_count) % 20 == 0:
                    self._safe_commit()

                progress.update(task, advance=1, status=self._status_text(scraped_count, skipped_count))

                # Adaptive delay
                self._delay()

        # Retry failed URLs
        if self._failed_urls:
            self._retry_failed_urls()

        state.status = 'completed'
        state.completed_at = datetime.utcnow()
        self._safe_commit()

        self._print_summary(scraped_count, skipped_count, len(remaining_urls))

    def _status_text(self, scraped: int, skipped: int) -> str:
        """Generate status text for progress bar."""
        return (
            f"delay: {self._current_delay:.2f}s | "
            f"new: {scraped} | skip: {skipped} | "
            f"err: {self._total_errors} | retry: {self._total_retries}"
        )

    def _print_summary(self, scraped: int, skipped: int, total_processed: int):
        """Print final summary."""
        console.print(f"\n[bold]{'─' * 50}[/bold]")
        console.print(f"[bold green]Scraping summary:[/bold green]")
        console.print(f"  Processed:  {total_processed}")
        console.print(f"  New comics: {scraped}")
        console.print(f"  Skipped:    {skipped} (already in DB)")
        console.print(f"  Errors:     {self._total_errors}")
        console.print(f"  Retries:    {self._total_retries}")
        console.print(f"  Failed:     {len(self._failed_urls)}")
        if self._failed_urls:
            console.print(f"  [yellow]Failed URLs saved for retry[/yellow]")

    # ==================== RETRY FAILED ====================

    def _retry_failed_urls(self):
        """Retry all failed URLs from the main scrape."""
        if not self._failed_urls:
            return

        console.print(f"\n[yellow]Retrying {len(self._failed_urls)} failed URLs...[/yellow]")

        still_failed = []
        recovered = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold yellow]Retrying failed"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Retry", total=len(self._failed_urls))

            for url, prev_retries in self._failed_urls:
                if self._stop_requested:
                    still_failed.append((url, prev_retries))
                    progress.update(task, advance=1)
                    continue

                # Wait longer between retries
                time.sleep(self._current_delay * 2)

                success = self._scrape_page_safe(url)
                if success:
                    recovered += 1
                else:
                    if prev_retries < MAX_RETRIES:
                        still_failed.append((url, prev_retries + 1))
                    else:
                        logger.error(f"Permanently failed after {MAX_RETRIES} retries: {url}")

                progress.update(task, advance=1)

        self._safe_commit()
        self._failed_urls = still_failed

        if recovered:
            console.print(f"[green]  Recovered: {recovered}[/green]")
        if still_failed:
            console.print(f"[red]  Still failed: {len(still_failed)}[/red]")

    # ==================== PAGE SCRAPING ====================

    def _scrape_page_safe(self, url: str) -> bool:
        """Scrape a page with error handling. Returns True on success."""
        try:
            resp = self._fetch_url(url)
            if not resp:
                return False

            data = parse_comic_page(resp.text, url)
            self._save_comic(data, url)
            return True

        except Exception as e:
            error_str = str(e)
            # Handle duplicate URLs gracefully (sitemap can list same URL twice)
            if 'UNIQUE constraint failed' in error_str or 'IntegrityError' in error_str:
                logger.debug(f"Duplicate URL (already in DB): {url}")
                self.session.rollback()
                return True  # Not a real error - comic is already saved

            # Handle session in bad state (PendingRollbackError etc.)
            if 'PendingRollbackError' in error_str or 'rolled back' in error_str:
                self.session.rollback()

            logger.error(f"Error processing {url}: {e}")
            self._on_error()
            return False

    def _save_comic(self, data: dict, url: str):
        """Save parsed comic data to database."""
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

        # Add download links
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

            # NOTE: We intentionally do NOT resolve links during scraping.
            # Resolving hits getcomics.org again (429 risk) and slows scraping 3-5x.
            # Links are resolved on-demand at download time instead.

            comic.download_links.append(link)

        self.session.add(comic)

    # ==================== SITEMAP PARSING ====================

    def _get_all_comic_urls(self) -> List[str]:
        """Fetch sitemap index and extract all comic page URLs."""
        urls = []

        resp = self._fetch_url(self.config.sitemap_url, retries=10)
        if not resp:
            return urls

        try:
            root = ElementTree.fromstring(resp.content)
            ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            sitemap_urls = []
            for sitemap in root.findall('.//sm:sitemap/sm:loc', ns):
                sitemap_urls.append(sitemap.text)

            # Direct URL entries
            for url_entry in root.findall('.//sm:url/sm:loc', ns):
                url = url_entry.text
                if url and self._is_comic_url(url):
                    urls.append(url)

            if sitemap_urls:
                # Filter out non-comic sitemaps (tags, categories, authors)
                comic_sitemaps = [u for u in sitemap_urls if self._is_comic_sitemap(u)]
                skipped_sitemaps = len(sitemap_urls) - len(comic_sitemaps)
                if skipped_sitemaps:
                    console.print(f"[dim]Skipping {skipped_sitemaps} non-comic sitemaps (tags/categories/authors)[/dim]")
                console.print(f"[dim]Fetching {len(comic_sitemaps)} comic sitemaps (patience - rate limits apply)...[/dim]")
                sitemap_urls = comic_sitemaps

            failed_sitemaps = []
            for i, sitemap_url in enumerate(sitemap_urls, 1):
                if self._stop_requested:
                    break

                # Longer delay between sitemap fetches to avoid 429
                time.sleep(max(2.0, self._current_delay))

                # More retries for sitemaps - they're critical and one-time
                sub_urls = self._fetch_sub_sitemap(sitemap_url)
                if sub_urls:
                    urls.extend(sub_urls)
                    console.print(f"  [dim][{i}/{len(sitemap_urls)}] {len(sub_urls)} URLs from {sitemap_url.split('/')[-1]}[/dim]")
                else:
                    failed_sitemaps.append(sitemap_url)
                    console.print(f"  [yellow][{i}/{len(sitemap_urls)}] FAILED: {sitemap_url.split('/')[-1]} (will retry)[/yellow]")

            # Retry failed sitemaps with longer waits
            if failed_sitemaps:
                console.print(f"\n[yellow]Retrying {len(failed_sitemaps)} failed sitemaps with longer delays...[/yellow]")
                for sitemap_url in failed_sitemaps:
                    if self._stop_requested:
                        break
                    time.sleep(10)  # Long wait before retry
                    sub_urls = self._fetch_sub_sitemap(sitemap_url)
                    if sub_urls:
                        urls.extend(sub_urls)
                        console.print(f"  [green]Recovered: {len(sub_urls)} URLs from {sitemap_url.split('/')[-1]}[/green]")
                    else:
                        console.print(f"  [red]Still failed: {sitemap_url.split('/')[-1]}[/red]")

        except ElementTree.ParseError as e:
            logger.error(f"Error parsing sitemap XML: {e}")

        return urls

    def _fetch_sub_sitemap(self, url: str) -> List[str]:
        """Fetch a sub-sitemap and extract comic URLs. Uses extra retries."""
        urls = []
        # Give sitemaps more retries since they're critical one-time fetches
        resp = self._fetch_url(url, retries=6)
        if not resp:
            return urls

        try:
            root = ElementTree.fromstring(resp.content)
            ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            for url_entry in root.findall('.//sm:url/sm:loc', ns):
                page_url = url_entry.text
                if page_url and self._is_comic_url(page_url):
                    urls.append(page_url)
        except ElementTree.ParseError as e:
            logger.error(f"Error parsing sub-sitemap {url}: {e}")

        return urls

    def _is_comic_url(self, url: str) -> bool:
        """Check if URL is a comic page (not a category/tag/page/author)."""
        skip_patterns = [
            '/tag/', '/category/', '/page/',
            '/wp-content/', '/wp-admin/',
            '/feed/', '/comment-page-',
            'getcomics.org/sitemap', '/author/',
        ]
        return not any(pattern in url for pattern in skip_patterns)

    def _is_comic_sitemap(self, url: str) -> bool:
        """Check if a sub-sitemap contains comic posts (not tags/categories/authors)."""
        skip_sitemap_patterns = [
            'post_tag-sitemap',   # tag pages, not comics
            'category-sitemap',   # category pages
            'author-sitemap',     # author pages
        ]
        filename = url.split('/')[-1].lower()
        return not any(pattern in filename for pattern in skip_sitemap_patterns)

    # ==================== INCREMENTAL UPDATE ====================

    def scrape_updates(self):
        """
        Incremental scrape - only new comics since last run.
        Stops after finding consecutive already-known comics.
        """
        console.print("[cyan]Fetching sitemap for updates...[/cyan]")
        urls = self._get_all_comic_urls()

        if not urls:
            console.print("[red]No URLs found![/red]")
            return 0

        new_count = 0
        skipped_streak = 0
        max_skipped_streak = 30

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Checking for new comics"),
            BarColumn(bar_width=30),
            TextColumn("{task.fields[info]}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Update", total=len(urls), info="scanning...")

            for i, url in enumerate(urls):
                if self._stop_requested:
                    break

                existing = self.session.query(Comic).filter_by(page_url=url).first()
                if existing:
                    skipped_streak += 1
                    if skipped_streak >= max_skipped_streak:
                        progress.update(task, info=f"found {new_count} new | hit {max_skipped_streak} known -> done")
                        break
                    progress.update(task, advance=1, info=f"new: {new_count} | known streak: {skipped_streak}")
                    continue

                skipped_streak = 0

                success = self._scrape_page_safe(url)
                if success:
                    new_count += 1
                    if new_count % 10 == 0:
                        self._safe_commit()

                progress.update(task, advance=1, info=f"new: {new_count} | checking...")
                self._delay()

        self._safe_commit()

        if self._failed_urls:
            self._retry_failed_urls()

        console.print(f"\n[bold green]Update complete: {new_count} new comics added[/bold green]")
        return new_count

    # ==================== STATE MANAGEMENT ====================

    def _get_or_create_state(self) -> ScrapeState:
        state = self.session.query(ScrapeState).filter_by(
            sitemap_url=self.config.sitemap_url
        ).first()

        if not state:
            state = ScrapeState(
                sitemap_url=self.config.sitemap_url,
                status='idle'
            )
            self.session.add(state)
            self._safe_commit()

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
