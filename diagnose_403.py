#!/usr/bin/env python3
"""
Diagnostic script - checks what getcomics.org actually returns for a /dls/ link.
Run this on the server to understand why 403s happen.

Usage:
    python3 diagnose_403.py <comic_page_url> <dls_url>

Example:
    python3 diagnose_403.py \
        "https://getcomics.org/marvel/captain-marvel-4/" \
        "https://getcomics.org/dls/EVfFe6UH..."
"""
import sys
import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

def check(comic_url: str, dls_url: str):
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })

    # Step 1: visit comic page
    print(f"\n[1] Visiting comic page: {comic_url}")
    r1 = session.get(comic_url, timeout=20)
    print(f"    Status: {r1.status_code}")
    print(f"    Cookies set: {dict(session.cookies)}")

    # Step 2: try /dls/ with Referer
    print(f"\n[2] Requesting /dls/ with Referer (stream=False to see response body):")
    print(f"    URL: {dls_url[:100]}...")
    r2 = session.get(
        dls_url,
        allow_redirects=True,
        timeout=30,
        headers={"Referer": comic_url},
    )
    print(f"    Final URL:   {r2.url[:120]}")
    print(f"    Status:      {r2.status_code}")
    print(f"    Headers:     {dict(r2.headers)}")
    print(f"    Body (first 500 chars):\n{r2.text[:500]}")

    # Step 3: try WITHOUT visiting the page first (cold session)
    print(f"\n[3] Cold session (no prior page visit, no cookies):")
    cold = requests.Session()
    cold.headers.update(session.headers)
    r3 = cold.get(
        dls_url,
        allow_redirects=True,
        timeout=30,
        headers={"Referer": comic_url},
    )
    print(f"    Final URL:   {r3.url[:120]}")
    print(f"    Status:      {r3.status_code}")
    print(f"    Body (first 500 chars):\n{r3.text[:500]}")

    # Step 4: try HEAD on /dls/
    print(f"\n[4] HEAD request on /dls/:")
    r4 = session.head(dls_url, allow_redirects=True, timeout=30,
                      headers={"Referer": comic_url})
    print(f"    Final URL:   {r4.url[:120]}")
    print(f"    Status:      {r4.status_code}")
    print(f"    Headers:     {dict(r4.headers)}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        # Try to pull a real example from the DB
        try:
            import sqlite3, os
            db_path = os.getenv("DATABASE_URL", "sqlite:///getcomics.db").replace("sqlite:///", "")
            conn = sqlite3.connect(db_path)
            cur = conn.execute(
                """SELECT c.page_url, dl.original_url
                   FROM download_links dl
                   JOIN comics c ON c.id = dl.comic_id
                   WHERE dl.original_url LIKE '%getcomics.org/dls/%'
                   LIMIT 1"""
            )
            row = cur.fetchone()
            conn.close()
            if row:
                print(f"Auto-detected from DB:")
                print(f"  Comic page: {row[0]}")
                print(f"  DLS url:    {row[1][:80]}...")
                check(row[0], row[1])
            else:
                print("No /dls/ links found in DB. Pass URLs as arguments.")
        except Exception as e:
            print(f"Could not auto-detect from DB: {e}")
            print(__doc__)
    else:
        check(sys.argv[1], sys.argv[2])
