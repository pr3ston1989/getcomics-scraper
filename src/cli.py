"""CLI interface for GetComics scraper and download manager."""
import logging
import sys
import time

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

from .config import Config
from .models import Comic, Tag, DownloadLink, DownloadQueue, get_session, init_db
from .scraper import Scraper
from .downloader import DownloadManager, generate_link_list

console = Console()


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('scraper.log'),
        ]
    )


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.pass_context
def cli(ctx, verbose):
    """GetComics Scraper & Download Manager

    Two main modes:
      - scrape: Build/update the comics database
      - download: Search, browse, and download comics
    """
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj['config'] = Config()


# ═══════════════════════════════════════════════════════════════════
# MODE 1: SCRAPER
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def scrape():
    """[MODE 1] Scrape comics database from getcomics.org"""
    pass


@scrape.command()
@click.option('--resume/--no-resume', default=True, help='Resume from last position')
@click.pass_context
def full(ctx, resume):
    """Full scrape of the entire sitemap (with pause/resume support)."""
    config = ctx.obj['config']
    scraper = Scraper(config)

    console.print("[bold green]Starting full scrape...[/bold green]")
    console.print(f"  Sitemap: {config.sitemap_url}")
    console.print(f"  Delay: {config.scrape_delay_min}-{config.scrape_delay_max}s")
    console.print(f"  [dim]Press Ctrl+C to stop gracefully (position saved)[/dim]\n")

    scraper.scrape_sitemap(resume=resume)

    progress = scraper.get_progress()
    console.print(f"\n[bold]Status:[/bold] {progress['status']}")
    console.print(f"[bold]Processed:[/bold] {progress['processed']}/{progress['total']}")
    console.print(f"[bold]Comics in DB:[/bold] {progress['total_comics_in_db']}")


@scrape.command()
@click.pass_context
def update(ctx):
    """Incremental scrape - only fetch new comics since last run."""
    config = ctx.obj['config']
    scraper = Scraper(config)

    console.print("[bold green]Checking for new comics...[/bold green]")
    console.print(f"  [dim]Press Ctrl+C to stop[/dim]\n")

    new_count = scraper.scrape_updates()
    console.print(f"\n[bold green]Done![/bold green] Added {new_count} new comics to database.")


@scrape.command()
@click.option('--delay-min', type=float, help='Minimum delay between requests (seconds)')
@click.option('--delay-max', type=float, help='Maximum delay between requests (seconds)')
@click.pass_context
def speed(ctx, delay_min, delay_max):
    """Set scraping speed (delay between requests)."""
    config = ctx.obj['config']
    if delay_min is not None:
        config.scrape_delay_min = delay_min
    if delay_max is not None:
        config.scrape_delay_max = delay_max
    console.print(f"Scrape delay: {config.scrape_delay_min}-{config.scrape_delay_max}s")


@scrape.command()
@click.pass_context
def status(ctx):
    """Show scraping progress and database stats."""
    config = ctx.obj['config']
    scraper = Scraper(config)
    progress = scraper.get_progress()

    table = Table(title="Scraper Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Status", progress['status'])
    table.add_row("Processed", f"{progress['processed']}/{progress['total']}")
    table.add_row("Progress", f"{progress['percent']:.1f}%")
    table.add_row("Comics in DB", str(progress['total_comics_in_db']))
    table.add_row("Links in DB", str(progress['total_links_in_db']))
    table.add_row("Started", str(progress['started_at'] or 'N/A'))

    console.print(table)


# ═══════════════════════════════════════════════════════════════════
# MODE 2: DOWNLOAD
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def download():
    """[MODE 2] Search, browse, and download comics."""
    pass


