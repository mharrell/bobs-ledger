#!/usr/bin/env python3
"""Fetch YouTube transcripts for each comp's affiliate videos.

For each comp in comps.json, resolve its numeric id, fetch the hsreplay
youtube-affiliate links, and download each video's auto-transcript via yt_dlp.
Saves as transcript_<video_id>.txt (the raw auto-caption text, which we then
mine into per-comp engine guides).

Usage:
    python fetch_transcripts.py [comp_slug ...]   # default: all comps
"""
import glob
import json
import os
import sys

import requests

from scrape_comps import resolve_comp_id, _headers, YOUTUBE_LINKS_URL

_HERE = os.path.dirname(os.path.abspath(__file__))
COMPS = os.path.join(_HERE, "meta", "comps.json")


def fetch_links(comp_id):
    url = YOUTUBE_LINKS_URL.format(id=comp_id)
    r = requests.get(
        url,
        headers=_headers(referer=f"https://hsreplay.net/battlegrounds/comps/{comp_id}/"),
        timeout=30,
    )
    if r.status_code != 200:
        return []
    d = r.json()
    return d.get("results", []) if isinstance(d, dict) else d


def download_transcript(video_id):
    """Download a video's auto-transcript to transcript_<id>.txt. Returns path or None."""
    out = os.path.join(_HERE, f"transcript_{video_id}.txt")
    if os.path.exists(out):
        return out  # already have it
    import yt_dlp
    base = os.path.join(_HERE, f"transcript_{video_id}")
    ydl_opts = {
        "skip_download": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en-orig"],
        "subtitlesformat": "json3",
        "outtmpl": base,
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    jf = next(iter(glob.glob(base + "*.json3")), None)
    if not jf:
        return None
    data = json.load(open(jf, encoding="utf-8"))
    text = "".join(seg.get("utf8", "")
                    for ev in data.get("events", []) for seg in ev.get("segs", []))
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    os.remove(jf)
    return out


def main():
    with open(COMPS, encoding="utf-8") as f:
        comps = json.load(f)
    slugs = sys.argv[1:] or list(comps)
    for slug in slugs:
        try:
            cid = resolve_comp_id(slug)
        except Exception as e:  # noqa: BLE001
            print(f"  {slug}: could not resolve id ({e})")
            continue
        links = fetch_links(cid)
        print(f"== {slug} (id {cid}): {len(links)} videos ==")
        for link in links:
            vid = link.get("video_id")
            if not vid:
                continue
            path = download_transcript(vid)
            status = "ok" if path else "FAILED"
            print(f"  {vid} [{link.get('channel_title')}] {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
