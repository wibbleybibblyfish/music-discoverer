#!/usr/bin/env python3
"""Music Discovernator — Web server with multi-source discovery and smart recommendations."""

import json
import random
import threading
import time
from collections import defaultdict
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

PORT = 8138
SCRIPT_DIR = Path(__file__).parent
RATINGS_FILE = SCRIPT_DIR / "ratings.json"
DISCOVERED_FILE = SCRIPT_DIR / "discovered.json"
CONFIG_FILE = SCRIPT_DIR / "config.json"


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_tracks():
    if DISCOVERED_FILE.exists():
        with open(DISCOVERED_FILE) as f:
            return json.load(f)
    return []


def load_ratings():
    if RATINGS_FILE.exists():
        with open(RATINGS_FILE) as f:
            return json.load(f)
    return {}


def save_ratings(ratings):
    with open(RATINGS_FILE, "w") as f:
        json.dump(ratings, f, indent=2)


def build_preference_profile(tracks, ratings):
    if not ratings:
        return None

    rated_tracks = []
    tracks_by_id = {t["id"]: t for t in tracks}
    for tid, rdata in ratings.items():
        if rdata.get("skipped"):
            continue
        t = tracks_by_id.get(tid)
        if t:
            rated_tracks.append({**t, "rating": rdata["rating"]})

    if not rated_tracks:
        return None

    profile = {
        "subgenre_scores": defaultdict(lambda: {"total": 0, "count": 0}),
        "energy_scores": defaultdict(lambda: {"total": 0, "count": 0}),
        "artist_scores": defaultdict(lambda: {"total": 0, "count": 0}),
        "vocalist_scores": defaultdict(lambda: {"total": 0, "count": 0}),
        "bpm_weighted_sum": 0,
        "bpm_weight_total": 0,
        "energy_weighted_sum": 0,
        "energy_weight_total": 0,
    }

    for t in rated_tracks:
        r = t["rating"]
        weight = r / 5.0

        sg = t.get("subgenre", "")
        if sg:
            s = profile["subgenre_scores"][sg]
            s["total"] += r
            s["count"] += 1

        energy = t.get("energy", 0)
        if energy:
            e = profile["energy_scores"][energy]
            e["total"] += r
            e["count"] += 1
            profile["energy_weighted_sum"] += energy * weight
            profile["energy_weight_total"] += weight

        a = profile["artist_scores"][t["artist"]]
        a["total"] += r
        a["count"] += 1

        for v in t.get("vocalists", []):
            vg = profile["vocalist_scores"][v]
            vg["total"] += r
            vg["count"] += 1

        bpm = t.get("bpm", 0)
        if bpm:
            profile["bpm_weighted_sum"] += bpm * weight
            profile["bpm_weight_total"] += weight

    return profile