@download.command()
@click.pass_context
def interactive(ctx):
    """Interactive download mode - search, browse, select, download."""
    config = ctx.obj['config']
    session = get_session(config.database_url)

    console.print("[bold]Interactive Download Mode[/bold]")
    console.print("[dim]Search for comics, then choose to download or export links.\n[/dim]")

    while True:
        query = Prompt.ask("\n[cyan]Search[/cyan] (title/series, or 'quit' to exit)")
        if query.lower() in ('quit', 'exit', 'q'):
            break

        # Search in titles, series, and tags
        comics = session.query(Comic).filter(
            (Comic.title.ilike(f'%{query}%')) |
            (Comic.series.ilike(f'%{query}%'))
        ).limit(50).all()

        # Also search by tag
        tag_comics = session.query(Comic).filter(
            Comic.tags.any(Tag.name.ilike(f'%{query}%'))
        ).limit(50).all()

        # Merge results
        seen_ids = {c.id for c in comics}
        for c in tag_comics:
            if c.id not in seen_ids:
                comics.append(c)
                seen_ids.add(c.id)

        if not comics:
            console.print("[yellow]No results found.[/yellow]")
            continue

        # Display results
        table = Table(title=f"Results for '{query}' ({len(comics)} found)")
        table.add_column("#", style="dim", width=4)
        table.add_column("Title", style="cyan", max_width=55)
        table.add_column("Series", style="green", max_width=25)
        table.add_column("Year", style="yellow", width=10)
        table.add_column("Size", style="magenta", width=8)
        table.add_column("Links", style="blue", width=6)
        table.add_column("DL", style="red", width=3)

        for i, comic in enumerate(comics, 1):
            hosts = set(l.host for l in comic.download_links)
            table.add_row(
                str(i),
                comic.title[:55],
                (comic.series or '-')[:25],
                comic.year or '-',
                comic.size or '-',
                str(len(comic.download_links)),
                '✓' if comic.is_downloaded else '✗',
            )

        console.print(table)

        # Show available hosts
        all_hosts = set()
        for comic in comics:
            for link in comic.download_links:
                if link.host:
                    all_hosts.add(link.host)
        if all_hosts:
            console.print(f"\n[dim]Available hosts: {', '.join(sorted(all_hosts))}[/dim]")

        # Action selection
        console.print("\n[bold]Actions:[/bold]")
        console.print("  [cyan]d[/cyan] - Download all (direct links)")
        console.print("  [cyan]d <numbers>[/cyan] - Download specific (e.g. 'd 1 3 5' or 'd 1-10')")
        console.print("  [cyan]l <host>[/cyan] - Generate link list for host (e.g. 'l mega')")
        console.print("  [cyan]l all[/cyan] - Generate all links")
        console.print("  [cyan]s[/cyan] - New search")
        console.print("  [cyan]q[/cyan] - Quit")

        action = Prompt.ask("\n[cyan]Action[/cyan]")

        if action.lower() in ('s', 'search', ''):
            continue
        elif action.lower() in ('q', 'quit'):
            break
        elif action.lower().startswith('d'):
            _handle_download_action(action, comics, config)
        elif action.lower().startswith('l'):
            _handle_link_export(action, comics, config)


def _handle_download_action(action: str, comics, config: Config):
    """Handle download action from interactive mode."""
    dm = DownloadManager(config)

    # Parse which comics to download
    selected = _parse_selection(action[1:].strip(), len(comics))

    if selected:
        target_comics = [comics[i - 1] for i in selected]
    else:
        target_comics = comics

    count = 0
    for comic in target_comics:
        if dm.add_comic(comic.id):
            count += 1

    dm.session.commit()
    console.print(f"\n[green]Added {count} comics to download queue.[/green]")

    if Confirm.ask("Start downloading now?", default=True):
        console.print("[dim]Press Ctrl+C to stop downloads[/dim]\n")
        dm.start()
        try:
            while True:
                time.sleep(3)
                status = dm.get_status()
                console.print(
                    f"  Pending: {status['pending']} | "
                    f"Active: {status['downloading']} | "
                    f"Done: {status['completed']} | "
                    f"Failed: {status['failed']} | "
                    f"Disk free: {status['disk_free_gb']}GB",
                    end='\r'
                )
                if status['pending'] == 0 and status['downloading'] == 0:
                    break
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping downloads (saving state)...[/yellow]")
            dm.stop()
        console.print("\n[bold green]Downloads finished.[/bold green]")


