#!/usr/bin/env python3
"""Vocal Trance Recommender — zero API keys, curated database with Spotify & YouTube links."""

import argparse
import json
import os
import random
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

SCRIPT_DIR = Path(__file__).parent
TRACKS_FILE = SCRIPT_DIR / "tracks.json"
HISTORY_FILE = SCRIPT_DIR / "history.json"

SUBGENRES = ["classic", "uplifting", "progressive", "balearic", "crossover"]
ENERGY_LABELS = {
    range(1, 4): "Chill",
    range(4, 6): "Mellow",
    range(6, 8): "Energetic",
    range(8, 10): "Peak Time",
    range(10, 11): "Absolute Banger",
}


def load_tracks():
    with open(TRACKS_FILE) as f:
        return json.load(f)


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return set(tuple(x) for x in json.load(f))
    return set()


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump([list(x) for x in history], f)


def energy_label(level):
    for r, label in ENERGY_LABELS.items():
        if level in r:
            return label
    return "Unknown"


def spotify_url(artist, title):
    q = quote_plus(f"{artist} {title}")
    return f"https://open.spotify.com/search/{q}"


def youtube_url(artist, title):
    q = quote_plus(f"{artist} - {title}")
    return f"https://www.youtube.com/results?search_query={q}"


def track_key(track):
    return (track["artist"], track["title"])


def format_track(track, index=None):
    prefix = f"  {index}." if index is not None else " "
    vocalists = ", ".join(track["vocalists"]) if track["vocalists"] else ""
    vocal_str = f" ft. {vocalists}" if vocalists else ""
    energy = energy_label(track["energy"])

    lines = [
        f"{prefix} {track['artist']} — {track['title']}{vocal_str}",
        f"     {track['subgenre'].title()} | {track['bpm']} BPM | {energy} | {track['year']}",
        f"     Spotify: {spotify_url(track['artist'], track['title'])}",
        f"     YouTube: {youtube_url(track['artist'], track['title'])}",
    ]
    return "\n".join(lines)


def filter_tracks(tracks, args, history):
    filtered = list(tracks)

    if args.subgenre:
        filtered = [t for t in filtered if t["subgenre"] == args.subgenre]

    if args.artist:
        q = args.artist.lower()
        filtered = [t for t in filtered if q in t["artist"].lower()]

    if args.vocalist:
        q = args.vocalist.lower()
        filtered = [t for t in filtered if any(q in v.lower() for v in t["vocalists"])]

    if args.min_energy:
        filtered = [t for t in filtered if t["energy"] >= args.min_energy]

    if args.max_energy:
        filtered = [t for t in filtered if t["energy"] <= args.max_energy]

    if args.min_bpm:
        filtered = [t for t in filtered if t["bpm"] >= args.min_bpm]

    if args.max_bpm:
        filtered = [t for t in filtered if t["bpm"] <= args.max_bpm]

    if args.era:
        era_ranges = {
            "90s": (1990, 1999),
            "00s": (2000, 2009),
            "10s": (2010, 2019),
            "20s": (2020, 2029),
        }
        if args.era in era_ranges:
            lo, hi = era_ranges[args.era]
            filtered = [t for t in filtered if lo <= t["year"] <= hi]

    if not args.include_heard:
        filtered = [t for t in filtered if track_key(t) not in history]

    return filtered


def cmd_recommend(args):
    tracks = load_tracks()
    history = load_history()
    filtered = filter_tracks(tracks, args, history)

    if not filtered:
        if not args.include_heard:
            print("No unheard tracks match your filters. Try --include-heard or --reset-history.")
        else:
            print("No tracks match your filters.")
        return

    count = min(args.count, len(filtered))
    picks = random.sample(filtered, count)

    print(f"\n  Vocal Trance Recommendations ({count} tracks)\n")
    for i, track in enumerate(picks, 1):
        print(format_track(track, i))
        print()

    if not args.no_save:
        for t in picks:
            history.add(track_key(t))
        save_history(history)

    if args.open:
        for t in picks:
            url = spotify_url(t["artist"], t["title"]) if args.open == "spotify" else youtube_url(t["artist"], t["title"])
            webbrowser.open(url)


