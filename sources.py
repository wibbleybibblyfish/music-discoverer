"""
Multi-source music track discovery.
Each source returns normalized track dicts ready for the database.
"""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) VocalTranceRecommender/2.0"


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def track_hash(artist, title):
    """Stable ID for deduplication across sources."""
    key = f"{artist.lower().strip()}|||{title.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def parse_youtube_title(title):
    """
    Parse artist and track from YouTube video titles.
    Common formats:
      Artist - Track Title
      Artist - Track Title (Remix)
      Artist feat. Vocalist - Track Title
      Artist ft. Vocalist - Track Title [Label]
    """
    # Remove common suffixes
    clean = re.sub(r'\[(?:Official|Music|Lyric|Audio|Video|Visualizer|4K|HD|HQ).*?\]', '', title, flags=re.I)
    clean = re.sub(r'\((?:Official|Music|Lyric|Audio|Video|Visualizer|4K|HD|HQ).*?\)', '', clean, flags=re.I)
    clean = re.sub(r'\[(?:FREE|OUT NOW|PREMIERE).*?\]', '', clean, flags=re.I)
    clean = re.sub(r'\((?:FREE|OUT NOW|PREMIERE).*?\)', '', clean, flags=re.I)
    clean = clean.strip()

    # Try "Artist - Title" split
    parts = re.split(r'\s*[-–—]\s*', clean, maxsplit=1)
    if len(parts) == 2:
        artist = parts[0].strip()
        track_title = parts[1].strip()

        # Extract featured vocalists
        vocalists = []
        feat_match = re.search(r'(?:feat\.?|ft\.?|featuring)\s+(.+?)(?:\s*[-–—(|]|$)', artist, re.I)
        if feat_match:
            vocalists = [v.strip() for v in re.split(r'\s*[,&]\s*', feat_match.group(1))]
            artist = artist[:feat_match.start()].strip()

        feat_match2 = re.search(r'(?:feat\.?|ft\.?|featuring)\s+(.+?)(?:\s*[)\]|]|$)', track_title, re.I)
        if feat_match2:
            vocalists += [v.strip() for v in re.split(r'\s*[,&]\s*', feat_match2.group(1))]
            track_title = track_title[:feat_match2.start()].strip()

        # Clean up parenthetical remix info but keep it
        remix_match = re.search(r'\(([^)]*(?:remix|mix|edit|dub)[^)]*)\)', track_title, re.I)
        remix = remix_match.group(1).strip() if remix_match else None

        # Remove label tags in brackets
        track_title = re.sub(r'\[.*?\]', '', track_title).strip()

        if artist and track_title:
            return {
                "artist": artist,
                "title": track_title,
                "vocalists": vocalists,
                "remix": remix,
            }

    return None


# ---------------------------------------------------------------------------
# YouTube RSS Source
# ---------------------------------------------------------------------------

def fetch_youtube(genre):
    """Fetch new tracks from YouTube channels via RSS for a genre."""
    genre_name = genre["name"]
    channels = [ch for ch in genre["sources"].get("youtube", []) if ch.get("enabled")]
    tracks = []

    for ch in channels:
        try:
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['id']}"
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:15]:
                parsed = parse_youtube_title(entry.title)
                if not parsed:
                    continue

                video_id = entry.get("yt_videoid", "")
                if not video_id and hasattr(entry, "link"):
                    m = re.search(r'v=([a-zA-Z0-9_-]{11})', entry.link)
                    video_id = m.group(1) if m else ""

                published = ""
                if hasattr(entry, "published"):
                    published = entry.published

                tracks.append({
                    "id": track_hash(parsed["artist"], parsed["title"]),
                    "artist": parsed["artist"],
                    "title": parsed["title"],
                    "vocalists": parsed.get("vocalists", []),
                    "remix": parsed.get("remix"),
                    "youtube_id": video_id,
                    "genre": genre_name,
                    "genres": [genre_name],
                    "source": f"youtube:{ch['name']}",
                    "source_type": "youtube",
                    "discovered_at": published or datetime.now(timezone.utc).isoformat(),
                    "url": entry.link if hasattr(entry, "link") else "",
                })

            time.sleep(0.5)
        except Exception as e:
            print(f"  [youtube] Error fetching {ch['name']}: {e}")

    return tracks