def _handle_link_export(action: str, comics, config: Config):
    """Handle link export from interactive mode."""
    parts = action.split(maxsplit=1)
    host_filter = parts[1].strip() if len(parts) > 1 else None

    links = []
    for comic in comics:
        for link in comic.download_links:
            if host_filter and host_filter != 'all':
                if link.host != host_filter:
                    continue
            # Prefer resolved URL for direct links, original for external
            if link.resolved_url:
                links.append(link.resolved_url)
            else:
                links.append(link.original_url)

    if not links:
        console.print("[yellow]No links found for the specified host.[/yellow]")
        return

    console.print(f"\n[bold]Links ({len(links)}):[/bold]\n")
    for link in links:
        console.print(link)

    # Offer to save to file
    console.print(f"\n[dim]Total: {len(links)} links[/dim]")
    if Confirm.ask("Save to file?", default=False):
        filename = Prompt.ask("Filename", default="links_export.txt")
        with open(filename, 'w') as f:
            f.write('\n'.join(links))
        console.print(f"[green]Saved to {filename}[/green]")
        console.print("[dim]Tip: Copy the content into JDownloader's LinkGrabber[/dim]")


def _parse_selection(text: str, max_val: int) -> list:
    """Parse selection like '1 3 5' or '1-10' or '1,3,5-8'."""
    if not text:
        return []

    selected = set()
    parts = text.replace(',', ' ').split()
    for part in parts:
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                for i in range(int(start), int(end) + 1):
                    if 1 <= i <= max_val:
                        selected.add(i)
            except ValueError:
                pass
        else:
            try:
                val = int(part)
                if 1 <= val <= max_val:
                    selected.add(val)
            except ValueError:
                pass
    return sorted(selected)


# ═══════════════════════════════════════════════════════════════════
# QUEUE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

@download.command()
@click.option('--series', '-s', help='Add by series name')
@click.option('--tag', '-t', help='Add by tag')
@click.option('--search', '-q', help='Add by title search')
@click.option('--comic-id', '-i', type=int, help='Add specific comic by ID')
@click.option('--host', '-h', help='Prefer specific host')
@click.pass_context
def add(ctx, series, tag, search, comic_id, host):
    """Add comics to download queue."""
    config = ctx.obj['config']
    dm = DownloadManager(config)

    if comic_id:
        if dm.add_comic(comic_id, host):
            console.print(f"[green]Added comic #{comic_id} to queue[/green]")
        else:
            console.print(f"[red]Could not add comic #{comic_id}[/red]")
    elif series:
        count = dm.add_by_series(series, host)
        console.print(f"[green]Added {count} comics from series '{series}'[/green]")
    elif tag:
        count = dm.add_by_tag(tag, host)
        console.print(f"[green]Added {count} comics with tag '{tag}'[/green]")
    elif search:
        count = dm.add_by_search(search, host)
        console.print(f"[green]Added {count} comics matching '{search}'[/green]")
    else:
        console.print("[red]Specify --series, --tag, --search, or --comic-id[/red]")