def score_track(track, profile):
    if profile is None:
        return random.random() * 2, ["New discovery"]

    score = 0.0
    reasons = []

    # Subgenre preference (0-2)
    sg = track.get("subgenre", "")
    if sg:
        sg_data = profile["subgenre_scores"].get(sg)
        if sg_data and sg_data["count"] > 0:
            sg_avg = sg_data["total"] / sg_data["count"]
            score += (sg_avg / 5.0) * 2.0
            if sg_avg >= 4:
                reasons.append(f"You love {sg}")
        else:
            score += 0.8
            reasons.append(f"Explore {sg}")

    # Energy proximity (0-1.5)
    energy = track.get("energy", 0)
    if energy and profile["energy_weight_total"] > 0:
        preferred = profile["energy_weighted_sum"] / profile["energy_weight_total"]
        dist = abs(energy - preferred)
        score += max(0, 1.5 - (dist * 0.3))
        if dist < 1:
            reasons.append("Matches your energy")

    # BPM proximity (0-1)
    bpm = track.get("bpm", 0)
    if bpm and profile["bpm_weight_total"] > 0:
        preferred_bpm = profile["bpm_weighted_sum"] / profile["bpm_weight_total"]
        dist = abs(bpm - preferred_bpm)
        score += max(0, 1.0 - (dist * 0.05))

    # Artist affinity (0-2)
    ag = profile["artist_scores"].get(track["artist"])
    if ag and ag["count"] > 0:
        avg = ag["total"] / ag["count"]
        score += (avg / 5.0) * 2.0
        if avg >= 4:
            reasons.append(f"You rate {track['artist']} highly")
    else:
        score += 0.5
        reasons.append("New artist")

    # Vocalist affinity (0-1.5)
    best_v_score = 0
    best_v = None
    for v in track.get("vocalists", []):
        vg = profile["vocalist_scores"].get(v)
        if vg and vg["count"] > 0:
            v_avg = vg["total"] / vg["count"]
            v_score = (v_avg / 5.0) * 1.5
            if v_score > best_v_score:
                best_v_score = v_score
                best_v = v
    if best_v:
        score += best_v_score
        if best_v_score > 1.0:
            reasons.append(f"Features {best_v}")
    elif track.get("vocalists"):
        score += 0.3

    # Freshness bonus — prefer recently discovered tracks
    source_type = track.get("source_type", "")
    if source_type in ("youtube", "deezer", "reddit"):
        score += 0.5
        if not reasons or "New" not in reasons[0]:
            reasons.insert(0, "Fresh discovery")

    # Multi-source bonus
    sources = track.get("sources", [])
    if len(sources) > 1:
        score += 0.3 * len(sources)
        reasons.append(f"Found on {len(sources)} sources")

    # Diversity noise
    score += random.uniform(0, 0.8)

    return score, reasons[:3]


def get_recommendations(tracks, ratings, count=9, filters=None, sort="newest"):
    profile = build_preference_profile(tracks, ratings)
    rated_ids = set(ratings.keys())

    candidates = [t for t in tracks if t["id"] not in rated_ids]

    if filters:
        if filters.get("subgenre"):
            candidates = [t for t in candidates if t.get("subgenre") == filters["subgenre"]]
        if filters.get("source_type"):
            candidates = [t for t in candidates if t.get("source_type") == filters["source_type"]]
        if filters.get("era"):
            era_ranges = {"90s": (1990, 1999), "00s": (2000, 2009), "10s": (2010, 2019), "20s": (2020, 2029)}
            if filters["era"] in era_ranges:
                lo, hi = era_ranges[filters["era"]]
                candidates = [t for t in candidates if lo <= t.get("year", 2020) <= hi]
        if filters.get("min_energy"):
            candidates = [t for t in candidates if t.get("energy", 0) >= int(filters["min_energy"])]
        if filters.get("genre"):
            g = filters["genre"]
            candidates = [t for t in candidates if t.get("genre") == g or g in t.get("genres", [])]

    if sort == "newest":
        # Sort newest per source by release date, then interleave so we get a mix
        by_source = defaultdict(list)
        for t in candidates:
            by_source[t.get("source_type", "unknown")].append(t)
        for s in by_source.values():
            s.sort(key=lambda t: t.get("release_date") or t.get("discovered_at", ""), reverse=True)

        result = []
        source_iters = {k: iter(v) for k, v in by_source.items()}
        keys = list(source_iters.keys())
        random.shuffle(keys)
        while len(result) < count and source_iters:
            exhausted = []
            for k in keys:
                if k not in source_iters:
                    continue
                t = next(source_iters[k], None)
                if t:
                    result.append({**t, "_score": 0, "_reasons": []})
                    if len(result) >= count:
                        break
                else:
                    exhausted.append(k)
            for k in exhausted:
                del source_iters[k]
                keys.remove(k)
        return result

    if sort == "random":
        random.shuffle(candidates)
        return [{**t, "_score": 0, "_reasons": []} for t in candidates[:count]]

    # "smart" — score-based recommendation
    scored = []
    for t in candidates:
        s, reasons = score_track(t, profile)
        scored.append({**t, "_score": s, "_reasons": reasons})

    scored.sort(key=lambda x: -x["_score"])

    pool_size = min(len(scored), count * 3)
    pool = scored[:pool_size]
    random.shuffle(pool)

    return pool[:count]