# ---------------------------------------------------------------------------
# Reddit RSS Source
# ---------------------------------------------------------------------------

def fetch_reddit(genre):
    """Fetch track posts from subreddits for a genre."""
    genre_name = genre["name"]
    subs = [s for s in genre["sources"].get("reddit", []) if s.get("enabled")]
    tracks = []

    for sub_cfg in subs:
        sub = sub_cfg["sub"]
        try:
            feed = feedparser.parse(
                f"https://www.reddit.com/r/{sub}.rss",
                request_headers={"User-Agent": UA},
            )

            for entry in feed.entries[:25]:
                title = entry.title
                parsed = parse_youtube_title(title)
                if not parsed:
                    continue

                # Try to extract YouTube ID from the post link
                youtube_id = ""
                link = entry.get("link", "")
                yt_match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', link)
                if yt_match:
                    youtube_id = yt_match.group(1)

                # Also check content/summary for YouTube links
                summary = entry.get("summary", "")
                if not youtube_id:
                    yt_match2 = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', summary)
                    if yt_match2:
                        youtube_id = yt_match2.group(1)

                published = entry.get("published", datetime.now(timezone.utc).isoformat())

                tracks.append({
                    "id": track_hash(parsed["artist"], parsed["title"]),
                    "artist": parsed["artist"],
                    "title": parsed["title"],
                    "vocalists": parsed.get("vocalists", []),
                    "remix": parsed.get("remix"),
                    "youtube_id": youtube_id,
                    "genre": genre_name,
                    "genres": [genre_name],
                    "source": f"reddit:r/{sub}",
                    "source_type": "reddit",
                    "discovered_at": published,
                    "url": link,
                })

            time.sleep(1)
        except Exception as e:
            print(f"  [reddit] Error fetching r/{sub}: {e}")

    return tracks


# ---------------------------------------------------------------------------
# Deezer API Source (free, no auth required)
# ---------------------------------------------------------------------------

DEEZER_API = "https://api.deezer.com"

REDDIT_GENRE_MAP = {
    # Electronic
    "vocal trance": ["vocaltrance"],
    "trance": ["trance"],
    "deep house": ["deephouse"],
    "progressive house": ["progressivehouse"],
    "techno": ["techno"],
    "drum and bass": ["dnb", "drumandbass"],
    "synthwave": ["synthwave", "outrun"],
    "lo-fi": ["lofi", "lofihiphop"],
    "ambient": ["ambient"],
    "house": ["house"],
    "edm": ["edm"],
    "dubstep": ["dubstep"],
    "hardstyle": ["hardstyle"],
    "psytrance": ["psytrance"],
    "chillout": ["chillout"],
    "melodic techno": ["melodictechno"],
    "progressive trance": ["progressivetrance"],
    "minimal": ["minimal"],
    "breakbeat": ["breakbeat"],
    "jungle": ["jungle"],
    "garage": ["garage", "ukgarage"],
    "downtempo": ["downtempo"],
    "electro": ["electro"],
    "industrial": ["industrialmusic"],
    "goa trance": ["goatrance"],
    "electronic": ["electronicmusic"],
    # Non-electronic
    "jazz": ["jazz"],
    "hip hop": ["hiphopheads"],
    "r&b": ["rnb"],
    "indie rock": ["indieheads"],
    "metal": ["metal"],
    "punk": ["punk"],
    "classical": ["classicalmusic"],
    "folk": ["folk"],
    "blues": ["blues"],
    "soul": ["soul"],
    "country": ["country"],
    "reggae": ["reggae"],
    "pop": ["popheads"],
    "rock": ["rock"],
    "funk": ["funk"],
    "latin": ["latinmusic"],
    "k-pop": ["kpop"],
    "shoegaze": ["shoegaze"],
    "post-rock": ["postrock"],
    "math rock": ["mathrock"],
    "emo": ["emo"],
    "ska": ["ska"],
    "grunge": ["grunge"],
}


