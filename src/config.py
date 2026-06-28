"""Configuration management."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment or defaults."""

    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL', 'sqlite:///getcomics.db')
        self.sitemap_url = os.getenv('SITEMAP_URL', 'https://getcomics.org/sitemap_index.xml')

        # Scraper rate limiting
        self.scrape_delay_min = float(os.getenv('SCRAPE_DELAY_MIN', '2.0'))
        self.scrape_delay_max = float(os.getenv('SCRAPE_DELAY_MAX', '5.0'))

        # Download settings
        self.max_concurrent_downloads = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '3'))
        self.download_dir = os.getenv('DOWNLOAD_DIR', './downloads')

        # User agent
        self.user_agent = os.getenv(
            'USER_AGENT',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

    def set_speed(self, delay_min: float, delay_max: float):
        """Update scraping speed."""
        self.scrape_delay_min = delay_min
        self.scrape_delay_max = delay_max
