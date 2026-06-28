from setuptools import setup, find_packages

setup(
    name='getcomics-scraper',
    version='1.0.0',
    description='GetComics.org scraper and download manager',
    packages=find_packages(),
    python_requires='>=3.9',
    install_requires=[
        'requests>=2.31.0',
        'beautifulsoup4>=4.12.2',
        'lxml>=4.9.3',
        'SQLAlchemy>=1.4.49,<2.0',
        'aiohttp>=3.8.6',
        'rich>=13.7.0',
        'click>=8.1.7',
        'python-dotenv>=1.0.0',
    ],
    entry_points={
        'console_scripts': [
            'getcomics=src.cli:main',
        ],
    },
)
