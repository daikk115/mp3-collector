#!/usr/bin/env python3
"""Download picked official tracks -> radio-friendly MP3 grouped by singer.
Usage: python3 -I dl.py picks.csv catalog_all.tsv OUT_DIR [--limit-bytes N] [--workers N]"""
import csv, os, re, sys, shutil, subprocess, tempfile, threading, unicodedata, argparse
from concurrent.futures import ThreadPoolExecutor

def ascii_(s):
    return unicodedata.normalize("NFKD", s.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
def fname(s, n=40):
    t = re.sub(r"[\(\[].*?[\)\]]", " ", s)
    return "_".join(w.capitalize() if w.islower() else w for w in re.sub(r"[^A-Za-z0-9 ]+", " ", ascii_(t)).split())[:n].strip("_")

lock = threading.Lock(); state = {"bytes": 0}

def job(it, out, limit, log):
    dst = os.path.join(out, fname(it["singer"], 30), f'{it["n"]:03d}_{fname(it["title"])}.mp3')
    if os.path.exists(dst): return
    with lock: over = state["bytes"] >= limit
    if over: log(it, "skipped_size_limit"); return
    tmp = tempfile.mkdtemp(dir=os.path.join(out, "..", "_raw"))
    try:
        r = subprocess.run(["yt-dlp", "-q", "-f", "bestaudio", "-o", os.path.join(tmp, "a.%(ext)s"),
                            "https://music.youtube.com/watch?v=" + it["vid"]], capture_output=True, text=True, timeout=600)
        src = os.listdir(tmp)
        if r.returncode or not src: log(it, "download_error"); return
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        part = dst[:-4] + ".part.mp3"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(tmp, src[0]), "-vn", "-map_metadata", "-1",
                            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame",
                            "-b:a", "192k", "-id3v2_version", "3", "-write_xing", "0",
                            "-metadata", f'title={it["title"]}', "-metadata", f'artist={it["artists"]}',
                            "-metadata", f'album={it["album"]}', "-metadata", f'genre={it["topic"]}', part],
                           capture_output=True, text=True, timeout=600)
        if r.returncode: log(it, "convert_error"); return
        os.replace(part, dst)
        with lock: state["bytes"] += os.path.getsize(dst)
        log(it, "ok")
    except Exception as e:
        log(it, "error:" + type(e).__name__)
    finally:
        shutil.rmtree(tmp, True)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("picks"); ap.add_argument("catalog"); ap.add_argument("out")
    ap.add_argument("--limit-bytes", type=int, default=3_500_000_000); ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    cat = {}
    for l in open(a.catalog, encoding="utf-8"):
        i, singer, title, arts, alb, d, vid = l.rstrip("\n").split("\t")
        cat[i] = dict(singer=singer, title=title, artists=arts, album=alb, vid=vid)
    os.makedirs(a.out, exist_ok=True); os.makedirs(os.path.join(a.out, "..", "_raw"), exist_ok=True)
    for root, _, fs in os.walk(a.out):
        state["bytes"] += sum(os.path.getsize(os.path.join(root, f)) for f in fs if f.endswith(".mp3") and ".part" not in f)
    items, cnt, seen = [], {}, set()
    for r in csv.DictReader(open(a.picks, encoding="utf-8")):
        it = cat.get(r["id"].strip())
        if not it or it["vid"] in seen: continue
        seen.add(it["vid"]); cnt[it["singer"]] = cnt.get(it["singer"], 0) + 1
        items.append({**it, "topic": r["topic"].strip(), "n": cnt[it["singer"]]})
    lf = open(os.path.join(a.out, "..", "dl_results.csv"), "a", encoding="utf-8", newline=""); w = csv.writer(lf)
    def log(it, st):
        with lock:
            w.writerow([it["singer"], it["title"], it["topic"], it["vid"], st]); lf.flush()
            print(st, "|", it["singer"], "-", it["title"], flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for it in items: ex.submit(job, it, a.out, a.limit_bytes, log)
    print("TOTAL_BYTES", state["bytes"], "ITEMS", len(items))

if __name__ == "__main__":
    main()
