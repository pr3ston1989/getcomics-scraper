"""
Download manager - handles downloading comics with queue, pause/resume, error handling.

Download strategy:
1. For direct links (getcomics /dls/): resolve redirect -> download from final URL
2. If resolved_url is cached and fresh: use it directly
3. If resolved_url is stale/missing: re-resolve from original_url
4. For external links (mega, mediafire): export to link list only (can't auto-download)

Error handling:
- Disk full: pause all downloads, notify user
- Network errors: retry with exponential backoff (max 3 retries)
- Broken links: mark as failed, try next available link for same comic
"""
import os
import time
import shutil
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Optional
from queue import Queue, Empty
from urllib.parse import unquote

import requests
from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import Comic, DownloadLink, DownloadQueue, Tag, get_session, init_db
from .config import Config
from .link_resolver import LinkResolver

logger = logging.getLogger(__name__)

# How old a resolved URL can be before we re-resolve (hours)
RESOLVED_URL_MAX_AGE_HOURS = 6


class DownloadError(Exception):
    """Base download error."""
    pass


class DiskFullError(DownloadError):
    """Raised when disk is full."""
    pass


class LinkExpiredError(DownloadError):
    """Raised when a resolved link has expired."""
    pass


class DownloadManager:
    """Manages comic downloads with persistent queue, pause/resume, and error handling."""

    def __init__(self, config: Config):
        self.config = config
        self.session = get_session(config.database_url)
        self.resolver = LinkResolver(config)
        self._stop_requested = False
        self._pause_requested = False
        self._workers = []
        self._lock = threading.Lock()
        self._error_event = threading.Event()

        # Ensure download directory exists
        os.makedirs(config.download_dir, exist_ok=True)
        init_db(config.database_url)

    # ==================== QUEUE MANAGEMENT ====================

    def add_by_series(self, series_name: str, host_filter: Optional[str] = None) -> int:
        """Add all comics from a series to download queue."""
        comics = self.session.query(Comic).filter(
            Comic.series.ilike(f'%{series_name}%'),
            Comic.is_downloaded == False
        ).all()
        return self._enqueue_comics(comics, host_filter)

    def add_by_tag(self, tag_name: str, host_filter: Optional[str] = None) -> int:
        """Add all comics with a specific tag to download queue."""
        comics = self.session.query(Comic).filter(
            Comic.tags.any(name=tag_name),
            Comic.is_downloaded == False
        ).all()
        return self._enqueue_comics(comics, host_filter)

    def add_by_search(self, query: str, host_filter: Optional[str] = None) -> int:
        """Add comics matching search query to download queue."""
        comics = self.session.query(Comic).filter(
            Comic.title.ilike(f'%{query}%'),
            Comic.is_downloaded == False
        ).all()
        return self._enqueue_comics(comics, host_filter)

    def add_all_not_downloaded(self, host_filter: Optional[str] = None) -> int:
        """Add ALL comics that haven't been downloaded yet to the queue."""
        comics = self.session.query(Comic).filter(
            Comic.is_downloaded == False
        ).all()
        return self._enqueue_comics(comics, host_filter)

    def add_comic(self, comic_id: int, host_filter: Optional[str] = None) -> bool:
        """Add a single comic to download queue."""
        comic = self.session.query(Comic).get(comic_id)
        if comic:
            return self._enqueue_single(comic, host_filter)
        return False

    def _enqueue_comics(self, comics: List[Comic], host_filter: Optional[str] = None) -> int:
        """Enqueue a list of comics."""
        count = 0
        for comic in comics:
            # Skip if already in queue
            existing = self.session.query(DownloadQueue).filter(
                DownloadQueue.comic_id == comic.id,
                DownloadQueue.status.in_(['pending', 'downloading', 'paused'])
            ).first()
            if existing:
                continue

            if self._enqueue_single(comic, host_filter):
                count += 1

        self.session.commit()
        return count

    def _enqueue_single(self, comic: Comic, host_filter: Optional[str] = None) -> bool:
        """Add one comic's best download link to the persistent queue."""
        link = self._pick_best_link(comic, host_filter)
        if not link:
            logger.warning(f"No downloadable links for: {comic.title}")
            return False

        queue_item = DownloadQueue(
            comic_id=comic.id,
            link_id=link.id,
            status='pending'
        )
        self.session.add(queue_item)
        return True

    def _pick_best_link(self, comic: Comic, host_filter: Optional[str] = None) -> Optional[DownloadLink]:
        """Pick the best download link for a comic."""
        links = comic.download_links

        if host_filter:
            filtered = [l for l in links if l.host == host_filter]
            if filtered:
                links = filtered

        # Priority: direct links with resolved URL > direct links > any
        for link in links:
            if link.is_direct and link.resolved_url:
                return link
        for link in links:
            if link.is_direct:
                return link
        for link in links:
            if not link.is_external:
                return link

        return links[0] if links else None

    # ==================== DOWNLOAD CONTROL ====================

    def start(self):
        """Start download workers processing the queue."""
        self._stop_requested = False
        self._pause_requested = False
        self._error_event.clear()

        # Resume any items that were 'downloading' (interrupted)
        interrupted = self.session.query(DownloadQueue).filter(
            DownloadQueue.status == 'downloading'
        ).all()
        for item in interrupted:
            item.status = 'pending'
        self.session.commit()

        for i in range(self.config.max_concurrent_downloads):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f'downloader-{i}',
                daemon=True
            )
            worker.start()
            self._workers.append(worker)

        logger.info(f"Started {self.config.max_concurrent_downloads} download workers")

    def stop(self):
        """Stop all downloads gracefully."""
        self._stop_requested = True
        for worker in self._workers:
            worker.join(timeout=15)
        self._workers.clear()

        # Mark active downloads as paused
        active = self.session.query(DownloadQueue).filter(
            DownloadQueue.status == 'downloading'
        ).all()
        for item in active:
            item.status = 'paused'
        self.session.commit()

        logger.info("Download manager stopped")

    def pause(self):
        """Pause downloads (can be resumed)."""
        self._pause_requested = True
        logger.info("Downloads pausing after current files complete...")

    def resume(self):
        """Resume paused downloads."""
        self._pause_requested = False

        # Requeue paused items
        paused = self.session.query(DownloadQueue).filter(
            DownloadQueue.status == 'paused'
        ).all()
        for item in paused:
            item.status = 'pending'
        self.session.commit()

        logger.info("Downloads resumed")

    def retry_failed(self):
        """Retry all failed downloads."""
        failed = self.session.query(DownloadQueue).filter(
            DownloadQueue.status == 'failed'
        ).all()
        for item in failed:
            item.status = 'pending'
            item.retry_count += 1
            item.error_message = None
        self.session.commit()
        logger.info(f"Requeued {len(failed)} failed downloads")
        return len(failed)

    # ==================== STATUS ====================

    def get_status(self) -> dict:
        """Get download manager status."""
        pending = self.session.query(DownloadQueue).filter(DownloadQueue.status == 'pending').count()
        downloading = self.session.query(DownloadQueue).filter(DownloadQueue.status == 'downloading').count()
        completed = self.session.query(DownloadQueue).filter(DownloadQueue.status == 'completed').count()
        failed = self.session.query(DownloadQueue).filter(DownloadQueue.status == 'failed').count()
        paused = self.session.query(DownloadQueue).filter(DownloadQueue.status == 'paused').count()

        # Disk space
        disk_usage = shutil.disk_usage(self.config.download_dir)
        free_gb = disk_usage.free / (1024 ** 3)

        return {
            'pending': pending,
            'downloading': downloading,
            'completed': completed,
            'failed': failed,
            'paused': paused,
            'total': pending + downloading + completed + failed + paused,
            'is_paused': self._pause_requested,
            'is_stopped': self._stop_requested,
            'disk_free_gb': round(free_gb, 2),
        }

    # ==================== WORKER ====================

    def _worker_loop(self):
        """Worker loop processing download queue."""
        while not self._stop_requested:
            if self._pause_requested:
                time.sleep(1)
                continue

            if self._error_event.is_set():
                time.sleep(2)
                continue

            # Get next pending item from DB queue
            with self._lock:
                item = self.session.query(DownloadQueue).filter(
                    DownloadQueue.status == 'pending'
                ).first()
                if not item:
                    time.sleep(2)
                    continue
                item.status = 'downloading'
                item.started_at = datetime.utcnow()
                self.session.commit()

            try:
                self._download_item(item)
                item.status = 'completed'
                item.completed_at = datetime.utcnow()

                # Mark comic as downloaded
                comic = self.session.query(Comic).get(item.comic_id)
                if comic:
                    comic.is_downloaded = True
                    comic.download_path = item.filepath
                    comic.downloaded_at = datetime.utcnow()

                self.session.commit()

            except DiskFullError as e:
                logger.error(f"DISK FULL! Pausing all downloads. {e}")
                item.status = 'paused'
                item.error_message = str(e)
                self.session.commit()
                self._error_event.set()
                self._pause_requested = True

            except LinkExpiredError as e:
                logger.warning(f"Link expired for {item.comic.title}, re-resolving...")
                item.status = 'pending'
                item.error_message = str(e)
                # Clear resolved URL so it gets re-resolved
                if item.link:
                    item.link.resolved_url = None
                    item.link.resolved_at = None
                self.session.commit()

            except DownloadError as e:
                item.retry_count += 1
                if item.retry_count >= 3:
                    item.status = 'failed'
                    item.error_message = str(e)
                    logger.error(f"Download permanently failed: {item.comic.title} - {e}")
                else:
                    item.status = 'pending'
                    item.error_message = f"Retry {item.retry_count}/3: {e}"
                    logger.warning(f"Download retry {item.retry_count}/3: {item.comic.title}")
                    time.sleep(2 ** item.retry_count)  # Exponential backoff
                self.session.commit()

            except Exception as e:
                item.status = 'failed'
                item.error_message = f"Unexpected error: {e}"
                self.session.commit()
                logger.error(f"Unexpected download error: {e}", exc_info=True)

    def _download_item(self, item: DownloadQueue):
        """Download a single queue item."""
        link = item.link
        if not link:
            raise DownloadError("No link associated with queue item")

        # Check disk space before downloading
        self._check_disk_space()

        # Get the comic page URL to use as Referer (needed for /dls/ links)
        comic = self.session.query(Comic).get(item.comic_id)
        source_page_url = comic.page_url if comic else None

        # Determine the URL to download from
        download_url = self._get_download_url(link, source_page_url=source_page_url)
        if not download_url:
            raise DownloadError(f"Could not resolve download URL for: {link.original_url[:80]}")

        # Start streaming download
        resp = self.resolver.resolve_for_download(download_url, source_page_url=source_page_url)
        if not resp:
            raise DownloadError(f"Failed to connect to: {download_url[:80]}")

        try:
            # Check for expired/moved links
            if resp.status_code in (403, 410, 404):
                raise LinkExpiredError(f"HTTP {resp.status_code} - link may be expired")

            # Get filename and prepare path
            filename = self._determine_filename(resp, item.comic)
            filepath = os.path.join(self.config.download_dir, filename)

            # Avoid overwriting
            if os.path.exists(filepath):
                base, ext = os.path.splitext(filepath)
                filepath = f"{base}_{item.id}{ext}"

            # Download with progress tracking
            total_size = int(resp.headers.get('content-length', 0))
            downloaded = 0

            with open(filepath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if self._stop_requested:
                        f.close()
                        os.remove(filepath)
                        raise DownloadError("Download stopped by user")

                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        item.progress = downloaded / total_size * 100

                    # Periodic disk check (every 10MB)
                    if downloaded % (10 * 1024 * 1024) == 0:
                        self._check_disk_space()

            # Update resolved URL in link (cache for future)
            if resp.url != link.original_url:
                link.resolved_url = resp.url
                link.resolved_at = datetime.utcnow()

            item.filepath = filepath
            item.progress = 100.0
            logger.info(f"Downloaded: {filename} ({self._format_size(downloaded)})")

        finally:
            resp.close()

    def _get_download_url(self, link: DownloadLink, source_page_url: Optional[str] = None) -> Optional[str]:
        """Get the best URL to download from."""
        # If we have a fresh resolved URL, use it
        if link.resolved_url and link.resolved_at:
            age = datetime.utcnow() - link.resolved_at
            if age < timedelta(hours=RESOLVED_URL_MAX_AGE_HOURS):
                return link.resolved_url

        # Re-resolve from original URL
        resolved, _ = self.resolver.resolve(link.original_url, source_page_url=source_page_url)
        if resolved:
            link.resolved_url = resolved
            link.resolved_at = datetime.utcnow()
            return resolved

        # Fallback to original URL (let requests handle redirect)
        return link.original_url

    def _check_disk_space(self, min_free_mb: int = 500):
        """Check if there's enough disk space. Raises DiskFullError if not."""
        try:
            disk_usage = shutil.disk_usage(self.config.download_dir)
            free_mb = disk_usage.free / (1024 * 1024)
            if free_mb < min_free_mb:
                raise DiskFullError(
                    f"Disk space critically low: {free_mb:.0f}MB free "
                    f"(minimum: {min_free_mb}MB)"
                )
        except OSError as e:
            logger.warning(f"Could not check disk space: {e}")

    def _determine_filename(self, resp: requests.Response, comic: Comic) -> str:
        """Determine filename for the downloaded file."""
        # Try Content-Disposition header
        cd = resp.headers.get('content-disposition', '')
        if 'filename=' in cd:
            parts = cd.split('filename=')
            if len(parts) > 1:
                filename = parts[1].strip('"\'').strip()
                if filename:
                    return self._sanitize_filename(filename)

        # Try from final URL
        url_path = resp.url.split('?')[0]
        if '/' in url_path:
            filename = unquote(url_path.split('/')[-1])
            if '.' in filename and len(filename) > 3:
                return self._sanitize_filename(filename)

        # Generate from comic title
        safe_title = self._sanitize_filename(comic.title)
        # Guess extension from content-type
        ct = resp.headers.get('content-type', '')
        ext = '.cbr'
        if 'zip' in ct:
            ext = '.zip'
        elif 'rar' in ct:
            ext = '.cbr'
        elif 'pdf' in ct:
            ext = '.pdf'

        return f"{safe_title}{ext}"

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize filename for filesystem."""
        # Remove/replace invalid characters
        invalid = '<>:"/\\|?*'
        for char in invalid:
            name = name.replace(char, '_')
        # Limit length
        if len(name) > 200:
            base, ext = os.path.splitext(name)
            name = base[:200 - len(ext)] + ext
        return name.strip('. ')

    @staticmethod
    def _format_size(bytes_count: int) -> str:
        """Format bytes to human-readable."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_count < 1024:
                return f"{bytes_count:.1f} {unit}"
            bytes_count /= 1024
        return f"{bytes_count:.1f} TB"


# ==================== LINK EXPORT (for JDownloader etc.) ====================

def generate_link_list(database_url: str, host: Optional[str] = None,
                       series: Optional[str] = None, tag: Optional[str] = None,
                       search: Optional[str] = None,
                       use_resolved: bool = False) -> List[str]:
    """
    Generate a list of download links filtered by host/series/tag/search.
    Useful for exporting to JDownloader or similar tools.

    Args:
        database_url: Database connection string
        host: Filter by host (e.g. 'mega', 'mediafire', 'getcomics_direct')
        series: Filter by series name (partial match)
        tag: Filter by tag name
        search: Search in comic titles
        use_resolved: If True, export resolved URLs instead of original
    """
    session = get_session(database_url)

    query = session.query(DownloadLink).join(Comic)

    if host:
        query = query.filter(DownloadLink.host == host)
    if series:
        query = query.filter(Comic.series.ilike(f'%{series}%'))
    if tag:
        query = query.filter(Comic.tags.any(name=tag))
    if search:
        query = query.filter(Comic.title.ilike(f'%{search}%'))

    links = query.all()

    result = []
    for link in links:
        if use_resolved and link.resolved_url:
            result.append(link.resolved_url)
        else:
            result.append(link.original_url)

    return result
