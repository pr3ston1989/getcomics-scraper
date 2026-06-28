# Uruchomienie na serwerze przez SSH

## 1. Połączenie i instalacja

```bash
ssh user@twoj-serwer

# Zainstaluj Python 3.9+ (jeśli nie ma)
sudo apt update
sudo apt install python3 python3-pip python3-venv git

# Sklonuj repo
git clone https://github.com/pr3ston1989/getcomics-scraper.git
cd getcomics-scraper

# Utwórz venv i zainstaluj
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Konfiguracja
cp .env.example .env
nano .env   # ustaw DOWNLOAD_DIR, np. /home/user/comics
```

## 2. Uruchomienie w tle (nie zginie po zamknięciu SSH)

### Opcja A: screen (najprostsza)

```bash
# Zainstaluj screen jeśli nie ma
sudo apt install screen

# Utwórz sesję
screen -S scraper

# Uruchom
cd ~/getcomics-scraper
source venv/bin/activate
python -m src.cli scrape full

# Odłącz się od sesji (scraper działa dalej):
# Ctrl+A, potem D

# Wyloguj się z SSH - scraper nadal chodzi
exit
```

**Powrót do sesji:**
```bash
ssh user@twoj-serwer
screen -r scraper
```

### Opcja B: tmux

```bash
sudo apt install tmux

# Nowa sesja
tmux new -s scraper

# Uruchom
cd ~/getcomics-scraper
source venv/bin/activate
python -m src.cli scrape full

# Odłącz: Ctrl+B, potem D

# Powrót:
tmux attach -t scraper
```

### Opcja C: nohup (fire and forget)

```bash
cd ~/getcomics-scraper
source venv/bin/activate

# Uruchom w tle, logi do pliku
nohup python -m src.cli scrape full > scrape_output.log 2>&1 &

# Sprawdź czy działa
tail -f scrape_output.log

# Sprawdź proces
ps aux | grep "src.cli"
```

## 3. Sprawdzanie postępu (z innej sesji SSH)

```bash
ssh user@twoj-serwer
cd ~/getcomics-scraper
source venv/bin/activate

# Status scrapowania
python -m src.cli scrape status

# Statystyki bazy
python -m src.cli db stats

# Ile pobrane
python -m src.cli db progress
```

## 4. Zatrzymanie

### Jeśli screen/tmux:
```bash
screen -r scraper    # lub: tmux attach -t scraper
# Naciśnij Ctrl+C (graceful stop, zapisuje pozycję)
```

### Jeśli nohup:
```bash
# Znajdź PID
ps aux | grep "src.cli"

# Wyślij SIGINT (graceful stop)
kill -2 <PID>

# Lub SIGTERM
kill <PID>
```

## 5. Wznawianie po zatrzymaniu

```bash
# Po Ctrl+C lub kill - po prostu uruchom ponownie
python -m src.cli scrape full
# Automatycznie wznowi od ostatniej pozycji
```

## 6. Pełny workflow na serwerze

```bash
# === DZIEŃ 1: Pełne scrapowanie ===
screen -S scraper
cd ~/getcomics-scraper && source venv/bin/activate
python -m src.cli scrape full
# Ctrl+A, D (odłącz)

# === NASTĘPNE DNI: Tylko nowe ===
screen -r scraper
python -m src.cli scrape update
# Ctrl+A, D

# === POBIERANIE PRIORYTETÓW ===
screen -S downloader
cd ~/getcomics-scraper && source venv/bin/activate
python -m src.cli download interactive
# szukaj, wybierz, pobierz

# === POBIERANIE WSZYSTKIEGO ===
python -m src.cli download add --all
python -m src.cli download start
# Ctrl+A, D (pobieranie w tle)

# === EKSPORT LINKÓW (np. do JDownloader na PC) ===
python -m src.cli links export --host mega -o mega_links.txt
# Skopiuj plik na PC:
# scp user@serwer:~/getcomics-scraper/mega_links.txt .
```

## 7. Automatyczne codzienne aktualizacje (cron)

```bash
crontab -e

# Dodaj linię (codziennie o 3:00 w nocy):
0 3 * * * cd /home/user/getcomics-scraper && /home/user/getcomics-scraper/venv/bin/python -m src.cli scrape update >> /home/user/getcomics-scraper/cron.log 2>&1
```

## 8. Kopiowanie bazy/linków na lokalny komputer

```bash
# Z lokalnego PC:
scp user@serwer:~/getcomics-scraper/getcomics.db .
scp user@serwer:~/getcomics-scraper/mega_links.txt .

# Lub zamontuj przez sshfs:
sshfs user@serwer:/home/user/getcomics-scraper/downloads /mnt/comics
```