def discover_sources(genre_name):
    """Auto-discover YouTube channels, Reddit subs, and Deezer playlists for a genre."""
    results = {"youtube": [], "reddit": [], "deezer_playlists": [], "deezer_searches": []}

    # Deezer playlists — search API (free, no auth)
    try:
        resp = requests.get(f"{DEEZER_API}/search/playlist",
            params={"q": genre_name, "limit": 8}, timeout=15)
        if resp.status_code == 200:
            for pl in resp.json().get("data", []):
                if pl.get("nb_tracks", 0) >= 10:
                    results["deezer_playlists"].append({
                        "name": pl["title"][:60],
                        "id": str(pl["id"]),
                        "track_count": pl.get("nb_tracks", 0),
                        "enabled": True,
                    })
    except Exception:
        pass

    # Deezer searches — auto-generate search terms
    current_year = datetime.now().year
    results["deezer_searches"] = [
        f"{genre_name} {current_year}",
        f"{genre_name} {current_year - 1}",
        f"{genre_name} new",
        genre_name,
    ]

    # Reddit subs — mapping or guess
    genre_lower = genre_name.lower().strip()
    if genre_lower in REDDIT_GENRE_MAP:
        for sub in REDDIT_GENRE_MAP[genre_lower]:
            results["reddit"].append({"name": f"r/{sub}", "sub": sub, "enabled": True})
    else:
        guessed = re.sub(r'[^a-z0-9]', '', genre_lower)
        if guessed:
            results["reddit"].append({"name": f"r/{guessed}", "sub": guessed, "enabled": True})

    # YouTube — scrape search for channels
    try:
        query = quote_plus(f"{genre_name} music")
        resp = requests.get(
            f"https://www.youtube.com/results?search_query={query}&sp=EgIQAg%3D%3D",
            headers={"User-Agent": UA}, timeout=10)
        if resp.status_code == 200:
            channels_found = set()
            for m in re.finditer(r'"channelId":"(UC[a-zA-Z0-9_-]{22})".*?"text":"([^"]{2,50})"', resp.text):
                cid, cname = m.group(1), m.group(2)
                if cid not in channels_found and len(channels_found) < 6:
                    channels_found.add(cid)
                    results["youtube"].append({"name": cname, "id": cid, "enabled": True})
    except Exception:
        pass

    return results


def _deezer_track_to_dict(t, source_str, genre_name):
    """Convert a Deezer API track object to our standard track dict."""
    artist_name = t.get("artist", {}).get("name", "Unknown")
    title = t.get("title", "")
    if not title:
        return None
    return {
        "id": track_hash(artist_name, title),
        "artist": artist_name,
        "title": title,
        "vocalists": [],
        "remix": None,
        "youtube_id": "",
        "deezer_id": str(t["id"]),
        "preview_url": t.get("preview", ""),
        "bpm": 0,
        "energy": 0,
        "release_date": "",
        "genre": genre_name,
        "genres": [genre_name],
        "source": source_str,
        "source_type": "deezer",
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "url": t.get("link", ""),
        "thumbnail": t.get("album", {}).get("cover_medium", ""),
    }


