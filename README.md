# 🎬 Gaparr

**Automatically find and add missing collection movies to Radarr.**

---

## How It Works

1. Scans your Radarr library for all movies
2. Finds which TMDB collections those movies belong to
3. Fetches complete collection details from TMDB
4. Identifies movies you're missing
5. Automatically adds up to your daily limit to Radarr

---

## Quick Start

### 1. Clone or download Gaparr

```bash
git clone https://github.com/yourusername/gaparr.git
cd gaparr
```

### 2. Create your config file

```bash
copy config_example.json config.json
```

Edit `config.json` with your settings:

```json
{
  "radarr_url": "http://192.168.0.77:7878",
  "radarr_api_key": "YOUR_RADARR_API_KEY",
  "tmdb_api_key": "YOUR_TMDB_API_KEY",
  "root_folder": "/movies",
  "daily_limit": 5,
  "auto_add": true,
  "hide_future": true
}
```

### 3. Start the container

```bash
docker-compose up -d
```

### 4. Check the logs

```bash
docker logs gaparr
```

Or view the log file: `logs/gaparr.log`

---

## Configuration Options

| Setting | Description |
|---------|-------------|
| `radarr_url` | Your Radarr URL (e.g., http://192.168.0.77:7878) |
| `radarr_api_key` | From Radarr Settings → General |
| `tmdb_api_key` | From themoviedb.org (create free account) |
| `root_folder` | Where Radarr stores movies |
| `daily_limit` | Max movies to add per day (1-50) |
| `auto_add` | true = automatic, false = dry run |
| `hide_future` | true = skip unreleased movies |

---

## Manual Run

Run the script immediately (not waiting for schedule):

```bash
docker exec -it gaparr python sync.py
```

---

## View Results

- **Radarr UI** – New movies appear in your library
- **Docker logs** – `docker logs gaparr`
- **Log file** – `logs/gaparr.log`
- **Last scan results** – `logs/last_scan.json`

---

## Schedule

The script runs automatically at 2:00 AM daily. To change the schedule, edit the command in `docker-compose.yml`:

```yaml
environment:
  - TZ=America/New_York
  - CRON_SCHEDULE=0 11 * * *
```

Or use your preferred scheduling method.

---

## Requirements

- Docker Desktop (Windows/Mac) or Docker Engine (Linux)
- Radarr running and accessible
- TMDB API key (free)

---

## Troubleshooting

**"No quality profiles found"**
- Create at least one quality profile in Radarr (Settings → Quality Profiles)

**"Config file not found"**
- Copy `config_example.json` to `config.json` and edit it

**Connection failed to Radarr**
- Check `radarr_url` is correct and Radarr is running

---

## Files

| File | Purpose |
|------|---------|
| `sync.py` | Main script |
| `config.json` | Your settings (you create this) |
| `config_example.json` | Template for config |
| `logs/gaparr.log` | Script output |
| `logs/last_scan.json` | Last scan results |

---

## License

MIT

---

## Support

Open an issue on GitHub

---

**Gaparr** – Keep your collections complete. 🎬