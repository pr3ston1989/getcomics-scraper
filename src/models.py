"""Database models for GetComics scraper."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float,
    ForeignKey, Table, create_engine, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

Base = declarative_base()

# Many-to-many relationship between comics and tags
comic_tags = Table(
    'comic_tags', Base.metadata,
    Column('comic_id', Integer, ForeignKey('comics.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)


class Tag(Base):
    __tablename__ = 'tags'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False, index=True)

    comics = relationship('Comic', secondary=comic_tags, back_populates='tags')

    def __repr__(self):
        return f"<Tag(name='{self.name}')>"


class DownloadLink(Base):
    """
    Stores all download links found on a comic page.

    Saves both the original URL from the page (which may be an obfuscated redirect)
    and the resolved final URL (actual file location). This way we have a fallback
    if one expires - the /dls/ redirect is usually permanent while the resolved URL
    may have an expiry token.
    """
    __tablename__ = 'download_links'

    id = Column(Integer, primary_key=True)
    comic_id = Column(Integer, ForeignKey('comics.id'), nullable=False)

    # Original URL as found on the page (e.g. getcomics.org/dls/... or mega.nz/...)
    original_url = Column(Text, nullable=False)

    # Resolved/final URL after following redirects (e.g. fs1.comicfiles.ru/...)
    # May expire - re-resolve from original_url if needed
    resolved_url = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    # Metadata
    host = Column(String(255), nullable=True, index=True)  # mega, mediafire, getcomics_direct, etc.
    label = Column(String(255), nullable=True)  # button/link text from page
    is_direct = Column(Boolean, default=False)  # getcomics /dls/ links that redirect to file
    is_external = Column(Boolean, default=False)  # mega, mediafire, google drive, etc.
    added_at = Column(DateTime, default=datetime.utcnow)

    comic = relationship('Comic', back_populates='download_links')

    def __repr__(self):
        return f"<DownloadLink(host='{self.host}', original='{self.original_url[:50]}...')>"


class Comic(Base):
    __tablename__ = 'comics'

    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False, index=True)
    page_url = Column(Text, unique=True, nullable=False)

    # Parsed metadata
    language = Column(String(50), nullable=True)
    image_format = Column(String(50), nullable=True)
    year = Column(String(50), nullable=True)
    size = Column(String(50), nullable=True)

    # Series info
    series = Column(String(500), nullable=True, index=True)
    issue_number = Column(String(50), nullable=True)

    # Raw description
    description = Column(Text, nullable=True)

    # Timestamps
    scraped_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(String(100), nullable=True)

    # Download status
    is_downloaded = Column(Boolean, default=False)
    download_path = Column(Text, nullable=True)
    downloaded_at = Column(DateTime, nullable=True)

    # Relationships
    tags = relationship('Tag', secondary=comic_tags, back_populates='comics')
    download_links = relationship('DownloadLink', back_populates='comic', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Comic(title='{self.title[:50]}')>"


class ScrapeState(Base):
    """Tracks scraping progress for pause/resume."""
    __tablename__ = 'scrape_state'

    id = Column(Integer, primary_key=True)
    sitemap_url = Column(Text, nullable=False)
    last_processed_url = Column(Text, nullable=True)
    total_urls = Column(Integer, default=0)
    processed_urls = Column(Integer, default=0)
    status = Column(String(50), default='idle')  # idle, running, paused, completed, stopped
    started_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # For incremental updates - last comic publish date we saw
    last_seen_date = Column(String(100), nullable=True)


class DownloadQueue(Base):
    """Persistent download queue with status tracking."""
    __tablename__ = 'download_queue'

    id = Column(Integer, primary_key=True)
    comic_id = Column(Integer, ForeignKey('comics.id'), nullable=False)
    link_id = Column(Integer, ForeignKey('download_links.id'), nullable=True)
    status = Column(String(50), default='pending')  # pending, downloading, completed, failed, paused
    progress = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    filepath = Column(Text, nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    comic = relationship('Comic')
    link = relationship('DownloadLink')


def get_engine(database_url='sqlite:///getcomics.db'):
    return create_engine(database_url, echo=False)


def get_session(database_url='sqlite:///getcomics.db'):
    engine = get_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()


def init_db(database_url='sqlite:///getcomics.db'):
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    return engine
