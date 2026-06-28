# GetComics Scraper & Download Manager

Scraper i menedżer pobierania dla GetComics.org z dwoma głównymi trybami pracy.

## Tryby

### 1. Scraper (`scrape`)
- Pełne scrapowanie sitemap z opcją zatrzymania/wznowienia (Ctrl+C)
- Tryb aktualizacji - pobiera tylko nowe wpisy od ostatniego uruchomienia
- Konfigurowalna szybkość (delay między requestami)
- Parsuje metadane: język, format obrazu, rok, rozmiar
- Identyfikuje serie i numery zeszytów
- Zapisuje WSZYSTKIE linki (oryginalne ze strony + resolved po redirect)

### 2. Pobieranie (`download`)
- Tryb interaktywny: wpisz frazę → zobacz wyniki → wybierz akcję
- Wyszukiwanie po tytule, serii, tagach
- Pobieranie bezpośrednie z auto-resolving linków redirect
- Eksport linków na konkretny serwis (mega, mediafire) do JDownloader
- Kolejka z zatrzymywaniem/wznawianiem
- Obsługa błędów: pełny dysk, wygasłe linki, retry z backoff

## Jak działają linki

GetComics używa obfuskowanych linków redirect (`getcomics.org/dls/...`).
Te linki to permanentne server-side redirecty do prawdziwych plików.

**Strategia:**
- Zapisujemy **oryginalny URL** ze strony (permanentny)
- Zapisujemy **resolved URL** po przekierowaniu (może wygasnąć)
- Przy pobieraniu: jeśli resolved URL wygasł → re-resolve z oryginału
- Linki zewnętrzne (mega, mediafire): export do JDownloader

## Wymagania

- Python 3.9+

## Instalacja

```bash
git clone https://github.com/pr3ston1989/getcomics-scraper.git
cd getcomics-scraper
pip install -e .
```

## Konfiguracja

```bash
cp .env.example .env
# Edytuj .env - ustaw szybkość, katalog pobierania, itd.
```

## Użycie

### Scraper

```bash
# Inicjalizacja bazy
getcomics db init

# Pełne scrapowanie (Ctrl+C zatrzymuje, następne uruchomienie wznawia)
getcomics scrape full

# Tylko nowe komiksy od ostatniego razu
getcomics scrape update

# Ustaw szybkość
getcomics scrape speed --delay-min 1.0 --delay-max 3.0

# Status
getcomics scrape status
```

### Pobieranie (tryb interaktywny)

```bash
getcomics download interactive
```

Wpisujesz frazę → dostajesz tabelę wyników → wybierasz:
- `d` - pobierz wszystkie (direct links)
- `d 1 3 5` lub `d 1-10` - pobierz wybrane
- `l mega` - wygeneruj listę linków z mega.nz
- `l all` - wszystkie linki (do skopiowania do JDownloader)

### Przeglądanie bazy - co jest do pobrania

```bash
# Lista wszystkich tagów (ekran - top 50)
getcomics db tags

# Eksport tagów do pliku (wszystkie)
getcomics db tags -o tags.txt

# Tylko tagi z min. 10 komiksami
getcomics db tags -m 10

# Lista serii
getcomics db series -o series.txt
getcomics db series -m 5    # min 5 zeszytów w serii

# Lista tytułów
getcomics db titles -o titles.txt

# Tytuły z konkretnego tagu
getcomics db titles -t "DC" -o dc_titles.txt

# Tytuły z konkretnej serii
getcomics db titles -s "Batman" -o batman.txt

# Szukaj w bazie
getcomics db search -q "Spider-Man"

# Co pobrane / co czeka
getcomics db progress
getcomics db progress --not-downloaded
getcomics db progress --downloaded -s "Batman"
```

### Pobieranie (CLI)

```bash
# Dodaj do kolejki
getcomics download add --series "Batman"
getcomics download add --tag "Marvel"
getcomics download add --search "Spider-Man"
getcomics download add --comic-id 42

# Start pobierania (Ctrl+C zatrzymuje, zachowuje stan)
getcomics download start

# Wznów zatrzymane
getcomics download resume

# Ponów nieudane
getcomics download retry

# Status kolejki
getcomics download status
```

### Eksport linków (JDownloader)

```bash
# Linki z mega dla konkretnej serii
getcomics links export --host mega --series "Batman"

# Wszystkie linki mediafire z zapisem do pliku
getcomics links export --host mediafire -o mediafire_links.txt

# Resolved URLs (bezpośrednie linki do plików)
getcomics links export --search "Spider-Man" --resolved

# Pokaż dostępne hosty
getcomics links hosts
```

## Obsługa błędów

- **Pełny dysk**: automatyczne wstrzymanie pobierania z powiadomieniem
- **Wygasłe linki**: automatyczne ponowne rozwiązywanie z oryginalnego URL
- **Błędy sieci**: retry z exponential backoff (max 3 próby)
- **Przerwane pobieranie**: `download resume` wznawia od miejsca zatrzymania

## Struktura bazy

- `comics` - komiksy (tytuł, metadane, seria, rok, rozmiar)
- `tags` - tagi/kategorie
- `download_links` - linki (`original_url` + `resolved_url` + host)
- `download_queue` - kolejka pobierania z statusem
- `scrape_state` - stan scrapowania (do pause/resume)
