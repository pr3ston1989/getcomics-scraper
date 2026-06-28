# Wizualizacja: co jest zapisywane i jak działa wyszukiwanie/pobieranie

## 1. Co scraper wyciąga ze strony

Przykład strony: `The Shadow – In the Coils of Leviathan #1 – 4 (1993-1994)`

### Źródło (strona HTML):
```
Title: The Shadow – In the Coils of Leviathan #1 – 4 (1993-1994)
Tags: OTHER COMICS, NON 0-DAY, THE SHADOW
Metadata: Language : English | Image Format : JPG | Year : 1993-1994 | Size : 61 MB
Description: The Shadow is faced with a monster who is terrorizing New York...
Published: 19TH JAN '26
Links:
  - DOWNLOAD NOW → getcomics.org/dls/H4EzbSplArfx8HROp6OGsH...
  - TERABOX → 1024terabox.com/s/1IqfYpUplQ5rbir1yVeEHlA
  - ROOTZ → www.rootz.so/d/273xOi
  - VIKINGFILE → vikingfile.com/f/IcgZhYnd0j
  - PIXELDRAIN → getcomics.org/dls/fPQavGeHPDseGExKa1HVG7N...
  - MEGA → getcomics.org/dls/vLahQK4gomXsF5KvQFsUKk...
```

### Co trafia do bazy:

```
┌─────────────────────────────────────────────────────────────────────┐
│ TABELA: comics                                                       │
├─────────────────────────────────────────────────────────────────────┤
│ id:           4521                                                    │
│ title:        The Shadow – In the Coils of Leviathan #1 – 4          │
│ page_url:     https://getcomics.org/other-comics/the-shadow-in-...   │
│ language:     English                                                 │
│ image_format: JPG                                                     │
│ year:         1993-1994                                               │
│ size:         61 MB                                                   │
│ series:       The Shadow – In the Coils of Leviathan   ← parsowane   │
│ issue_number: 1-4                                       ← z tytułu   │
│ description:  The Shadow is faced with a monster...                   │
│ published_at: 2026-01-19                                              │
│ is_downloaded: False                                                  │
│ scraped_at:   2026-06-28 18:30:00                                    │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ TABELA: tags (powiązane z komiksem)                                  │
├─────────────────────────────────────────────────────────────────────┤
│ • OTHER COMICS                                                       │
│ • NON 0-DAY                                                          │
│ • THE SHADOW                                                         │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ TABELA: download_links (6 linków dla tego komiksu)                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│ Link #1 (bezpośredni - do pobrania)                                  │
│   original_url:  https://getcomics.org/dls/H4EzbSplArfx8HRO...      │
│   resolved_url:  https://fs1.comicfiles.ru/2026.01.14/The%20...     │
│   host:          getcomics_main                                      │
│   label:         DOWNLOAD NOW                                        │
│   is_direct:     True                                                │
│   is_external:   False                                               │
│                                                                      │
│ Link #2 (zewnętrzny)                                                 │
│   original_url:  https://1024terabox.com/s/1IqfYpUplQ5rbir...       │
│   resolved_url:  NULL                                                │
│   host:          terabox                                             │
│   label:         TERABOX                                             │
│   is_direct:     False                                               │
│   is_external:   True                                                │
│                                                                      │
│ Link #3 (zewnętrzny)                                                 │
│   original_url:  https://www.rootz.so/d/273xOi                      │
│   resolved_url:  NULL                                                │
│   host:          rootz                                               │
│   label:         ROOTZ                                               │
│   is_direct:     False                                               │
│   is_external:   True                                                │
│                                                                      │
│ Link #4 (zewnętrzny)                                                 │
│   original_url:  https://vikingfile.com/f/IcgZhYnd0j                │
│   resolved_url:  NULL                                                │
│   host:          vikingfile                                          │
│   label:         VIKINGFILE                                          │
│   is_direct:     False                                               │
│   is_external:   True                                                │
│                                                                      │
│ Link #5 (bezpośredni via redirect)                                   │
│   original_url:  https://getcomics.org/dls/fPQavGeHPDseGExK...      │
│   resolved_url:  https://pixeldrain.com/u/abc123xyz                  │
│   host:          pixeldrain                                          │
│   label:         PIXELDRAIN                                          │
│   is_direct:     True                                                │
│   is_external:   False                                               │
│                                                                      │
│ Link #6 (bezpośredni via redirect)                                   │
│   original_url:  https://getcomics.org/dls/vLahQK4gomXsF5Kv...      │
│   resolved_url:  https://mega.nz/file/abc123#key456                  │
│   host:          mega                                                │
│   label:         MEGA                                                │
│   is_direct:     True                                                │
│   is_external:   False                                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Wyszukiwanie (tryb interaktywny)

```
$ python -m src.cli download interactive

Interactive Download Mode
Search for comics, then choose to download or export links.

Search (title/series, or 'quit' to exit): shadow

┌─────────────────────────────────────────────────────────────────────────────┐
│ Results for 'shadow' (12 found)                                              │
├───┬───────────────────────────────────────────┬──────────┬──────┬─────┬────┤
│ # │ Title                                     │ Series   │ Year │ Size│ DL │
├───┼───────────────────────────────────────────┼──────────┼──────┼─────┼────┤
│ 1 │ The Shadow – In the Coils of Leviathan #1-4│ The Sha..│93-94 │61 MB│ ✗  │
│ 2 │ The Shadow – Hell's Heat Wave #1 – 3      │ The Sha..│ 1995 │45 MB│ ✗  │
│ 3 │ The Shadow Vol. 2 #1 – 12                 │ The Sha..│ 2012 │320MB│ ✗  │
│ 4 │ Shadow of the Batgirl (2020)              │ Shadow.. │ 2020 │85 MB│ ✓  │
│...│ ...                                       │ ...      │ ...  │ ... │ ...│
└───┴───────────────────────────────────────────┴──────────┴──────┴─────┴────┘

