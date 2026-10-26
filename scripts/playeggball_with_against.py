"""Build with_against.html: every ranked playeggball.com player's wins and losses with and against every other player.

Reads games.json written by fetch_playeggball_replays.py. A player counts in a game only if they were
still in it at the end ("finished"); leavers are left out. Someone who switched teams counts for the
team they finished on.

usage: playeggball_with_against.py [data_dir]   (default ~/tagpro-analytics/data/playeggball)
"""
import collections, json, os, sys

DIR = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/tagpro-analytics/data/playeggball")
# alt name -> main name: the same person on two accounts
MERGE = {"Bambi1": "Bambi", "waoter": "3"}

games = json.load(open(os.path.join(DIR, "games.json")))

def key(p):
    name = MERGE.get(p["name"], p["name"])
    if name in MERGE.values() or p["account"] is None:
        return "name:" + name
    return p["account"]

names = {}  # key -> latest name
record = collections.defaultdict(lambda: [0, 0])
pair = collections.defaultdict(lambda: [0, 0])  # (a, b, "with"/"against") -> [wins, losses] for a
for g in sorted(games, key=lambda g: g["at"]):
    final = {}
    for p in g["players"]:
        if not p["finished"]:
            continue
        k = key(p)
        names[k] = MERGE.get(p["name"], p["name"])
        end = float("inf") if p["to"] is None else p["to"]
        if k not in final or end >= final[k][0]:
            final[k] = (end, p["team"])
    team = {k: t for k, (_, t) in final.items()}
    for a, ta in team.items():
        won = ta == g["winner"]
        record[a][0 if won else 1] += 1
        for b, tb in team.items():
            if a != b:
                pair[(a, b, "with" if ta == tb else "against")][0 if won else 1] += 1

players = sorted(record, key=lambda k: (-sum(record[k]), names[k].lower()))
data = {
    "games": len(games),
    "first": min(g["at"] for g in games), "last": max(g["at"] for g in games),
    "players": [{"name": names[k], "w": record[k][0], "l": record[k][1],
                 "with": [[names[b], *pair[(k, b, "with")]] for b in players if (k, b, "with") in pair],
                 "against": [[names[b], *pair[(k, b, "against")]] for b in players if (k, b, "against") in pair]}
                for k in players],
}

html = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eggball With and Against</title>
<style>
body { font-family: sans-serif; margin: 16px; }
table { border-collapse: collapse; margin: 8px 24px 16px 0; display: inline-table; vertical-align: top; }
th, td { border: 1px solid #ccc; padding: 3px 8px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { cursor: pointer; background: #eee; }
</style></head><body>
<h1>Eggball Ranked: With and Against</h1>
<p id="about"></p>
<p><label>Player <select id="player-select"></select></label> <span id="player-record"></span></p>
<table id="with-table"><caption>With (same team)</caption><thead></thead><tbody></tbody></table>
<table id="against-table"><caption>Against (other team)</caption><thead></thead><tbody></tbody></table>
<script>
const DATA = __DATA__;
const day = (t) => new Date(t).toLocaleDateString();
document.getElementById('about').textContent = DATA.games + ' ranked games on playeggball.com, ' + day(DATA.first) + ' to ' + day(DATA.last) +
  '. Wins and losses are the selected player\\'s. Only players still in the game at the end count. Click a column to sort.';
const select = document.getElementById('player-select');
DATA.players.forEach((p, i) => select.add(new Option(p.name + ' (' + (p.w + p.l) + ')', i)));
const pct = (w, l) => (100 * w / (w + l)).toFixed(0) + '%';
const sortBy = { 'with-table': 1, 'against-table': 1 };
function fill(id, rows) {
  const t = document.getElementById(id);
  const cols = ['Player', 'Games', 'Wins', 'Losses', 'Win %'];
  t.tHead.innerHTML = '<tr>' + cols.map((c, i) => '<th data-col="' + i + '">' + c + '</th>').join('') + '</tr>';
  const r = rows.map(([n, w, l]) => [n, w + l, w, l, w / (w + l)]);
  const c = sortBy[id];
  r.sort((a, b) => c === 0 ? a[0].localeCompare(b[0]) : b[c] - a[c] || b[1] - a[1]);
  t.tBodies[0].innerHTML = r.map(([n, g, w, l]) => '<tr><td>' + n.replace(/</g, '&lt;') + '</td><td>' + g + '</td><td>' + w + '</td><td>' + l + '</td><td>' + pct(w, l) + '</td></tr>').join('');
  t.tHead.onclick = (e) => { if (e.target.dataset.col) { sortBy[id] = +e.target.dataset.col; show(); } };
}
function show() {
  const p = DATA.players[select.value];
  document.getElementById('player-record').textContent = p.w + ' wins, ' + p.l + ' losses (' + pct(p.w, p.l) + ')';
  fill('with-table', p.with);
  fill('against-table', p.against);
}
select.onchange = show;
show();
</script></body></html>
"""
out = os.path.join(DIR, "with_against.html")
open(out, "w").write(html.replace("__DATA__", json.dumps(data)))
print(f"{out}: {len(players)} players, {len(games)} games")