def cmd_stats(args):
    tracks = load_tracks()
    history = load_history()

    print(f"\n  Database: {len(tracks)} tracks")
    print(f"  Heard:    {len(history)} tracks")
    print(f"  Unheard:  {len(tracks) - len(history)} tracks")

    print("\n  By subgenre:")
    for sg in SUBGENRES:
        n = len([t for t in tracks if t["subgenre"] == sg])
        if n:
            print(f"    {sg.title():15s} {n}")

    artists = {}
    for t in tracks:
        artists[t["artist"]] = artists.get(t["artist"], 0) + 1
    top = sorted(artists.items(), key=lambda x: -x[1])[:10]
    print("\n  Top artists:")
    for artist, count in top:
        print(f"    {artist:30s} {count}")

    vocalists = {}
    for t in tracks:
        for v in t["vocalists"]:
            vocalists[v] = vocalists.get(v, 0) + 1
    top_v = sorted(vocalists.items(), key=lambda x: -x[1])[:10]
    print("\n  Top vocalists:")
    for vocalist, count in top_v:
        print(f"    {vocalist:30s} {count}")
    print()


def cmd_reset(args):
    if HISTORY_FILE.exists():
        os.remove(HISTORY_FILE)
        print("History cleared.")
    else:
        print("No history to clear.")


def cmd_artists(args):
    tracks = load_tracks()
    artists = sorted(set(t["artist"] for t in tracks))
    print(f"\n  Artists ({len(artists)}):\n")
    for a in artists:
        print(f"    {a}")
    print()


def cmd_vocalists(args):
    tracks = load_tracks()
    vocalists = sorted(set(v for t in tracks for v in t["vocalists"]))
    print(f"\n  Vocalists ({len(vocalists)}):\n")
    for v in vocalists:
        print(f"    {v}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Vocal Trance Recommender",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          5 random recommendations
  %(prog)s -n 10                    10 random recommendations
  %(prog)s --subgenre uplifting     only uplifting trance
  %(prog)s --era 00s                classic 2000s era
  %(prog)s --artist "Above"         tracks from Above & Beyond
  %(prog)s --vocalist "Emma"        tracks featuring Emma Hewitt
  %(prog)s --min-energy 8           peak-time bangers only
  %(prog)s --open spotify           open results in Spotify
  %(prog)s --open youtube           open results in YouTube
  %(prog)s stats                    show database statistics
  %(prog)s artists                  list all artists
  %(prog)s vocalists                list all vocalists
  %(prog)s reset                    clear recommendation history
        """,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("stats", help="Show database statistics")
    sub.add_parser("reset", help="Clear recommendation history")
    sub.add_parser("artists", help="List all artists")
    sub.add_parser("vocalists", help="List all vocalists")

    parser.add_argument("-n", "--count", type=int, default=5, help="Number of recommendations (default: 5)")
    parser.add_argument("--subgenre", choices=SUBGENRES, help="Filter by subgenre")
    parser.add_argument("--artist", help="Filter by artist name (partial match)")
    parser.add_argument("--vocalist", help="Filter by vocalist name (partial match)")
    parser.add_argument("--era", choices=["90s", "00s", "10s", "20s"], help="Filter by decade")
    parser.add_argument("--min-energy", type=int, choices=range(1, 11), metavar="1-10", help="Minimum energy level")
    parser.add_argument("--max-energy", type=int, choices=range(1, 11), metavar="1-10", help="Maximum energy level")
    parser.add_argument("--min-bpm", type=int, help="Minimum BPM")
    parser.add_argument("--max-bpm", type=int, help="Maximum BPM")
    parser.add_argument("--include-heard", action="store_true", help="Include previously recommended tracks")
    parser.add_argument("--no-save", action="store_true", help="Don't save to history")
    parser.add_argument("--open", choices=["spotify", "youtube"], help="Open results in browser")

    args = parser.parse_args()

    if args.command == "stats":
        cmd_stats(args)
    elif args.command == "reset":
        cmd_reset(args)
    elif args.command == "artists":
        cmd_artists(args)
    elif args.command == "vocalists":
        cmd_vocalists(args)
    else:
        cmd_recommend(args)


if __name__ == "__main__":
    main()
