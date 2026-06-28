"""Parser for GetComics comic pages - extracts metadata, tags, and download links."""
import re
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup


def parse_comic_page(html: str, page_url: str) -> Dict:
    """Parse a single comic page and extract all relevant info."""
    soup = BeautifulSoup(html, 'lxml')

    title = _extract_title(soup)
    metadata = _extract_metadata(soup)
    tags = _extract_tags(soup)
    download_links = _extract_download_links(soup)
    description = _extract_description(soup)
    series, issue = _parse_series_from_title(title)
    published_at = _extract_publish_date(soup)

    return {
        'title': title,
        'page_url': page_url,
        'language': metadata.get('language'),
        'image_format': metadata.get('image_format'),
        'year': metadata.get('year'),
        'size': metadata.get('size'),
        'series': series,
        'issue_number': issue,
        'description': description,
        'tags': tags,
        'download_links': download_links,
        'published_at': published_at,
    }


def _extract_title(soup: BeautifulSoup) -> str:
    """Extract comic title from page."""
    title_el = soup.find('h1', class_='post-title')
    if title_el:
        return title_el.get_text(strip=True)
    title_el = soup.find('title')
    if title_el:
        return title_el.get_text(strip=True).split('|')[0].strip()
    return 'Unknown Title'


def _extract_metadata(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """
    Parse metadata block like:
    Language : English | Image Format : JPG | Year : 1993-1994 | Size : 61 MB
    """
    metadata = {
        'language': None,
        'image_format': None,
        'year': None,
        'size': None,
    }

    # Look for the metadata in post content
    post_content = soup.find('div', class_='post-content') or soup.find('article')
    if not post_content:
        return metadata

    text = post_content.get_text()

    # Pattern: Key : Value | Key : Value ...
    # Try to find the metadata line
    patterns = {
        'language': r'Language\s*:\s*([^||\n]+)',
        'image_format': r'(?:Image\s*)?Format\s*:\s*([^||\n]+)',
        'year': r'Year\s*:\s*([^||\n]+)',
        'size': r'Size\s*:\s*([^||\n]+)',
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            metadata[key] = match.group(1).strip()

    return metadata


def _extract_tags(soup: BeautifulSoup) -> List[str]:
    """Extract tags/categories from the page."""
    tags = []

    # Look for tag links
    tag_elements = soup.find_all('a', rel='tag')
    for tag_el in tag_elements:
        tag_name = tag_el.get_text(strip=True)
        if tag_name:
            tags.append(tag_name)

    # Also check category spans
    cat_elements = soup.find_all('span', class_='cat-links')
    for cat_el in cat_elements:
        for a_tag in cat_el.find_all('a'):
            cat_name = a_tag.get_text(strip=True)
            if cat_name and cat_name not in tags:
                tags.append(cat_name)

    return tags


def _extract_download_links(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Extract all download links from the page."""
    links = []

    # GetComics uses various link patterns
    # Look for download buttons/links in the content area
    post_content = soup.find('div', class_='post-content') or soup.find('article')
    if not post_content:
        return links

    # Pattern 1: Links with class containing 'download' or in download sections
    download_sections = post_content.find_all(['a'], href=True)

    for a_tag in download_sections:
        href = a_tag.get('href', '').strip()
        if not href or href == '#':
            continue

        # Skip navigation/social links
        skip_patterns = ['twitter.com', 'facebook.com', 'pinterest.com',
                         'reddit.com', '#comment', 'getcomics.org/tag/',
                         'getcomics.org/category/', 'javascript:']
        if any(skip in href.lower() for skip in skip_patterns):
            continue

        label = a_tag.get_text(strip=True)
        host = _identify_host(href, label)

        # Only include actual download links
        if _is_download_link(href, label, a_tag):
            links.append({
                'url': href,
                'host': host,
                'label': label,
                'is_direct': _is_direct_link(href),
            })

    return links


def _is_download_link(href: str, label: str, a_tag) -> bool:
    """Determine if a link is likely a download link."""
    # Check URL patterns
    download_url_patterns = [
        'getcomics.org/dls/',
        'comicfiles.ru',
        'mega.nz', 'mega.co.nz',
        'mediafire.com',
        'zippyshare.com',
        'uploadhaven.com',
        'userscloud.com',
        'drive.google.com',
        'dropapk.to',
        'cloud.mail.ru',
        'workupload.com',
        'racaty.net',
        'pixeldrain.com',
    ]
    if any(pattern in href.lower() for pattern in download_url_patterns):
        return True

    # Check label/button text
    download_labels = ['download', 'link', 'server', 'mirror']
    label_lower = label.lower()
    if any(dl in label_lower for dl in download_labels):
        return True

    # Check for download button classes
    classes = a_tag.get('class', [])
    if isinstance(classes, list):
        class_str = ' '.join(classes).lower()
        if 'download' in class_str or 'btn' in class_str:
            return True

    return False


def _identify_host(url: str, label: str) -> str:
    """Identify the hosting service from URL or label."""
    host_patterns = {
        'getcomics_main': ['getcomics.org/dls/'],
        'comicfiles': ['comicfiles.ru'],
        'mega': ['mega.nz', 'mega.co.nz'],
        'mediafire': ['mediafire.com'],
        'zippyshare': ['zippyshare.com'],
        'uploadhaven': ['uploadhaven.com'],
        'google_drive': ['drive.google.com'],
        'pixeldrain': ['pixeldrain.com'],
        'workupload': ['workupload.com'],
    }

    url_lower = url.lower()
    for host, patterns in host_patterns.items():
        for pattern in patterns:
            if pattern in url_lower:
                return host

    # Try from label
    label_lower = label.lower()
    for host, _ in host_patterns.items():
        if host.replace('_', ' ') in label_lower or host.replace('_', '') in label_lower:
            return host

    return 'unknown'


def _is_direct_link(url: str) -> bool:
    """Check if the URL is a direct download link (vs redirect/landing page)."""
    direct_patterns = ['.cbr', '.cbz', '.zip', '.rar', '.pdf', '.7z']
    url_lower = url.lower().split('?')[0]
    return any(url_lower.endswith(ext) for ext in direct_patterns)


def _extract_description(soup: BeautifulSoup) -> Optional[str]:
    """Extract the text description of the comic."""
    post_content = soup.find('div', class_='post-content') or soup.find('article')
    if not post_content:
        return None

    # Get text paragraphs before download links
    paragraphs = []
    for p in post_content.find_all('p'):
        text = p.get_text(strip=True)
        if text and len(text) > 20:
            # Stop at download section
            if 'download' in text.lower() and ('link' in text.lower() or 'now' in text.lower()):
                break
            paragraphs.append(text)

    return '\n'.join(paragraphs) if paragraphs else None


def _parse_series_from_title(title: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse series name and issue number from title.
    Examples:
        'The Shadow - In the Coils of Leviathan #1 - 4' -> ('The Shadow - In the Coils of Leviathan', '1-4')
        'Batman Vol. 3 #125' -> ('Batman Vol. 3', '125')
        'X-Men Annual 2022' -> ('X-Men Annual', None)
    """
    # Pattern: Title #Number or Title #Number - Number
    match = re.match(r'^(.+?)\s*#(\d+(?:\s*[-–]\s*\d+)?)\s*$', title)
    if match:
        series = match.group(1).strip()
        issue = match.group(2).strip().replace('–', '-')
        return series, issue

    # Pattern: Title (Year) or similar - just return the title as series
    # Strip common suffixes
    clean_title = re.sub(r'\s*\(\d{4}(?:-\d{4})?\)\s*$', '', title)
    clean_title = re.sub(r'\s*[-–]\s*(?:Complete|Full|Annual).*$', '', clean_title, flags=re.IGNORECASE)

    return clean_title.strip() if clean_title.strip() != title.strip() else title, None


def _extract_publish_date(soup: BeautifulSoup) -> Optional[str]:
    """Extract the publish date from the page."""
    # Look for time element
    time_el = soup.find('time', class_='entry-date')
    if time_el:
        return time_el.get('datetime')

    # Alternative: look for date in meta
    meta_date = soup.find('meta', property='article:published_time')
    if meta_date:
        return meta_date.get('content')

    return None