Available hosts: getcomics_main, mega, pixeldrain, terabox, rootz, vikingfile

Actions:
  d - Download all (direct links)
  d 1 3 - Download specific (e.g. 'd 1 3 5' or 'd 1-3')
  l mega - Generate link list for host (e.g. 'l mega')
  l all - Generate all links
  s - New search
  q - Quit

Action: _
```

---

## 3. Pobieranie - co się dzieje po wybraniu "d 1-3"

```
Action: d 1-3

Added 3 comics to download queue.
Start downloading now? [Y/n]: y
Press Ctrl+C to stop downloads

┌──────────────────────────────────────────────────────────────────────────┐
│ Co się dzieje pod spodem:                                                │
│                                                                          │
│ 1. Bierze Link #1 (getcomics_main) dla każdego komiksu                  │
│ 2. Sprawdza czy resolved_url jest świeży (< 6h)                         │
│    - TAK → pobiera z resolved_url                                        │
│    - NIE → robi request na original_url, podąża za redirectem,           │
│            zapisuje nowy resolved_url i pobiera                           │
│ 3. Plik ląduje w ./downloads/                                            │
│                                                                          │
│ Przykład:                                                                │
│   original_url: getcomics.org/dls/H4EzbSplArfx8HRO...                   │
│        ↓ redirect (302)                                                  │
│   resolved_url: fs1.comicfiles.ru/2026.01.14/The%20Shadow-...zip        │
│        ↓ download                                                        │
│   filepath: ./downloads/The Shadow-In the Coils of Leviathan 001-004.zip│
└──────────────────────────────────────────────────────────────────────────┘

  Pending: 2 | Active: 1 | Done: 0 | Failed: 0 | Disk: 142.5GB
  Pending: 1 | Active: 1 | Done: 1 | Failed: 0 | Disk: 142.4GB
  Pending: 0 | Active: 1 | Done: 2 | Failed: 0 | Disk: 142.1GB

Downloads finished.
```

---

## 4. Eksport linków (JDownloader)

```
Action: l mega

Links (3):

https://getcomics.org/dls/vLahQK4gomXsF5KvQFsUKk...
https://getcomics.org/dls/aB3xYz9mNopQ7rStUvWx...
https://getcomics.org/dls/kL2mNoPqRsTuVwXyZ1a2...

Total: 3 links
Save to file? [y/N]: y
Filename [links_export.txt]: shadow_mega.txt
Saved to shadow_mega.txt
Tip: Copy the content into JDownloader's LinkGrabber
```

Potem w JDownloader: `Ctrl+V` w LinkGrabber → automatycznie rozwiąże redirecty i doda do pobrania.

---

## 5. Schemat relacji w bazie

```
┌──────────┐       ┌──────────────┐       ┌──────────────────┐
│   tags   │◄─────►│  comic_tags  │◄─────►│     comics       │
│          │  M:N  │              │       │                  │
│ id       │       │ comic_id     │       │ id               │
│ name     │       │ tag_id       │       │ title            │
│          │       │              │       │ page_url         │
└──────────┘       └──────────────┘       │ language         │
                                          │ image_format     │
                                          │ year             │
                                          │ size             │
                                          │ series           │
                                          │ issue_number     │
                                          │ description      │
                                          │ published_at     │
                                          │ is_downloaded    │
                                          │ download_path    │
                                          └────────┬─────────┘
                                                   │ 1:N
                                          ┌────────▼─────────┐
                                          │ download_links   │
                                          │                  │
                                          │ id               │
                                          │ comic_id (FK)    │
                                          │ original_url     │
                                          │ resolved_url     │
                                          │ host             │
                                          │ label            │
                                          │ is_direct        │
                                          │ is_external      │
                                          │ resolved_at      │
                                          └──────────────────┘

┌──────────────────┐       ┌──────────────────┐
│  scrape_state    │       │ download_queue    │
│                  │       │                  │
│ status           │       │ comic_id (FK)    │
│ processed_urls   │       │ link_id (FK)     │
│ total_urls       │       │ status           │
│ last_processed   │       │ progress         │
│ ...              │       │ error_message    │
└──────────────────┘       │ retry_count      │
                           │ filepath         │
                           └──────────────────┘
```

---

## 6. Typowe scenariusze użycia

### Scenariusz A: "Chcę pobrać wszystkie Shadow"
```bash
getcomics download interactive
> Search: The Shadow
> Action: d          ← pobierz wszystkie z listy (direct links)
```

### Scenariusz B: "Chcę linki mega na Batmana do JDownloader"
```bash
getcomics links export --series "Batman" --host mega -o batman_mega.txt
# → otwierasz batman_mega.txt, kopiujesz do JDownloader
```

### Scenariusz C: "Sprawdź co nowego na stronie"
```bash
getcomics scrape update
# → dodaje nowe komiksy od ostatniego razu (30s-2min)
```

### Scenariusz D: "Pobieranie przerwane, wznów"
```bash
getcomics download resume
getcomics download start
```