def build_stats(tracks, ratings):
    rated = {k: v for k, v in ratings.items() if not v.get("skipped")}
    skipped = {k: v for k, v in ratings.items() if v.get("skipped")}

    source_counts = defaultdict(int)
    for t in tracks:
        source_counts[t.get("source_type", "unknown")] += 1

    subgenre_counts = defaultdict(int)
    subgenre_ratings = defaultdict(list)
    tracks_by_id = {t["id"]: t for t in tracks}
    for t in tracks:
        sg = t.get("subgenre", "")
        if sg:
            subgenre_counts[sg] += 1
    for tid, rdata in rated.items():
        t = tracks_by_id.get(tid)
        if t and t.get("subgenre"):
            subgenre_ratings[t["subgenre"]].append(rdata["rating"])

    subgenre_stats = {}
    for sg in subgenre_counts:
        r = subgenre_ratings.get(sg, [])
        subgenre_stats[sg] = {
            "total": subgenre_counts[sg],
            "rated": len(r),
            "avg_rating": round(sum(r) / len(r), 1) if r else None,
        }

    avg_rating = None
    if rated:
        avg_rating = round(sum(v["rating"] for v in rated.values()) / len(rated), 1)

    genre_counts = defaultdict(int)
    for t in tracks:
        for g in t.get("genres", [t.get("genre", "unknown")]):
            genre_counts[g] += 1

    return {
        "total_tracks": len(tracks),
        "rated": len(rated),
        "skipped": len(skipped),
        "unrated": len(tracks) - len(ratings),
        "avg_rating": avg_rating,
        "subgenres": subgenre_stats,
        "sources": dict(source_counts),
        "genres_breakdown": dict(genre_counts),
    }


def build_sources_info():
    """Return all configured sources with per-source track counts."""
    config = load_config()
    tracks = load_tracks()

    # Count tracks per specific source string
    source_detail = defaultdict(int)
    for t in tracks:
        for s in t.get("sources", [t.get("source", "unknown")]):
            source_detail[s] += 1

    sources = []

    for genre in config.get("genres", []):
        genre_name = genre["name"]
        genre_sources = genre.get("sources", {})

        # YouTube channels
        for ch in genre_sources.get("youtube", []):
            key = f"youtube:{ch['name']}"
            sources.append({
                "type": "youtube",
                "name": ch["name"],
                "genre": genre_name,
                "detail": ch.get("focus", ""),
                "enabled": ch.get("enabled", True),
                "tracks": source_detail.get(key, 0),
                "configured": True,
            })

        # Reddit
        for sub_cfg in genre_sources.get("reddit", []):
            key = f"reddit:r/{sub_cfg['sub']}"
            sources.append({
                "type": "reddit",
                "name": sub_cfg["name"],
                "genre": genre_name,
                "detail": "subreddit",
                "enabled": sub_cfg.get("enabled", True),
                "tracks": source_detail.get(key, 0),
                "configured": True,
            })

        # Deezer playlists
        for pl in genre_sources.get("deezer_playlists", []):
            key = f"deezer:playlist:{pl['name']}"
            sources.append({
                "type": "deezer",
                "name": pl["name"],
                "genre": genre_name,
                "detail": "playlist",
                "enabled": pl.get("enabled", True),
                "tracks": source_detail.get(key, 0),
                "configured": True,
            })

        # Deezer searches
        searches = genre_sources.get("deezer_searches", [])
        if searches:
            sources.append({
                "type": "deezer",
                "name": "Search",
                "genre": genre_name,
                "detail": ", ".join(searches),
                "enabled": True,
                "tracks": source_detail.get("deezer:search", 0),
                "configured": True,
            })

    # Curated
    sources.append({
        "type": "curated",
        "name": "Curated Seed DB",
        "genre": "",
        "detail": "hand-picked classics",
        "enabled": True,
        "tracks": source_detail.get("curated", 0),
        "configured": True,
    })

    return sources


