"""Download every ranked replay listed on playeggball.com.

Walks /replays/data?kind=ranked page by page (25 games a page, newest first) until a page comes back empty,
then downloads each game's file from /replays/file/<id>?save=1 and stores it gzipped.
Single-threaded, waits GAP seconds between downloads, stops on rate-limit or server errors.
Resumable: games already saved are skipped, so re-running only fetches new ones.

usage: fetch_playeggball_replays.py [out_dir]   (default ~/tagpro-analytics/data/playeggball)
out_dir gets games.json (every listed game's info) and replays/<id>.eggball-replay.gz
"""
import gzip, json, os, sys, time
import requests

OUT = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/tagpro-analytics/data/playeggball")
BASE = "https://playeggball.com"
GAP = 2.0        # seconds between replay downloads
PAGE_GAP = 1.0   # seconds between listing pages
KIND = "ranked"  # /replays/data filter; the site only lists its newest 1000 games, filtered or not

s = requests.Session()
s.headers["User-Agent"] = "eggball-replay-archiver (1 download / 2 s)"

def get(path, **params):
    r = s.get(BASE + path, params=params, timeout=60)
    if r.status_code == 429 or r.status_code >= 500:
        sys.exit(f"stopping: HTTP {r.status_code} on {path} {params}")
    return r

os.makedirs(os.path.join(OUT, "replays"), exist_ok=True)

# 1. list every game
games = {}
page = 0
while True:
    r = get("/replays/data", kind=KIND, page=page)
    if r.status_code != 200:
        sys.exit(f"stopping: HTTP {r.status_code} listing page {page}")
    rows = r.json().get("games", [])
    if not rows:
        break
    for g in rows:
        games.setdefault(g["id"], g)  # new games arriving mid-walk push old ones down a page: dedupe
    print(f"page {page}: {len(games)} games so far", flush=True)
    page += 1
    time.sleep(PAGE_GAP)

index_path = os.path.join(OUT, "games.json")
old = json.load(open(index_path)) if os.path.exists(index_path) else []
merged = {g["id"]: g for g in old}
merged.update(games)
json.dump(sorted(merged.values(), key=lambda g: g["at"]), open(index_path, "w"))

# 2. download the ones not saved yet
def dest(gid):
    return os.path.join(OUT, "replays", gid + ".eggball-replay.gz")

todo = [gid for gid in games if not os.path.exists(dest(gid))]
print(f"{len(games)} listed, {len(games) - len(todo)} already saved, {len(todo)} to download "
      f"(~{len(todo) * GAP / 60:.0f} min)", flush=True)

for i, gid in enumerate(todo, 1):
    r = get(f"/replays/file/{gid}", save=1)
    if r.status_code == 404:
        print(f"{i}/{len(todo)} {gid}: not found, skipped", flush=True)
    elif r.status_code != 200:
        sys.exit(f"stopping: HTTP {r.status_code} downloading {gid}")
    else:
        tmp = dest(gid) + ".part"
        with gzip.open(tmp, "wb") as f:
            f.write(r.content)
        os.replace(tmp, dest(gid))  # only complete files get the final name
        print(f"{i}/{len(todo)} {gid} {games[gid]['map']} {len(r.content) // 1024} KB", flush=True)
    time.sleep(GAP)

print("done", flush=True)
