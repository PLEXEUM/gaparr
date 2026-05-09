# 🎬 Gaparr

**Automatically add missing collection movies to Radarr.**

Gaparr scans your Radarr library, finds movies missing from TMDB collections (like sequels or franchise entries), and adds them to Radarr - respecting your daily limits and filtering future releases.

---

## ✨ Features

- **Collection Discovery** - Finds missing movies from TMDB collections
- **Daily Limits** - Control how many movies get added per day
- **Future Release Filter** - Skip movies that haven't been released yet
- **Ignore Lists** - Permanently skip specific movies or entire collections
- **Dry Run Mode** - Preview what would be added without making changes
- **Docker Ready** - Easy deployment with Docker Compose
- **Dark/Light Theme** - Matches Resizarr's visual design

---

## 🚀 Quick Start

### Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/gaparr.git
cd gaparr

# Copy and edit environment file
cp .env.example .env
# Edit .env with your Radarr URL, API key, and TMDB API key

# Start Gaparr
docker-compose up -d
```

Open `http://localhost:7117` in your browser.

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your configuration

# Run the app
python main.py
```

---

## ⚙️ Configuration

Create a `.env` file with these settings:

```env
# Required
RADARR_URL=http://localhost:7878
RADARR_API_KEY=your_radarr_api_key
TMDB_API_KEY=your_tmdb_api_key

# Optional
DAILY_LIMIT=5                    # Movies to add per day
SYNC_TIME=02:00                  # Daily sync time (24h)
HIDE_FUTURE_RELEASES=true        # Skip unreleased movies
LOG_LEVEL=INFO                   # DEBUG, INFO, WARNING, ERROR
PORT=7117                        # Web UI port
```

### Getting a TMDB API Key

1. Sign up at [themoviedb.org](https://www.themoviedb.org)
2. Go to Settings → API
3. Request an API key (Developer)
4. Copy your API key to `.env`

### Getting Radarr API Key

1. Open Radarr → Settings → General
2. Copy the API Key under "Security"

---

## 📊 Usage

### Dashboard

- View missing movies found in your collections
- See daily sync progress (X of Y movies added today)
- Run manual sync or dry run preview

### Settings

- Configure Radarr connection (URL, API key, root folder)
- Configure TMDB API key
- Set daily limit and sync schedule

### Logs

- View application activity
- Download logs for debugging

---

## 🐳 Docker Commands

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down

# Restart
docker-compose restart
```

---

## 📁 Project Structure

```
gaparr/
├── app/
│   ├── api/              # FastAPI routes
│   ├── services/         # Radarr, TMDB, Sync services
│   ├── templates/        # HTML templates
│   └── static/           # Static assets
├── data/                 # Persistent state (ignore lists, sync counts)
├── main.py              # Application entry point
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker build instructions
├── docker-compose.yml   # Docker Compose configuration
└── .env.example         # Environment variables template
```

---

## 🔧 How It Works

1. **Fetch Radarr Library** - Gets all movies currently in Radarr
2. **Find Collections** - For each movie, finds its TMDB collection
3. **Identify Gaps** - Compares collection parts against owned movies
4. **Apply Filters** - Skips ignored items, future releases, and respects daily limit
5. **Add to Radarr** - Adds missing movies automatically

---

## ❓ FAQ

**Why use Radarr instead of Plex as source of truth?**

Radarr knows about movies you've added (even if not yet downloaded). Plex only knows what's actually on disk. Using Radarr prevents re-adding movies that are already in your queue.

**How does the daily limit work?**

Gaparr tracks how many movies it has added each day in `data/sync_state.json`. Once the limit is reached, no more movies will be added until the next day.

**Can I preview changes before syncing?**

Yes! Use the "Dry Run" button on the dashboard to see what would be added without actually adding anything.

**How do I ignore a movie or collection?**

Use the ignore endpoints via API (coming soon to UI). For now, you can manually edit `data/sync_state.json`.

---

## 📝 License

MIT License - see LICENSE file for details.

---

## 🙏 Credits

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Radarr integration adapted from Resizarr
- Collection logic inspired by GAPS-2

---

**Gaparr** – Keep your collections complete. 🎬