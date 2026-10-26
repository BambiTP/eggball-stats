"""Build with_against.html: every ranked playeggball.com player's wins and losses with and against every other player.

Reads games.json written by fetch_playeggball_replays.py. A player counts in a game only if they were
still in it at the end ("finished"); leavers are left out. Someone who switched teams counts for the
team they finished on. Guests (no account) are matched by name. The page gets
one row per game and does the counting itself, so its filters (dates, minimum games, name) can recount everything.

usage: playeggball_with_against.py [data_dir]   (default ~/tagpro-analytics/data/playeggball)
"""
import json, os, sys

DIR = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/tagpro-analytics/data/playeggball")
# alt name -> main name: the same person on two accounts
MERGE = {"Bambi1": "Bambi", "waoter": "3"}

games = json.load(open(os.path.join(DIR, "games.json")))

def key(p):
    name = MERGE.get(p["name"], p["name"])
    if name in MERGE.values() or p["account"] is None:
        return "name:" + name
    return p["account"]

index = {}   # key -> position in names
names = []   # latest name per player
rows = []    # [at, winner "red"/"blue", red player indexes, blue player indexes]
for g in sorted(games, key=lambda g: g["at"]):
    final = {}
    for p in g["players"]:
        if not p["finished"]:
            continue
        k = key(p)
        if k not in index:
            index[k] = len(names)
            names.append("")
        names[index[k]] = MERGE.get(p["name"], p["name"])
        end = float("inf") if p["to"] is None else p["to"]
        if k not in final or end >= final[k][0]:
            final[k] = (end, p["team"])
    teams = {"red": [], "blue": []}
    for k, (_, t) in final.items():
        teams[t].append(index[k])
    rows.append([g["at"], g["winner"], teams["red"], teams["blue"]])

data = {"players": names, "games": rows}

html = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eggball With and Against</title>
<style>
body { font-family: sans-serif; margin: 16px; }
#filters label { margin-right: 14px; display: inline-block; margin-bottom: 6px; }
table { border-collapse: collapse; margin: 8px 24px 16px 0; display: inline-table; vertical-align: top; }
caption { font-weight: bold; text-align: left; padding: 4px 0; }
/* With is green, Against is red, and the sticky headings say which, so they stay apart when scrolled */
#with-table th { background: #bfe3bf; }
#with-table td { background: #f0f9f0; }
#against-table th { background: #f2bcbc; }
#against-table td { background: #fdf0f0; }
th, td { border: 1px solid #ccc; padding: 3px 8px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { cursor: pointer; background: #eee; user-select: none; white-space: nowrap; position: sticky; top: var(--bar-height, 0); }
#context-bar { position: sticky; top: 0; z-index: 1; background: #fff; border-bottom: 2px solid #999; padding: 6px 0; margin-bottom: 8px; }
#context-player { font-size: 1.2em; font-weight: bold; }
td a { cursor: pointer; color: #06c; }
</style></head><body>
<h1>Eggball Ranked: With and Against</h1>
<p id="about"></p>
<div id="filters">
  <label>From <input type="date" id="date-from"></label>
  <label>To <input type="date" id="date-to"></label>
  <label>Minimum games <input type="number" id="min-games" min="1" value="1" style="width:4em"></label>
  <label>Name search <input type="search" id="name-search"></label>
  <button id="reset-filters">Reset</button>
</div>
<p id="filter-summary"></p>
<p><label>Player <select id="player-select"></select></label></p>
<div id="context-bar"><span id="context-player"></span> <span id="player-record"></span><br><span id="context-filters"></span></div>
<table id="with-table"><caption></caption><thead></thead><tbody></tbody></table>
<table id="against-table"><caption></caption><thead></thead><tbody></tbody></table>
<br>
<table id="all-players-table"><caption></caption><thead></thead><tbody></tbody></table>
<script>
const DATA = __DATA__;
const $ = (id) => document.getElementById(id);
const day = (t) => new Date(t).toLocaleDateString();
const first = DATA.games[0][0], last = DATA.games[DATA.games.length - 1][0];
$('about').textContent = DATA.games.length + ' ranked games on playeggball.com, ' + day(first) + ' to ' + day(last) +
  '. Wins and losses in the With and Against tables are the selected player\\'s. Only players still in the game at the end count. ' +
  'Click a column heading to sort by it; click it again to reverse.';

const COLS = ['Player', 'Games', 'Wins', 'Losses', 'Win %'];
const FIRST_COL = { 'with-table': () => 'WITH ' + (DATA.players[selected] || '') + ': teammate', 'against-table': () => 'AGAINST ' + (DATA.players[selected] || '') + ': opponent', 'all-players-table': () => 'Player' };
const sorts = { 'with-table': [1, -1], 'against-table': [1, -1], 'all-players-table': [1, -1] };  // [column, 1 up / -1 down]
let selected = null;

function filteredGames() {
  const from = $('date-from').value ? new Date($('date-from').value + 'T00:00').getTime() : -Infinity;
  const to = $('date-to').value ? new Date($('date-to').value + 'T00:00').getTime() + 864e5 : Infinity;
  return DATA.games.filter(([at]) => at >= from && at < to);
}

function count(games) {
  const total = new Map(), withs = new Map(), against = new Map();
  const add = (m, k, won) => { const r = m.get(k) || [0, 0]; r[won ? 0 : 1]++; m.set(k, r); };
  for (const [, winner, red, blue] of games) {
    for (const [mine, theirs, color] of [[red, blue, 'red'], [blue, red, 'blue']]) {
      const won = winner === color;
      for (const a of mine) {
        add(total, a, won);
        for (const b of mine) if (b !== a) add(withs, a + ',' + b, won);
        for (const b of theirs) add(against, a + ',' + b, won);
      }
    }
  }
  return { total, withs, against };
}

const pct = (w, l) => w + l ? (100 * w / (w + l)).toFixed(0) + '%' : '';
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

function fill(id, rows, linkNames) {
  // rows: [player index, wins, losses]
  const t = $(id), [col, dir] = sorts[id];
  t.tHead.innerHTML = '<tr>' + COLS.map((c, i) => '<th data-col="' + i + '">' + (i === 0 ? esc(FIRST_COL[id]()) : c) + (i === col ? (dir > 0 ? ' ▲' : ' ▼') : '') + '</th>').join('') + '</tr>';
  const r = rows.map(([p, w, l]) => [DATA.players[p], w + l, w, l, w / (w + l), p]);
  const byName = (a, b) => a[0].localeCompare(b[0], undefined, { sensitivity: 'base' });
  r.sort((a, b) => (col === 0 ? byName(a, b) * dir : (a[col] - b[col]) * dir) || b[1] - a[1] || byName(a, b));
  t.tBodies[0].innerHTML = r.length ? r.map(([n, g, w, l, , p]) =>
    '<tr><td>' + (linkNames ? '<a data-player="' + p + '">' + esc(n) + '</a>' : esc(n)) + '</td><td>' + g + '</td><td>' + w + '</td><td>' + l + '</td><td>' + pct(w, l) + '</td></tr>').join('')
    : '<tr><td colspan="5">No one matches the filters</td></tr>';
}

function show() {
  const games = filteredGames();
  const { total, withs, against } = count(games);
  const min = Math.max(1, +$('min-games').value || 1);
  const search = $('name-search').value.trim().toLowerCase();
  const nameOk = (p) => !search || DATA.players[p].toLowerCase().includes(search);
  $('filter-summary').textContent = games.length + ' games match the date filters.';
  // the sticky bar and captions repeat the player and filters, so any screenshot of the page explains itself
  const filters = [($('date-from').value || day(first)) + ' to ' + ($('date-to').value || day(last)),
    games.length + ' games'];
  if (min > 1) filters.push('only pairs/players with ' + min + '+ games');
  if (search) filters.push('names containing "' + search + '"');
  $('context-filters').textContent = 'Eggball Ranked, playeggball.com · ' + filters.join(' · ');

  // player list: everyone who played in the filtered games, most games first
  const people = [...total.keys()].sort((a, b) => (total.get(b)[0] + total.get(b)[1]) - (total.get(a)[0] + total.get(a)[1]) || DATA.players[a].localeCompare(DATA.players[b]));
  if (selected === null || !total.has(selected)) selected = people.length ? people[0] : null;
  const sel = $('player-select');
  sel.innerHTML = '';
  people.forEach((p) => { const [w, l] = total.get(p); sel.add(new Option(DATA.players[p] + ' (' + (w + l) + ')', p)); });
  if (selected !== null) sel.value = selected;

  const pairs = (m) => [...m].filter(([k]) => +k.split(',')[0] === selected)
    .map(([k, [w, l]]) => [+k.split(',')[1], w, l]).filter(([p, w, l]) => w + l >= min && nameOk(p));
  const who = selected === null ? '' : DATA.players[selected];
  $('context-player').textContent = who;
  $('with-table').caption.textContent = who + ' WITH each teammate (' + who + '\\'s wins and losses)';
  $('against-table').caption.textContent = who + ' AGAINST each opponent (' + who + '\\'s wins and losses)';
  $('all-players-table').caption.textContent = 'All players, own wins and losses (click a name to select them)';
  if (selected !== null) {
    const [w, l] = total.get(selected);
    $('player-record').textContent = w + ' wins, ' + l + ' losses (' + pct(w, l) + ')';
  } else $('player-record').textContent = 'No games match the filters';
  fill('with-table', selected === null ? [] : pairs(withs));
  fill('against-table', selected === null ? [] : pairs(against));
  document.documentElement.style.setProperty('--bar-height', $('context-bar').offsetHeight + 'px');
  fill('all-players-table', [...total].filter(([p, [w, l]]) => w + l >= min && nameOk(p)).map(([p, [w, l]]) => [p, w, l]), true);
}

for (const id in sorts) $(id).tHead.onclick = (e) => {
  const c = e.target.dataset.col;
  if (c === undefined) return;
  const [col, dir] = sorts[id];
  sorts[id] = +c === col ? [col, -dir] : [+c, +c === 0 ? 1 : -1];
  show();
};
$('all-players-table').tBodies[0].onclick = (e) => {
  if (e.target.dataset.player === undefined) return;
  selected = +e.target.dataset.player;
  show();
  window.scrollTo(0, 0);
};
$('player-select').onchange = () => { selected = +$('player-select').value; show(); };
for (const id of ['date-from', 'date-to', 'min-games', 'name-search']) $(id).oninput = show;
$('reset-filters').onclick = () => {
  $('date-from').value = ''; $('date-to').value = ''; $('min-games').value = 1; $('name-search').value = '';
  show();
};
show();
</script></body></html>
"""
out = os.path.join(DIR, "with_against.html")
open(out, "w").write(html.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
print(f"{out}: {len(names)} players, {len(games)} games")