@download.command(name='start')
@click.pass_context
def download_start(ctx):
    """Start processing the download queue."""
    config = ctx.obj['config']
    dm = DownloadManager(config)

    status = dm.get_status()
    if status['pending'] == 0 and status['paused'] == 0:
        console.print("[yellow]Nothing in queue. Use 'download add' or 'download interactive' first.[/yellow]")
        return

    console.print("[bold green]Starting downloads...[/bold green]")
    console.print(f"  Workers: {config.max_concurrent_downloads}")
    console.print(f"  Directory: {config.download_dir}")
    console.print(f"  Queue: {status['pending']} pending, {status['paused']} paused")
    console.print(f"  Disk free: {status['disk_free_gb']}GB")
    console.print("[dim]  Press Ctrl+C to stop (state is saved)[/dim]\n")

    dm.start()
    try:
        while True:
            time.sleep(3)
            status = dm.get_status()
            console.print(
                f"  Pending: {status['pending']} | "
                f"Active: {status['downloading']} | "
                f"Done: {status['completed']} | "
                f"Failed: {status['failed']} | "
                f"Disk: {status['disk_free_gb']}GB"
            )
            if status['pending'] == 0 and status['downloading'] == 0:
                break
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping...[/yellow]")
        dm.stop()

    final = dm.get_status()
    console.print(f"\n[bold]Final: {final['completed']} completed, {final['failed']} failed[/bold]")


@download.command()
@click.pass_context
def resume(ctx):
    """Resume paused downloads."""
    config = ctx.obj['config']
    dm = DownloadManager(config)
    dm.resume()
    console.print("[green]Paused items requeued. Run 'download start' to begin.[/green]")


@download.command()
@click.pass_context
def retry(ctx):
    """Retry all failed downloads."""
    config = ctx.obj['config']
    dm = DownloadManager(config)
    count = dm.retry_failed()
    console.print(f"[green]Requeued {count} failed downloads. Run 'download start' to begin.[/green]")


@download.command(name='status')
@click.pass_context
def download_status(ctx):
    """Show download queue status."""
    config = ctx.obj['config']
    dm = DownloadManager(config)
    status = dm.get_status()

    table = Table(title="Download Queue Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Pending", str(status['pending']))
    table.add_row("Downloading", str(status['downloading']))
    table.add_row("Completed", str(status['completed']))
    table.add_row("Failed", str(status['failed']))
    table.add_row("Paused", str(status['paused']))
    table.add_row("Total", str(status['total']))
    table.add_row("Disk Free", f"{status['disk_free_gb']} GB")

    console.print(table)


# ═══════════════════════════════════════════════════════════════════
# LINK EXPORT (JDownloader, etc.)
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def links():
    """Export download links for external tools (JDownloader etc.)."""
    pass


@links.command(name='export')
@click.option('--host', '-h', help='Filter by host (mega, mediafire, getcomics_direct, etc.)')
@click.option('--series', '-s', help='Filter by series')
@click.option('--tag', '-t', help='Filter by tag')
@click.option('--search', '-q', help='Search in titles')
@click.option('--resolved', is_flag=True, help='Use resolved URLs (actual file links)')
@click.option('--output', '-o', help='Output file (default: print to screen)')
@click.pass_context
def export_links(ctx, host, series, tag, search, resolved, output):
    """Export download links (paste into JDownloader LinkGrabber)."""
    config = ctx.obj['config']

    link_list = generate_link_list(
        config.database_url,
        host=host,
        series=series,
        tag=tag,
        search=search,
        use_resolved=resolved,
    )

    if not link_list:
        console.print("[yellow]No links found with given filters.[/yellow]")
        return

    content = '\n'.join(link_list)

    if output:
        with open(output, 'w') as f:
            f.write(content)
        console.print(f"[green]Exported {len(link_list)} links to {output}[/green]")
    else:
        for link in link_list:
            console.print(link)

    console.print(f"\n[dim]Total: {len(link_list)} links[/dim]")
    console.print("[dim]Tip: Copy these into JDownloader's LinkGrabber to import[/dim]")