def enrich_deezer_dates(tracks, limit=80, on_progress=None):
    """Fetch release dates from Deezer track API for tracks missing them."""
    needs_date = [t for t in tracks if t.get("deezer_id") and not t.get("release_date")]
    if not needs_date:
        return 0

    batch = needs_date[:limit]
    total = len(batch)
    enriched = 0
    for i, t in enumerate(batch, 1):
        if on_progress:
            on_progress(f"Enriching release dates... {i}/{total}")
        try:
            resp = requests.get(f"{DEEZER_API}/track/{t['deezer_id']}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                rd = data.get("release_date", "")
                if rd:
                    t["release_date"] = rd
                    t["year"] = int(rd[:4])
                    enriched += 1
            time.sleep(0.2)
        except Exception:
            pass
    return enriched


def fetch_deezer(genre):
    """Fetch tracks from Deezer search and playlists for a genre."""
    genre_name = genre["name"]
    sources = genre.get("sources", {})
    all_tracks = []

    # 1. Fetch from playlists
    playlists = [pl for pl in sources.get("deezer_playlists", []) if pl.get("enabled")]
    for pl in playlists:
        try:
            resp = requests.get(
                f"{DEEZER_API}/playlist/{pl['id']}/tracks",
                params={"limit": 50},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            for t in data.get("data", []):
                track = _deezer_track_to_dict(t, f"deezer:playlist:{pl['name']}", genre_name)
                if track:
                    all_tracks.append(track)

            time.sleep(0.3)
        except Exception as e:
            print(f"  [deezer] Error fetching playlist {pl['name']}: {e}")

    # 2. Search queries
    for query in sources.get("deezer_searches", []):
        try:
            resp = requests.get(
                f"{DEEZER_API}/search",
                params={"q": query, "limit": 25},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            for t in data.get("data", []):
                track = _deezer_track_to_dict(t, "deezer:search", genre_name)
                if track:
                    all_tracks.append(track)

            time.sleep(0.3)
        except Exception as e:
            print(f"  [deezer] Error searching '{query}': {e}")

    return all_tracks


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DB_FILE = SCRIPT_DIR / "discovered.json"


def load_discovered_db():
    if DB_FILE.exists():
        with open(DB_FILE) as f:
            return json.load(f)
    return []


def save_discovered_db(tracks):
    with open(DB_FILE, "w") as f:
        json.dump(tracks, f, indent=2)


def merge_tracks(existing, new_tracks):
    """Merge new tracks into existing DB, deduplicating by ID."""
    by_id = {t["id"]: t for t in existing}
    added = 0

    for t in new_tracks:
        tid = t["id"]
        if tid not in by_id:
            by_id[tid] = t
            added += 1
        else:
            # Update with new info if we have better data
            old = by_id[tid]
            if not old.get("youtube_id") and t.get("youtube_id"):
                old["youtube_id"] = t["youtube_id"]
            if not old.get("deezer_id") and t.get("deezer_id"):
                old["deezer_id"] = t["deezer_id"]
            if not old.get("preview_url") and t.get("preview_url"):
                old["preview_url"] = t["preview_url"]
            if not old.get("bpm") and t.get("bpm"):
                old["bpm"] = t["bpm"]
            if not old.get("energy") and t.get("energy"):
                old["energy"] = t["energy"]
            if not old.get("thumbnail") and t.get("thumbnail"):
                old["thumbnail"] = t["thumbnail"]
            if not old.get("release_date") and t.get("release_date"):
                old["release_date"] = t["release_date"]
            if not old.get("year") and t.get("year"):
                old["year"] = t["year"]
            # Merge genre lists (union)
            if t.get("genre"):
                existing_genres = set(old.get("genres", [old.get("genre", "")]))
                existing_genres.add(t["genre"])
                old["genres"] = sorted(g for g in existing_genres if g)
            # Track additional sources
            sources = set(old.get("sources", [old.get("source", "")]))
            sources.add(t.get("source", ""))
            old["sources"] = list(s for s in sources if s)

    return list(by_id.values()), added


# ---------------------------------------------------------------------------
# Import seed tracks from curated tracks.json
# ---------------------------------------------------------------------------

def import_seed_tracks():
    """Import curated tracks.json into the discovered database."""
    seed_file = SCRIPT_DIR / "tracks.json"
    if not seed_file.exists():
        return 0

    with open(seed_file) as f:
        seeds = json.load(f)

    tracks = []
    for s in seeds:
        tracks.append({
            "id": track_hash(s["artist"], s["title"]),
            "artist": s["artist"],
            "title": s["title"],
            "vocalists": s.get("vocalists", []),
            "remix": None,
            "youtube_id": "",
            "genre": "vocal trance",
            "genres": ["vocal trance"],
            "bpm": s.get("bpm", 0),
            "energy": s.get("energy", 0),
            "source": "curated",
            "source_type": "curated",
            "discovered_at": f"{s.get('year', 2020)}-01-01T00:00:00Z",
            "url": "",
            "subgenre": s.get("subgenre", ""),
            "year": s.get("year", 0),
        })

    return tracks


# ---------------------------------------------------------------------------
# YouTube ID enrichment — scrape search results for video IDs
# ---------------------------------------------------------------------------

def search_youtube_id(artist, title):
    """Search YouTube and return the first video ID found."""
    query = quote_plus(f"{artist} - {title}")
    url = f"https://www.youtube.com/results?search_query={query}"
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        resp.raise_for_status()
        # YouTube embeds video IDs in the page source as JSON
        match = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def enrich_youtube_ids(tracks, limit=50, on_progress=None):
    """Find YouTube video IDs for tracks that don't have one."""
    needs_id = [t for t in tracks if not t.get("youtube_id")]
    if not needs_id:
        return 0

    batch = needs_id[:limit]
    total = len(batch)
    enriched = 0
    for i, t in enumerate(batch, 1):
        if on_progress:
            on_progress(f"Enriching YouTube IDs... {i}/{total}")
        vid = search_youtube_id(t["artist"], t["title"])
        if vid:
            t["youtube_id"] = vid
            enriched += 1
        time.sleep(0.5)  # be polite

    return enriched


# ---------------------------------------------------------------------------
# Main fetch orchestrator
# ---------------------------------------------------------------------------

def fetch_all(config=None, on_progress=None):
    """Fetch from all configured sources and merge into DB."""
    def progress(msg):
        print(f"  {msg}")
        if on_progress:
            on_progress(msg)

    if config is None:
        config = load_config()

    existing = load_discovered_db()

    # Import seed tracks if DB is empty
    if not existing:
        seeds = import_seed_tracks()
        if seeds:
            existing, seed_count = merge_tracks(existing, seeds)
            progress(f"[seed] Imported {seed_count} curated tracks")

    total_added = 0
    source_results = {}

    for genre in config.get("genres", []):
        genre_name = genre["name"]
        progress(f"[{genre_name}] Fetching YouTube channels...")
        yt_tracks = fetch_youtube(genre)
        existing, added = merge_tracks(existing, yt_tracks)
        total_added += added
        source_results[f"youtube:{genre_name}"] = {"fetched": len(yt_tracks), "new": added}
        progress(f"[{genre_name}] YouTube: {len(yt_tracks)} found, {added} new")

        progress(f"[{genre_name}] Fetching Reddit...")
        reddit_tracks = fetch_reddit(genre)
        existing, added = merge_tracks(existing, reddit_tracks)
        total_added += added
        source_results[f"reddit:{genre_name}"] = {"fetched": len(reddit_tracks), "new": added}
        progress(f"[{genre_name}] Reddit: {len(reddit_tracks)} found, {added} new")

        progress(f"[{genre_name}] Fetching Deezer playlists & searches...")
        deezer_tracks = fetch_deezer(genre)
        existing, added = merge_tracks(existing, deezer_tracks)
        total_added += added
        source_results[f"deezer:{genre_name}"] = {"fetched": len(deezer_tracks), "new": added}
        progress(f"[{genre_name}] Deezer: {len(deezer_tracks)} found, {added} new")

    # Enrich Deezer release dates
    progress("Enriching release dates...")
    dz_enriched = enrich_deezer_dates(existing, limit=80, on_progress=on_progress)
    source_results["enriched_dates"] = {"new": dz_enriched}
    progress(f"Enriched {dz_enriched} release dates")

    # Enrich tracks missing YouTube IDs
    progress("Enriching YouTube IDs...")
    yt_enriched = enrich_youtube_ids(existing, limit=50, on_progress=on_progress)
    source_results["enriched_youtube"] = {"new": yt_enriched}
    progress(f"Enriched {yt_enriched} YouTube IDs")

    save_discovered_db(existing)

    return {
        "total_tracks": len(existing),
        "new_tracks": total_added,
        "sources": source_results,
    }


if __name__ == "__main__":
    print("\nMusic Discoverer — Source Fetcher\n")
    result = fetch_all()
    print(f"\nDone: {result['total_tracks']} total tracks, {result['new_tracks']} new")
