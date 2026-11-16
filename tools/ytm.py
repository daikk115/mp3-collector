#!/usr/bin/env python3
"""Official-catalog lookups via YouTube Music (label-distributed tracks only).
  python3 -I ytm.py resolve in.csv out.csv      # adds videoId,album,artists for matched rows; FAIL lines printed
  python3 -I ytm.py catalog singers.txt out_dir # dumps each singer's official song list to out_dir/<Singer>.tsv
"""
import csv, os, sys, re, unicodedata, threading
from concurrent.futures import ThreadPoolExecutor
from ytmusicapi import YTMusic

_tl = threading.local()
def yt():
    if not hasattr(_tl, "y"): _tl.y = YTMusic()
    return _tl.y

BAD = {"karaoke", "beat", "remix", "instrumental", "lofi", "edm", "remake", "tiktok"}
BAD_PHRASE = ["lien khuc", "hoa tau", "nhac khong loi", "tan co"]

def ascii_(s):
    return unicodedata.normalize("NFKD", s.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
def norm(s):
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", ascii_(s).lower()).split())
def dur(s):
    try:
        p = [int(x) for x in (s or "0").split(":")]
        return sum(v * 60 ** i for i, v in enumerate(reversed(p)))
    except ValueError:
        return 0
def clean_title(t):  # drop "(Tân nhạc)", "(Remastered)" etc.
    return norm(re.sub(r"[\(\[].*?[\)\]]", " ", t))

def artist_ok(singer, artists):
    s = norm(singer)
    return any(s == norm(a) or (" " + s + " ") in (" " + norm(a) + " ") for a in artists)

def bad_title(t):
    n = norm(t); w = set(n.split())
    return bool(w & BAD) or any(p in n for p in BAD_PHRASE)

def resolve(singer, song):
    want = norm(song)
    res = yt().search(f"{singer} {song}", filter="songs", limit=20)
    cands = []
    for r in res:
        arts = [a["name"] for a in r.get("artists") or []]
        t = r.get("title") or ""
        d = dur(r.get("duration"))
        if not r.get("videoId") or not artist_ok(singer, arts) or bad_title(t) or not (110 <= d <= 600):
            continue
        ct = clean_title(t)
        if ct == want: sc = 3
        elif want in ct and len(ct.split()) <= len(want.split()) + 3: sc = 1
        else: continue
        if len(arts) == 1: sc += 1  # prefer solo recording
        cands.append((sc, -res.index(r), r, arts))
    if not cands: return None
    sc, _, r, arts = max(cands, key=lambda x: (x[0], x[1]))
    return {"videoId": r["videoId"], "album": (r.get("album") or {}).get("name", ""), "artists": " & ".join(arts)}

def cmd_resolve(inp, out):
    rows = list(csv.DictReader(open(inp, encoding="utf-8")))
    def f(r):
        try: return r, resolve(r["singer"].strip(), r["song"].strip())
        except Exception as e: return r, None
    with ThreadPoolExecutor(6) as ex: res = list(ex.map(f, rows))
    fields = ["singer", "song", "topic", "videoId", "album", "artists"]
    seen, ok = set(), 0
    with open(out, "w", encoding="utf-8", newline="") as fo:
        w = csv.DictWriter(fo, fields); w.writeheader()
        for r, m in res:
            if not m:
                print("FAIL", r["singer"], "|", r["song"]); continue
            key = (norm(r["singer"]), norm(r["song"]))
            if m["videoId"] in seen or key in seen: continue
            seen |= {m["videoId"], key}; ok += 1
            w.writerow({"singer": r["singer"].strip(), "song": r["song"].strip(), "topic": r.get("topic", ""), **m})
    print("OK", ok, "/", len(rows))

def catalog(singer):
    y = yt()
    arts = [a for a in y.search(singer, filter="artists", limit=5) if norm(a.get("artist", "")) == norm(singer)]
    if not arts: return []
    a = y.get_artist(arts[0]["browseId"])
    sec = a.get("songs") or {}
    items = sec.get("results") or []
    if sec.get("browseId"):
        try: items = y.get_playlist(sec["browseId"], limit=300)["tracks"]
        except Exception: pass
    out = []
    for t in items:
        arts_ = [x["name"] for x in t.get("artists") or []]
        d = t.get("duration_seconds") or dur(t.get("duration"))
        if t.get("videoId") and artist_ok(singer, arts_) and not bad_title(t["title"]) and 110 <= d <= 600:
            out.append((t["title"], " & ".join(arts_), (t.get("album") or {}).get("name", ""), d, t["videoId"]))
    return out

def cmd_catalog(lst, outdir):
    os.makedirs(outdir, exist_ok=True)
    singers = [l.strip() for l in open(lst, encoding="utf-8") if l.strip()]
    def f(s):
        try: rows = catalog(s)
        except Exception as e: rows = []
        with open(os.path.join(outdir, s.replace(" ", "_") + ".tsv"), "w", encoding="utf-8") as fo:
            for r in rows: fo.write("\t".join(map(str, r)) + "\n")
        print(len(rows), s, flush=True)
    with ThreadPoolExecutor(4) as ex: list(ex.map(f, singers))

if __name__ == "__main__":
    {"resolve": cmd_resolve, "catalog": cmd_catalog}[sys.argv[1]](*sys.argv[2:])