@links.command()
@click.pass_context
def hosts(ctx):
    """Show available hosts and link counts."""
    config = ctx.obj['config']
    session = get_session(config.database_url)

    from sqlalchemy import func
    host_stats = session.query(
        DownloadLink.host, func.count(DownloadLink.id)
    ).group_by(DownloadLink.host).order_by(
        func.count(DownloadLink.id).desc()
    ).all()

    table = Table(title="Available Hosts")
    table.add_column("Host", style="cyan")
    table.add_column("Links", style="green")
    table.add_column("Description", style="dim")

    host_descriptions = {
        'getcomics_main': 'Direct download (auto-resolves)',
        'comicfiles': 'Direct download server',
        'mega': 'Mega.nz (export to JDownloader)',
        'mediafire': 'MediaFire (export to JDownloader)',
        'google_drive': 'Google Drive',
        'pixeldrain': 'Pixeldrain',
        'zippyshare': 'ZippyShare (may be dead)',
        'uploadhaven': 'UploadHaven',
        'workupload': 'WorkUpload',
    }

    for host, count in host_stats:
        desc = host_descriptions.get(host, '')
        table.add_row(host or 'unknown', str(count), desc)

    console.print(table)


# ═══════════════════════════════════════════════════════════════════
# DATABASE UTILITIES
# ═══════════════════════════════════════════════════════════════════

@cli.group()
def db():
    """Database utilities."""
    pass


@db.command()
@click.pass_context
def init(ctx):
    """Initialize the database."""
    config = ctx.obj['config']
    init_db(config.database_url)
    console.print("[bold green]Database initialized![/bold green]")


@db.command()
@click.pass_context
def stats(ctx):
    """Show database statistics."""
    config = ctx.obj['config']
    session = get_session(config.database_url)

    from sqlalchemy import func

    total_comics = session.query(Comic).count()
    total_tags = session.query(Tag).count()
    total_links = session.query(DownloadLink).count()
    downloaded = session.query(Comic).filter(Comic.is_downloaded == True).count()

    direct_links = session.query(DownloadLink).filter(DownloadLink.is_direct == True).count()
    external_links = session.query(DownloadLink).filter(DownloadLink.is_external == True).count()
    resolved_links = session.query(DownloadLink).filter(DownloadLink.resolved_url.isnot(None)).count()

    table = Table(title="Database Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Comics", str(total_comics))
    table.add_row("Total Tags", str(total_tags))
    table.add_row("Total Links", str(total_links))
    table.add_row("  Direct (downloadable)", str(direct_links))
    table.add_row("  External (mega, etc.)", str(external_links))
    table.add_row("  With resolved URL", str(resolved_links))
    table.add_row("Downloaded", str(downloaded))
    table.add_row("Not Downloaded", str(total_comics - downloaded))

    console.print(table)

    # Top series
    top_series = session.query(
        Comic.series, func.count(Comic.id)
    ).filter(Comic.series.isnot(None)).group_by(Comic.series).order_by(
        func.count(Comic.id).desc()
    ).limit(10).all()

    if top_series:
        s_table = Table(title="Top 10 Series")
        s_table.add_column("Series", style="cyan")
        s_table.add_column("Issues", style="green")
        for name, count in top_series:
            s_table.add_row((name or '-')[:60], str(count))
        console.print(s_table)


@db.command()
@click.option('--query', '-q', required=True, help='Search query')
@click.option('--limit', '-l', default=30, help='Max results')
@click.pass_context
def search(ctx, query, limit):
    """Search comics in database."""
    config = ctx.obj['config']
    session = get_session(config.database_url)

    comics = session.query(Comic).filter(
        (Comic.title.ilike(f'%{query}%')) |
        (Comic.series.ilike(f'%{query}%'))
    ).limit(limit).all()

    table = Table(title=f"Search: '{query}' ({len(comics)} results)")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Title", style="cyan", max_width=55)
    table.add_column("Year", style="yellow", width=10)
    table.add_column("Size", style="magenta", width=8)
    table.add_column("Links", style="blue", width=6)

    for comic in comics:
        table.add_row(
            str(comic.id),
            comic.title[:55],
            comic.year or '-',
            comic.size or '-',
            str(len(comic.download_links)),
        )

    console.print(table)


def main():
    cli(obj={})


if __name__ == '__main__':
    main()
