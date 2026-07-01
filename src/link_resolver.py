"""
Link resolver - handles getcomics redirect links and resolves actual download URLs.

GetComics uses obfuscated links like:
    https://getcomics.org/dls/GReIX6dXa7V6gOa261/...

These are server-side redirects (301/302) that point to actual file URLs like:
    https://fs1.comicfiles.ru/2026.01.14/The%20Shadow-In%20the%20Coils...

Strategy:
- /dls/ links: Follow redirect to get the real URL, then download from there
- External links (mega, mediafire): Save as-is for export to JDownloader
- The /dls/ redirect is persistent (tied to the comic, not session-based)
- The final resolved URL may have an expiry token, so we resolve at download time
"""
import logging
from typing import Optional, Tuple
from datetime import datetime

import requests

from .config import Config

logger = logging.getLogger(__name__)


class LinkResolver:
    """Resolves getcomics redirect links to actual download URLs."""

    def __init__(self, config: Config):
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': config.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    def resolve(self, url: str, source_page_url: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolve a download link to its final URL.

        source_page_url: the comic page URL to use as Referer header.
        Returns:
            Tuple of (resolved_url, filename) or (None, None) on failure.
        """
        if self._is_external(url):
            # External links (mega, mediafire) can't be resolved - return as-is
            return url, None

        # Build Referer: prefer the actual comic page, fall back to getcomics root
        referer = source_page_url or 'https://getcomics.org/'
        extra_headers = {'Referer': referer}

        # Visit the comic page first to obtain session cookies.
        # GetComics ties /dls/ tokens to a browser session - without cookies = 403.
        if source_page_url and 'getcomics.org/dls/' in url:
            logger.debug(f"Visiting source page to obtain session cookies: {source_page_url}")
            try:
                self._session.get(source_page_url, timeout=20)
            except requests.RequestException:
                pass  # Best-effort; proceed regardless

        try:
            # Use HEAD request first to avoid downloading the file
            resp = self._session.head(
                url,
                allow_redirects=True,
                timeout=30,
                headers=extra_headers,
            )

            if resp.status_code == 200:
                final_url = resp.url
                filename = self._extract_filename_from_url(final_url)
                logger.info(f"Resolved: {url[:60]}... -> {final_url[:80]}...")
                return final_url, filename

            # Some servers don't support HEAD, try GET with stream
            resp = self._session.get(
                url,
                allow_redirects=True,
                stream=True,
                timeout=30,
                headers=extra_headers,
            )
            resp.close()  # Don't download the body

            if resp.status_code == 200:
                final_url = resp.url
                filename = self._extract_filename(resp)
                return final_url, filename

            logger.warning(f"Could not resolve {url}: HTTP {resp.status_code}")
            return None, None

        except requests.RequestException as e:
            logger.error(f"Error resolving {url}: {e}")
            return None, None

    def resolve_for_download(self, url: str, source_page_url: Optional[str] = None) -> Optional[requests.Response]:
        """
        Resolve and start downloading - returns streaming response.
        Caller is responsible for closing the response.

        source_page_url: the comic page URL to visit first (sets cookies + Referer).
        """
        try:
            # Visit the comic page first to obtain session cookies, then download.
            # GetComics ties /dls/ tokens to a browser session - without cookies = 403.
            if source_page_url and 'getcomics.org/dls/' in url:
                logger.debug(f"Visiting source page to obtain session cookies: {source_page_url}")
                try:
                    self._session.get(source_page_url, timeout=20)
                except requests.RequestException:
                    pass  # Best-effort; proceed regardless

            headers = {}
            if source_page_url:
                headers['Referer'] = source_page_url
            elif 'getcomics.org/dls/' in url:
                headers['Referer'] = 'https://getcomics.org/'

            resp = self._session.get(
                url,
                allow_redirects=True,
                stream=True,
                timeout=60,
                headers=headers,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logger.error(f"Error starting download from {url}: {e}")
            return None

    def check_link_alive(self, url: str) -> bool:
        """Check if a link is still alive (returns 200 on HEAD)."""
        try:
            resp = self._session.head(url, allow_redirects=True, timeout=15)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _is_external(self, url: str) -> bool:
        """Check if URL is an external service (mega, mediafire, etc.)."""
        external_hosts = [
            'mega.nz', 'mega.co.nz',
            'mediafire.com',
            'drive.google.com',
            'pixeldrain.com',
            'workupload.com',
            'uploadhaven.com',
        ]
        return any(host in url.lower() for host in external_hosts)

    def _extract_filename(self, resp: requests.Response) -> Optional[str]:
        """Extract filename from response headers or URL."""
        # Try Content-Disposition
        cd = resp.headers.get('content-disposition', '')
        if 'filename=' in cd:
            parts = cd.split('filename=')
            if len(parts) > 1:
                return parts[1].strip('"\'').strip()

        return self._extract_filename_from_url(resp.url)

    def _extract_filename_from_url(self, url: str) -> Optional[str]:
        """Extract filename from URL path."""
        from urllib.parse import unquote, urlparse
        path = urlparse(url).path
        if '/' in path:
            filename = unquote(path.split('/')[-1])
            if '.' in filename:
                return filename
        return None
