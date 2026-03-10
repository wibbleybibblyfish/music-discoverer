<p align="center">
  <img src="logo-256.png" alt="Music Discovernator" width="200">
</p>

# Music Discovernator

A self-hosted music discovery app that learns your taste. Add any genre, and it automatically finds tracks from YouTube channels, Reddit communities, and Deezer playlists. Rate tracks to get smarter recommendations over time.

No API keys required. No accounts. Just music.

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue) ![No API Keys](https://img.shields.io/badge/API%20keys-none-green) ![License: MIT](https://img.shields.io/badge/license-MIT-yellow)

## Quick Start

```bash
git clone https://github.com/wibbleybibblyfish/music-discoverer.git
cd music-discoverer
./start.sh
```

That's it. The setup wizard opens in your browser and guides you through picking genres.

## How It Works

1. **Pick your genres** — the setup wizard auto-discovers sources for any genre (vocal trance, deep house, synthwave, drum and bass, etc.)
2. **Browse your feed** — tracks from all your genres, mixed together, with 30-second Deezer previews and YouTube playback
3. **Rate tracks** — 1-5 stars, or skip. The recommendation engine learns your preferences
4. **Get better recommendations** — the more you rate, the smarter it gets

### What It Learns

- Subgenre preferences (uplifting, progressive, classic, etc.)
- Energy level sweet spot
- BPM range
- Artist and vocalist affinity
- Source credibility (tracks found on multiple sources score higher)

## Sources

For each genre, the app pulls tracks from:

- **YouTube RSS** — monitors label/artist channels for new uploads
- **Reddit RSS** — pulls from genre subreddits
- **Deezer** — searches playlists and keywords (free API, no key needed)

Sources auto-refresh every 6 hours (configurable in settings).

## Features

- Genre-agnostic — add as many genres as you want
- Setup wizard with auto-discovery of sources per genre
- Settings page for managing sources, toggling feeds, adjusting fetch intervals
- Filter by genre, source, subgenre, energy level
- Sort by newest, score, or random
- Card-based UI with swap animations
- 30-second preview playback via Deezer
- YouTube video embeds
- Stats dashboard with taste profile breakdown
- Dark theme
- Zero external dependencies beyond Python

## Manual Setup

If you prefer not to use `start.sh`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Open http://localhost:8138

## Configuration

On first launch, the setup wizard creates `config.json`. You can also copy the example:

```bash
cp config.example.json config.json
```

The settings page (gear icon) lets you manage everything in the browser — add/remove genres, enable/disable individual sources, change fetch intervals.

## Files

| File | Purpose |
|------|---------|
| `server.py` | HTTP server, recommendation engine, all API endpoints |
| `sources.py` | Multi-source track fetcher + auto-discovery |
| `index.html` | Main feed UI |
| `setup.html` | First-launch setup wizard |
| `settings.html` | Source management and settings |
| `recommend.py` | Standalone CLI recommender (optional) |
| `tracks.json` | Curated vocal trance seed database (optional, imported if genre selected) |
| `config.json` | Your genre and source configuration (auto-created) |
| `discovered.json` | Track database (auto-created) |
| `ratings.json` | Your ratings (auto-created) |

## CLI Tool

There's also a standalone CLI for quick recommendations:

```bash
.venv/bin/python recommend.py                      # 5 random picks
.venv/bin/python recommend.py -n 10                # 10 picks
.venv/bin/python recommend.py --subgenre uplifting # filter by subgenre
.venv/bin/python recommend.py stats                # database overview
```

## License

MIT