# Background refresh
_refresh_lock = threading.Lock()
_refresh_status = {"running": False, "last_result": None, "last_time": None, "progress": ""}


def do_refresh():
    global _refresh_status
    with _refresh_lock:
        if _refresh_status["running"]:
            return {"status": "already_running"}
        _refresh_status["running"] = True

    try:
        from sources import fetch_all
        def on_progress(msg):
            _refresh_status["progress"] = msg
        result = fetch_all(on_progress=on_progress)
        _refresh_status["last_result"] = result
        _refresh_status["last_time"] = __import__("datetime").datetime.now().isoformat()
        _refresh_status["progress"] = ""
        return result
    finally:
        _refresh_status["running"] = False


class Handler(SimpleHTTPRequestHandler):
    def send_redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            config = load_config()
            if not config.get("genres"):
                self.send_redirect("/setup")
            else:
                self.serve_file("index.html", "text/html")
        elif parsed.path == "/setup":
            self.serve_file("setup.html", "text/html")
        elif parsed.path == "/api/tracks":
            self.send_json(load_tracks())
        elif parsed.path == "/api/ratings":
            self.send_json(load_ratings())
        elif parsed.path == "/api/recommend":
            params = parse_qs(parsed.query)
            count = int(params.get("count", ["9"])[0])
            filters = {}
            for key in ["subgenre", "era", "min_energy", "source_type", "genre"]:
                if key in params:
                    filters[key] = params[key][0]
            tracks = load_tracks()
            ratings = load_ratings()
            sort = params.get("sort", ["newest"])[0]
            recs = get_recommendations(tracks, ratings, count, filters or None, sort=sort)
            self.send_json(recs)
        elif parsed.path == "/api/stats":
            tracks = load_tracks()
            ratings = load_ratings()
            self.send_json(build_stats(tracks, ratings))
        elif parsed.path == "/api/refresh/status":
            self.send_json(_refresh_status)
        elif parsed.path == "/api/config":
            self.send_json(load_config())
        elif parsed.path == "/api/sources":
            self.send_json(build_sources_info())
        elif parsed.path == "/api/preview":
            params = parse_qs(parsed.query)
            deezer_id = params.get("deezer_id", [None])[0]
            if not deezer_id:
                self.send_json({"preview_url": ""})
                return
            try:
                import requests as req
                resp = req.get(f"https://api.deezer.com/track/{deezer_id}", timeout=10)
                url = resp.json().get("preview", "") if resp.status_code == 200 else ""
                self.send_json({"preview_url": url})
            except Exception:
                self.send_json({"preview_url": ""})
        elif parsed.path == "/settings":
            self.serve_file("settings.html", "text/html")
        elif parsed.path in ("/favicon.ico", "/logo-128.png", "/logo-256.png"):
            filepath = SCRIPT_DIR / parsed.path.lstrip("/")
            if filepath.exists():
                ct = "image/x-icon" if parsed.path.endswith(".ico") else "image/png"
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.end_headers()
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/rate":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            ratings = load_ratings()
            ratings[body["id"]] = {"rating": body["rating"], "skipped": False}
            save_ratings(ratings)
            self.send_json({"ok": True})
        elif parsed.path == "/api/skip":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            ratings = load_ratings()
            ratings[body["id"]] = {"rating": 0, "skipped": True}
            save_ratings(ratings)
            self.send_json({"ok": True})
        elif parsed.path == "/api/reset":
            save_ratings({})
            self.send_json({"ok": True})
        elif parsed.path == "/api/refresh":
            thread = threading.Thread(target=do_refresh, daemon=True)
            thread.start()
            self.send_json({"status": "started"})
        elif parsed.path == "/api/discover":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            genre_name = body.get("genre", "").strip()
            if not genre_name:
                self.send_json({"error": "genre is required"})
                return
            from sources import discover_sources
            results = discover_sources(genre_name)
            self.send_json(results)
        elif parsed.path == "/api/genres":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            genre_name = body.get("name", "").strip()
            if not genre_name:
                self.send_json({"error": "name is required"})
                return
            genre_obj = {
                "name": genre_name,
                "sources": body.get("sources", {
                    "youtube": [],
                    "reddit": [],
                    "deezer_playlists": [],
                    "deezer_searches": [],
                }),
            }
            config = load_config()
            # Check for duplicate
            existing_names = [g["name"].lower() for g in config.get("genres", [])]
            if genre_name.lower() in existing_names:
                self.send_json({"error": f"genre '{genre_name}' already exists"})
                return
            config.setdefault("genres", []).append(genre_obj)
            save_config(config)
            # Trigger background fetch for just this genre (skip enrichment)
            def fetch_new_genre():
                try:
                    from sources import (fetch_youtube, fetch_reddit, fetch_deezer,
                                         load_discovered_db, save_discovered_db, merge_tracks)
                    existing = load_discovered_db()
                    for fetcher in (fetch_youtube, fetch_reddit, fetch_deezer):
                        tracks = fetcher(genre_obj)
                        existing, _ = merge_tracks(existing, tracks)
                    save_discovered_db(existing)
                    print(f"  [bg-fetch] Done fetching '{genre_name}'")
                except Exception as e:
                    print(f"  [bg-fetch] Error fetching new genre: {e}")
            thread = threading.Thread(target=fetch_new_genre, daemon=True)
            thread.start()
            self.send_json({"ok": True})
        elif parsed.path == "/api/genres/delete":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            genre_name = body.get("name", "").strip()
            if not genre_name:
                self.send_json({"error": "name is required"})
                return
            config = load_config()
            original_count = len(config.get("genres", []))
            config["genres"] = [g for g in config.get("genres", []) if g["name"].lower() != genre_name.lower()]
            if len(config["genres"]) == original_count:
                self.send_json({"error": f"genre '{genre_name}' not found"})
                return
            save_config(config)
            # Remove tracks that only belong to this genre
            from sources import load_discovered_db, save_discovered_db
            tracks = load_discovered_db()
            kept = []
            removed_ids = set()
            for t in tracks:
                genres = t.get("genres", [t.get("genre", "")])
                remaining = [g for g in genres if g.lower() != genre_name.lower()]
                if remaining:
                    t["genres"] = remaining
                    t["genre"] = remaining[0]
                    kept.append(t)
                else:
                    removed_ids.add(t["id"])
            save_discovered_db(kept)
            # Clean up ratings for removed tracks
            if removed_ids:
                ratings = load_ratings()
                ratings = {k: v for k, v in ratings.items() if k not in removed_ids}
                save_ratings(ratings)
            self.send_json({"ok": True, "tracks_removed": len(removed_ids)})
        else:
            self.send_error(404)

    def do_PUT(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/config/sources":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            save_config(body)
            self.send_json({"ok": True})
        else:
            self.send_error(404)

    def do_DELETE(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/tracks":
            from sources import save_discovered_db
            save_discovered_db([])
            self.send_json({"ok": True})
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def serve_file(self, filename, content_type):
        filepath = SCRIPT_DIR / filename
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass


def auto_refresh_loop():
    """Background thread that refreshes sources on a schedule."""
    config = load_config()
    interval = config.get("fetch_interval_hours", 6) * 3600
    while True:
        time.sleep(interval)
        print(f"  [auto-refresh] Running scheduled refresh...")
        try:
            do_refresh()
            print(f"  [auto-refresh] Done.")
        except Exception as e:
            print(f"  [auto-refresh] Error: {e}")


def main():
    # Auto-fetch on startup if DB is empty or stale
    tracks = load_tracks()
    if not tracks:
        print("  No tracks in database — running initial fetch...")
        do_refresh()
    else:
        print(f"  {len(tracks)} tracks in database")

    # Start background auto-refresh
    config = load_config()
    interval_hrs = config.get("fetch_interval_hours", 6)
    refresh_thread = threading.Thread(target=auto_refresh_loop, daemon=True)
    refresh_thread.start()
    print(f"  Auto-refresh every {interval_hrs} hours")

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  Music Discovernator")
    print(f"  http://localhost:{PORT}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
