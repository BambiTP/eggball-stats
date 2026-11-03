"""Build the eggball stats site: a Games list, one page per game, a Players table and one page per player.

Reads the ranked replays in ~/tagpro-analytics/data/playeggball/replays (parsed once each, cached in
parsed/), writes HTML into the site folder given on the command line (default ~/eggball-live/site).

Definitions (shown on the pages too):
- possession: from the moment a team gets the egg (kickoff, steal, or catching/picking up the other
  team's throw) until it scores or loses it.
- pass: a throw caught by a teammate. Passes to score = passes in the possession that scored.
- turnover: losing the egg, either sacked (tagged while holding it) or a throw the other team gets.
- yards: the field between the endzones is 100 yards. A yard line is measured from that player's own
  goal line, so 10 means deep in your own end and 90 means close to scoring.
- expected points from a yard line: across every game, the average points a possession that starts on
  that yard line goes on to score. A turnover "gives up" the expected points of the other team's
  possession at that spot; forcing one "takes away" the expected points the other team had there.
"""
import html
import json
import os
import statistics as st
import sys
import collections
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_replay import parse

DATA = os.path.expanduser('~/tagpro-analytics/data/playeggball')
SITE = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/eggball-live/site')
CACHE = os.path.join(DATA, 'parsed')
PARSER_VERSION = 4
MERGE = {}   # alt name -> main name (the same person on two accounts); none right now. Same as the with/against page
MIN_GAMES = 20
BIN = 10   # yards per expected-points bucket

TABS = [('home.html', 'Home'), ('index.html', 'With and Against'), ('scores.html', 'Final scores: TPM vs playeggball'),
        ('games.html', 'Games'), ('players.html', 'Players'), ('posters.html', 'Best and worst'),
        ('compare.html', 'Head to head')]

CSS = """
body { font-family: sans-serif; margin: 16px; line-height: 1.4; }
#page-tabs { margin-bottom: 12px; border-bottom: 2px solid #999; }
#page-tabs a { display: inline-block; padding: 6px 14px; border: 1px solid #999; border-bottom: none; text-decoration: none; color: #06c; }
#page-tabs a.current-tab { background: #ddd; color: #000; font-weight: bold; }
table { border-collapse: collapse; margin: 8px 0 18px; }
caption { font-weight: bold; text-align: left; padding: 4px 0; }
th, td { border: 1px solid #ccc; padding: 3px 7px; text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { background: #eee; }
table.sortable th { cursor: pointer; }
tr.red-team td:first-child { border-left: 6px solid #d33; }
tr.blue-team td:first-child { border-left: 6px solid #36c; }
.explain { color: #444; max-width: 900px; }
.wide { overflow-x: auto; max-width: 100%; }
.win { color: #282; font-weight: bold; }
.loss { color: #b22; font-weight: bold; }
.form a { text-decoration: none; display: inline-block; width: 1.4em; text-align: center; border: 1px solid #ccc; margin-right: 2px; }
.rating-chart { width: 100%; max-width: 720px; height: auto; border: 1px solid #ccc; background: #fff; }
@media (max-width: 600px) {
  body { margin: 8px; }
  #page-tabs a { padding: 4px 8px; font-size: 0.9em; }
  th, td { padding: 2px 4px; }
}
"""

SORT_JS = """<script>
// click a column heading to sort by it; click again to reverse
document.querySelectorAll('table.sortable').forEach(function (table) {
  table.querySelectorAll('th').forEach(function (heading, column) {
    heading.addEventListener('click', function () {
      var body = table.tBodies[0];
      var rows = Array.from(body.rows);
      var down = heading.dataset.down !== '1';
      heading.dataset.down = down ? '1' : '0';
      rows.sort(function (a, b) {
        var x = a.cells[column].dataset.v ?? a.cells[column].textContent;
        var y = b.cells[column].dataset.v ?? b.cells[column].textContent;
        var nx = parseFloat(x), ny = parseFloat(y);
        var c = (!isNaN(nx) && !isNaN(ny)) ? nx - ny : String(x).localeCompare(String(y));
        return down ? -c : c;
      });
      rows.forEach(function (r) { body.appendChild(r); });
    });
  });
});
</script>"""


def page(title, current, body, depth=0):
    up = '../' * depth
    tabs = ' '.join(f'<a href="{up}{href}"' + (' class="current-tab"' if href == current else '') + f'>{label}</a>'
                    for href, label in TABS)
    return (f'<!doctype html>\n<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body>\n'
            f'<nav id="page-tabs">{tabs}</nav>\n{body}\n{SORT_JS}\n</body></html>\n')


def esc(x):
    return html.escape(str(x))


def num(x, places=1):
    if x is None:
        return ''
    if isinstance(x, int):
        return str(x)
    return f'{x:.{places}f}'


def pct(x):
    return '' if x is None else f'{x:.0%}'


def cell(x, places=1, as_pct=False):
    if x is None:
        return '<td data-v="-1e9"></td>'
    shown = pct(x) if as_pct else num(x, places)
    return f'<td data-v="{x}">{shown}</td>'


def player_key(p):
    name = MERGE.get(p['name'], p['name'])
    if name in MERGE.values() or not p.get('account'):
        return 'name:' + name
    return p['account']


PROFILE_FILE = {}   # player key -> readable file name (from their latest name), filled in by name_profiles()


def name_profiles(total):
    """Give each player a readable page name like "Lancer-Evo-X" instead of their account id.
    Players with the most games get a clashing name first; anyone after them gets "-2", "-3"."""
    used = set()
    for k, a in sorted(total.items(), key=lambda x: -len(x[1]['log'])):
        base = '-'.join(''.join(c if (c.isascii() and c.isalnum()) or c == '_' else ' ' for c in a['name']).split()) or 'player'
        name, n = base, 1
        while name.lower() in used:
            n += 1
            name = f'{base}-{n}'
        used.add(name.lower())
        PROFILE_FILE[k] = name


def file_key(key):
    if key in PROFILE_FILE:
        return PROFILE_FILE[key]
    return ''.join(c if c.isalnum() else '_' for c in key)


# ---------- 1. parse every ranked replay (cached) ----------

def load_games():
    os.makedirs(CACHE, exist_ok=True)
    listed = {g['id']: g for g in json.load(open(os.path.join(DATA, 'games.json')))}
    out = []
    for gid, meta in listed.items():
        if meta.get('kind') != 'ranked':
            continue
        src = os.path.join(DATA, 'replays', gid + '.eggball-replay.gz')
        if not os.path.exists(src):
            continue
        cached = os.path.join(CACHE, gid + '.json')
        g = None
        if os.path.exists(cached) and os.path.getmtime(cached) >= os.path.getmtime(src):
            g = json.load(open(cached))
            if g.get('parser_version') != PARSER_VERSION:
                g = None
        if g is None:
            try:
                g = parse(src)
            except Exception as e:  # a broken file shouldn't stop the site
                print('skipped', gid, e)
                continue
            g['parser_version'] = PARSER_VERSION
            json.dump(g, open(cached, 'w'))
        g['team'] = {int(k): v for k, v in g['team'].items()}
        g['name'] = {int(k): v for k, v in g['name'].items()}
        out.append(g)
    out.sort(key=lambda g: g['info']['at'])
    return out


# ---------- 2. per-game numbers ----------

def link_goals_to_possessions(g):
    by_end = {p['end']: p for p in g['possessions'] if p['end_how'] == 'goal'}
    for p in g['possessions']:
        p['points'] = 0
    for goal in g['goals']:
        p = by_end.get(goal['time'])
        if p:
            p['points'] = goal['points']
    # what happened next, for turnovers: the other team's possession that followed
    for a, b in zip(g['possessions'], g['possessions'][1:]):
        a['next'] = b if a['end_how'] in ('sacked', 'intercepted') else None
    if g['possessions']:
        g['possessions'][-1]['next'] = None


def expected_points_table(games):
    """Average points scored by a possession, by the yard line it starts on (10-yard buckets)."""
    total = collections.defaultdict(float)
    count = collections.Counter()
    for g in games:
        for p in g['possessions']:
            if p['start_yard'] is None or p['end_how'] in ('end',):
                continue
            b = min(int(p['start_yard'] // BIN), 100 // BIN - 1)
            total[b] += p['points']
            count[b] += 1
    return {b: (total[b] / count[b], count[b]) for b in count}


def ep(table, yard):
    if yard is None:
        return None
    b = min(int(yard // BIN), 100 // BIN - 1)
    return table.get(b, (0, 0))[0]


def game_players(g):
    """key -> {name, team, minutes, ids} for everyone who played, merging re-joins on one account."""
    ms = g['info']['ms']
    people = {}
    for p in g['info']['players']:
        k = player_key(p)
        end = ms if p['to'] is None else p['to']
        q = people.setdefault(k, {'name': MERGE.get(p['name'], p['name']), 'ids': set(), 'ms': 0,
                                  'finished': False, 'team': p['team'], 'last_end': -1})
        if 'id' in p:
            q['ids'].add(p['id'])
        q['ms'] += max(0, end - p['from'])
        q['finished'] = q['finished'] or p['finished']
        if end >= q['last_end']:
            q['team'], q['last_end'] = p['team'], end
    return people


def per_game(g, table):
    """Team stats and player stats for one game."""
    link_goals_to_possessions(g)
    people = game_players(g)
    id_key = {i: k for k, q in people.items() for i in q['ids']}
    box_by_account = {}
    for r in (g['result'] or {}).get('players', []):
        box_by_account[r.get('account') or 'name:' + r['name']] = r

    stats = {k: collections.Counter() for k in people}
    lists = {k: collections.defaultdict(list) for k in people}

    def add(pid, field, n=1):
        k = id_key.get(pid)
        if k is not None:
            stats[k][field] += n

    def note(pid, field, value):
        k = id_key.get(pid)
        if k is not None and value is not None:
            lists[k][field].append(value)

    for goal in g['goals']:
        add(goal['scorer'], 'goals')
        add(goal['scorer'], 'points_scored', goal['points'])
        add(goal['assist'], 'assists')
        add(goal['second_assist'], 'second_assists')
        if goal['boat']:
            add(goal['scorer'], 'boat_goals')
            add(goal['assist'], 'boat_passes')
    for t in g['passes']:
        add(t['thrower'], 'throws')
        if t['outcome'] == 'complete':
            add(t['thrower'], 'passes')
    teams = {tm: collections.Counter() for tm in ('red', 'blue')}
    team_lists = {tm: collections.defaultdict(list) for tm in ('red', 'blue')}
    for p in g['possessions']:
        if p['end_how'] == 'end' and not p['touches']:
            continue
        tm = p['team']
        teams[tm]['possessions'] += 1
        scored = p['end_how'] == 'goal'
        teams[tm]['scoring_possessions'] += scored
        team_lists[tm]['passes_scoring' if scored else 'passes_not_scoring'].append(p['passes'])
        if scored:
            team_lists[tm]['seconds_to_score'].append((p['end'] - p['start']) / 1000)
        if p['start_yard'] is not None:
            team_lists[tm]['start_yard'].append(p['start_yard'])
        for pid in set(p['touches']):
            add(pid, 'possessions_touched')
            if scored:
                add(pid, 'scoring_possessions_touched')
                note(pid, 'passes_to_score', p['passes'])
        if p['end_how'] in ('sacked', 'intercepted'):
            teams[tm]['turnovers'] += 1
            teams[tm]['sacked' if p['end_how'] == 'sacked' else 'throws_lost'] += 1
            if p['end_yard'] is not None:
                team_lists[tm]['turnover_yard'].append(p['end_yard'])
            nxt = p.get('next')
            lost_by, forced_by = p['lost_by'], p['forced_by']
            add(lost_by, 'turnovers')
            add(lost_by, 'sacked' if p['end_how'] == 'sacked' else 'throws_lost')
            add(forced_by, 'forced')
            add(forced_by, 'steals' if p['end_how'] == 'sacked' else 'interceptions')
            if p['end_yard'] is not None:
                given = ep(table, 100 - p['end_yard'])   # the other team's possession starts here
                taken = ep(table, p['end_yard'])          # what the team that lost it had from here
                note(lost_by, 'turnover_yard', p['end_yard'])
                note(lost_by, 'xpoints_given', given)
                note(forced_by, 'forced_yard', 100 - p['end_yard'])
                note(forced_by, 'xpoints_taken', taken)
            if nxt is not None and nxt['team'] != tm:
                if nxt['end_how'] == 'goal':
                    add(lost_by, 'points_given', nxt['points'])
                    add(lost_by, 'goals_given')
                    note(lost_by, 'passes_to_score_after', nxt['passes'])
    # first goal, lead changes, halves
    lead_changes, leader, first = 0, None, None
    half_goals = {'red': [0, 0], 'blue': [0, 0]}
    for goal in g['goals']:
        first = first or goal['team']
        now = 'red' if goal['red'] > goal['blue'] else 'blue' if goal['blue'] > goal['red'] else None
        if now and leader and now != leader:
            lead_changes += 1
        leader = now or leader
        half = 1 if g['halftime'] is not None and goal['time'] >= g['halftime'] else 0
        half_goals[goal['team']][half] += goal['points']

    players = {}
    for k, q in people.items():
        s, l = stats[k], lists[k]
        box = box_by_account.get(k) or {}
        if not box:
            for r in (g['result'] or {}).get('players', []):
                if MERGE.get(r['name'], r['name']) == q['name']:
                    box = r
        players[k] = {
            'name': q['name'], 'team': q['team'], 'minutes': q['ms'] / 60000, 'finished': q['finished'],
            **{f: s[f] for f in ('goals', 'points_scored', 'assists', 'second_assists', 'boat_goals', 'boat_passes',
                                 'throws', 'passes', 'possessions_touched', 'scoring_possessions_touched',
                                 'turnovers', 'sacked', 'throws_lost', 'forced', 'steals', 'interceptions',
                                 'points_given', 'goals_given')},
            'lists': {f: l[f] for f in ('passes_to_score', 'turnover_yard', 'xpoints_given', 'forced_yard',
                                        'xpoints_taken', 'passes_to_score_after')},
            'saves': box.get('saves'), 'box_points': box.get('points'), 'mvp': box.get('mvp'),
        }
    team_summary = {}
    for tm in ('red', 'blue'):
        c, l = teams[tm], team_lists[tm]
        team_summary[tm] = {
            'score': g['info']['score'][tm], 'possessions': c['possessions'],
            'scoring_rate': c['scoring_possessions'] / c['possessions'] if c['possessions'] else None,
            'passes_scoring': mean(l['passes_scoring']), 'passes_not_scoring': mean(l['passes_not_scoring']),
            'seconds_to_score': mean(l['seconds_to_score']), 'start_yard': mean(l['start_yard']),
            'turnovers': c['turnovers'], 'sacked': c['sacked'], 'throws_lost': c['throws_lost'],
            'turnover_yard': mean(l['turnover_yard']),
            'first_half': half_goals[tm][0], 'second_half': half_goals[tm][1],
            'boats': sum(1 for x in g['goals'] if x['team'] == tm and x['boat']),
        }
    return {'players': players, 'teams': team_summary, 'first': first, 'lead_changes': lead_changes}


def mean(x):
    x = [v for v in x if v is not None]
    return st.mean(x) if x else None


# ---------- 3. pages ----------

def when(g):
    return datetime.datetime.fromtimestamp(g['info']['at'] / 1000).strftime('%Y-%m-%d %H:%M')


def length(g):
    s = g['info']['ms'] // 1000
    return f'{s // 60}:{s % 60:02d}'


DEFINITIONS = """<div class="explain"><p><b>How these are counted.</b>
A <b>possession</b> runs from when a team gets the egg (kickoff, steal, or getting the other team's throw) until it scores or loses it.
A <b>pass</b> is a throw caught by a teammate. <b>Second assist</b> = the pass before the assist.
A <b>turnover</b> is losing the egg: <b>sacked</b> (tagged while holding it) or a <b>throw lost</b> (the other team gets your throw).
<b>Yards</b>: the field between the endzones is 100 yards, measured from that player's own goal line (10 = deep in your own end, 90 = near scoring).
<b>Expected points (xP)</b> from a yard line = the average points a possession starting there goes on to score, over every game.
A turnover <b>gives up</b> the other team's xP from that spot; forcing one <b>takes away</b> the xP the other team had there.
<b>Points given up</b> = points the other team actually scored on the possession right after your turnover.
<b>Passes to score after</b> = how many passes that took them.</p></div>"""


def games_page(games, per):
    rows = []
    for g in reversed(games):
        info, s = g['info'], per[g['info']['id']]
        t = s['teams']
        over = g.get('over') or {}
        rows.append(
            f'<tr><td data-v="{info["at"]}"><a href="games/{info["id"]}.html">{when(g)}</a></td>'
            f'<td>{esc(info["map"])}</td><td>{info["score"]["red"]}–{info["score"]["blue"]}</td>'
            f'<td>{esc(info["winner"] or "")}</td><td data-v="{info["ms"]}">{length(g)}</td>'
            f'<td>{"yes" if over.get("mercy") else ""}</td>'
            f'<td>{t["red"]["possessions"]}–{t["blue"]["possessions"]}</td>'
            f'<td>{pct(t["red"]["scoring_rate"])}–{pct(t["blue"]["scoring_rate"])}</td>'
            f'<td>{t["red"]["turnovers"]}–{t["blue"]["turnovers"]}</td>'
            f'<td>{s["lead_changes"]}</td></tr>')
    body = (f'<h1>Eggball ranked games</h1><p>{len(games)} games, newest first. Red–Blue in each column. '
            f'Click a game for its full stats. Updated {datetime.datetime.now():%Y-%m-%d %H:%M}.</p>'
            '<div class="wide"><table class="sortable"><thead><tr><th>Date</th><th>Map</th><th>Score (red–blue)</th><th>Winner</th>'
            '<th>Length</th><th>Mercy</th><th>Possessions</th><th>Possessions that scored</th><th>Turnovers</th>'
            '<th>Lead changes</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
    return page('Eggball Games', 'games.html', body)


PLAYER_COLUMNS = [
    ('Player', None), ('Min', 'minutes'), ('Game rating', None), ('Goals', 'goals'), ('Assists', 'assists'),
    ('2nd assists', 'second_assists'), ('Boat goals', 'boat_goals'), ('Boat passes', 'boat_passes'),
    ('Passes / throws', None), ('Possessions touched', 'possessions_touched'),
    ('Touched → scored', None), ('Avg passes to score', None),
    ('Turnovers', 'turnovers'), ('Sacked', 'sacked'), ('Throws lost', 'throws_lost'),
    ('Avg turnover yard', None), ('xP given up', None), ('Points given up', 'points_given'),
    ('Avg passes to score after', None),
    ('Steals', 'steals'), ('Interceptions', 'interceptions'), ('Avg forced yard', None), ('xP taken away', None),
    ('Saves', 'saves'), ('Game points', 'box_points'),
]


def game_page(g, s, keys):
    info = g['info']
    t = s['teams']

    def trow(label, f, places=1, as_pct=False):
        return f'<tr><td>{label}</td>' + ''.join(cell(t[tm][f], places, as_pct) for tm in ('red', 'blue')) + '</tr>'

    team_table = ('<table><caption>Teams</caption><tr><th></th><th>Red</th><th>Blue</th></tr>'
                  + trow('Score', 'score') + trow('First half', 'first_half') + trow('Second half', 'second_half')
                  + trow('Raptor Boats', 'boats') + trow('Possessions', 'possessions')
                  + trow('Possessions that scored', 'scoring_rate', as_pct=True)
                  + trow('Avg passes, scoring possessions', 'passes_scoring')
                  + trow('Avg passes, other possessions', 'passes_not_scoring')
                  + trow('Avg seconds to score', 'seconds_to_score')
                  + trow('Avg yard possessions start on', 'start_yard')
                  + trow('Turnovers', 'turnovers') + trow('Sacked', 'sacked') + trow('Throws lost', 'throws_lost')
                  + trow('Avg turnover yard', 'turnover_yard') + '</table>')
    rows = []
    for k, p in sorted(s['players'].items(), key=lambda kv: (kv[1]['team'] != 'red', -kv[1]['goals'])):
        l = p['lists']
        name = f'<a href="../players/{file_key(k)}.html">{esc(p["name"])}</a>' if k in keys else esc(p['name'])
        if not p['finished']:
            name += ' (left)'
        touched = p['possessions_touched']
        rows.append(
            f'<tr class="{p["team"]}-team"><td>{name}</td>' + cell(p['minutes']) + cell(game_rating(p), 2) + cell(p['goals']) + cell(p['assists'])
            + cell(p['second_assists']) + cell(p['boat_goals']) + cell(p['boat_passes'])
            + f'<td data-v="{p["passes"]}">{p["passes"]}/{p["throws"]}</td>' + cell(touched)
            + cell(p['scoring_possessions_touched'] / touched if touched else None, as_pct=True)
            + cell(mean(l['passes_to_score'])) + cell(p['turnovers']) + cell(p['sacked']) + cell(p['throws_lost'])
            + cell(mean(l['turnover_yard'])) + cell(sum(l['xpoints_given']), 2) + cell(p['points_given'])
            + cell(mean(l['passes_to_score_after'])) + cell(p['steals']) + cell(p['interceptions'])
            + cell(mean(l['forced_yard'])) + cell(sum(l['xpoints_taken']), 2)
            + cell(p['saves']) + cell(p['box_points']) + '</tr>')
    head = ''.join(f'<th>{c}</th>' for c, _ in PLAYER_COLUMNS)
    names = g['name']
    id_key = {i: k for k, q in game_players(g).items() for i in q['ids']}

    def who(pid):
        k = id_key.get(pid)
        if pid is None:
            return ''
        if k in keys:
            return f'<a href="../players/{file_key(k)}.html">{esc(names.get(pid, ""))}</a>'
        return esc(names.get(pid, ''))

    def link(k, p):
        return f'<a href="../players/{file_key(k)}.html">{esc(p["name"])}</a>' if k in keys else esc(p['name'])
    rated = sorted(((game_rating(p), k, p) for k, p in s['players'].items() if p['finished'] and p['minutes'] >= 5),
                   key=lambda x: x[0])
    stars = ''
    if rated:
        hi, lo = rated[-1], rated[0]
        stars = (f'<p><span class="win">Best player of the game:</span> {link(hi[1], hi[2])} ({hi[2]["team"]}, rating {hi[0]:+.2f}) · '
                 f'<span class="loss">Worst:</span> {link(lo[1], lo[2])} ({lo[2]["team"]}, rating {lo[0]:+.2f})</p>')
    kickoff = g['possessions'][0]['start'] if g['possessions'] else 0

    def clock(ms):
        ms = max(0, ms - kickoff)
        return f'{ms // 60000}:{ms // 1000 % 60:02d}'
    goal_rows = ''.join(
        f'<tr class="{x["team"]}-team"><td>{clock(x["time"])}</td><td>{x["red"]}–{x["blue"]}</td>'
        f'<td>{who(x["scorer"])}</td><td>{who(x["assist"])}</td>'
        f'<td>{who(x["second_assist"])}</td><td>{"yes" if x["boat"] else ""}</td>'
        f'<td>{"" if x["passes"] is None else x["passes"]}</td>'
        f'<td>{num(x.get("possession_seconds"))}</td><td>{num(x.get("possession_start_yard"))}</td></tr>'
        for x in g['goals'])
    winner = info['winner']
    headline = (f'{winner.capitalize()} wins {info["score"][winner]}–{info["score"]["blue" if winner == "red" else "red"]}'
                if winner else f'Tied {info["score"]["red"]}–{info["score"]["blue"]}')
    body = (f'<h1>{headline}{" (mercy)" if (g.get("over") or {}).get("mercy") else ""}</h1>'
            f'<p><b>{when(g)}</b> · {esc(info["map"])} · length {length(g)} · red {info["score"]["red"]}, blue {info["score"]["blue"]} · '
            f'first goal: {esc(s["first"] or "none")} · lead changes: {s["lead_changes"]} · <a href="../games.html">All games</a></p>'
            + stars + team_table
            + '<div class="wide"><table class="sortable"><caption>Players (red rows first, then blue; click a heading to sort)</caption>'
            + f'<thead><tr>{head}</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
            + '<table><caption>Goals (time since the opening kickoff)</caption><tr><th>Time</th><th>Score</th>'
              '<th>Scorer</th><th>Assist</th><th>2nd assist</th><th>Raptor Boat</th><th>Passes</th>'
              '<th>Possession seconds</th><th>Possession started on yard</th></tr>' + goal_rows + '</table>'
            + DEFINITIONS)
    return page(f'Eggball game {when(g)}', None, body, depth=1)


def aggregate(games, per):
    """Totals per player over all their games."""
    total = {}
    for g in games:
        s = per[g['info']['id']]
        winner = g['info']['winner']
        team_rate = {tm: s['teams'][tm]['scoring_rate'] for tm in ('red', 'blue')}
        for k, p in s['players'].items():
            a = total.setdefault(k, {'name': p['name'], 'games': 0, 'wins': 0, 'minutes': 0.0,
                                     'c': collections.Counter(), 'l': collections.defaultdict(list),
                                     'team_rate_touched': 0.0, 'log': [], 'ratings': []})
            a['name'] = p['name']
            if not p['finished']:
                a['log'].append((g, p))
                continue
            a['games'] += 1
            a['wins'] += p['team'] == winner
            a['minutes'] += p['minutes']
            if p['minutes'] >= 5:
                a['ratings'].append(game_rating(p))
            for f, v in p.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and f not in ('minutes',):
                    a['c'][f] += v or 0
            for f, v in p['lists'].items():
                a['l'][f].extend(v)
            if team_rate[p['team']] is not None:
                a['team_rate_touched'] += team_rate[p['team']] * p['possessions_touched']
            a['log'].append((g, p))
    for a in total.values():
        c, l, n = a['c'], a['l'], max(a['games'], 1)
        touched = c['possessions_touched']
        a['row'] = {
            'games': a['games'], 'win_rate': a['wins'] / n if a['games'] else None,
            'rating_pg': mean(a['ratings']),
            'goals_pg': c['goals'] / n, 'assists_pg': c['assists'] / n, 'second_assists_pg': c['second_assists'] / n,
            'involvement_pg': (c['goals'] + c['assists'] + c['second_assists']) / n,
            'boats_pg': (c['boat_goals'] + c['boat_passes']) / n,
            'pass_rate': c['passes'] / c['throws'] if c['throws'] else None,
            'touched_pg': touched / n,
            'touched_scored': c['scoring_possessions_touched'] / touched if touched else None,
            'touched_lift': None,  # filled in below, against the average player
            'passes_to_score': mean(l['passes_to_score']),
            'turnovers_pg': c['turnovers'] / n, 'turnovers_per_touch': c['turnovers'] / touched if touched else None,
            'turnover_yard': mean(l['turnover_yard']), 'xp_given_pg': sum(l['xpoints_given']) / n,
            'points_given_pg': c['points_given'] / n, 'passes_after': mean(l['passes_to_score_after']),
            'forced_pg': c['forced'] / n, 'forced_yard': mean(l['forced_yard']),
            'xp_taken_pg': sum(l['xpoints_taken']) / n,
            'net_turnover_xp_pg': (sum(l['xpoints_taken']) - sum(l['xpoints_given'])) / n,
        }
    # possessions with more players in them score more, so compare each player with the average player
    all_touched = sum(a['c']['possessions_touched'] for a in total.values())
    all_scored = sum(a['c']['scoring_possessions_touched'] for a in total.values())
    average = all_scored / all_touched if all_touched else 0
    for a in total.values():
        if a['row']['touched_scored'] is not None:
            a['row']['touched_lift'] = a['row']['touched_scored'] - average
    return total


AGG_COLUMNS = [
    ('games', 'Games', 0, False), ('win_rate', 'Win %', 0, True), ('rating_pg', 'Avg game rating', 2, False),
    ('goals_pg', 'Goals', 2, False), ('assists_pg', 'Assists', 2, False), ('second_assists_pg', '2nd assists', 2, False),
    ('involvement_pg', 'Goal involvement', 2, False), ('boats_pg', 'Boats (goals + passes)', 2, False),
    ('pass_rate', 'Pass completion', 0, True), ('touched_pg', 'Possessions touched', 1, False),
    ('touched_scored', 'Touched → scored', 0, True), ('touched_lift', 'vs average player', 0, True),
    ('passes_to_score', 'Avg passes to score', 1, False),
    ('turnovers_pg', 'Turnovers', 2, False), ('turnovers_per_touch', 'Turnovers per possession touched', 0, True),
    ('turnover_yard', 'Avg turnover yard', 0, False), ('xp_given_pg', 'xP given up', 2, False),
    ('points_given_pg', 'Points given up', 2, False), ('passes_after', 'Avg passes to score after', 1, False),
    ('forced_pg', 'Turnovers forced', 2, False), ('forced_yard', 'Avg forced yard', 0, False),
    ('xp_taken_pg', 'xP taken away', 2, False), ('net_turnover_xp_pg', 'Net turnover xP', 2, False),
]


def top_list(total, field, title, reverse, explain, places=2, as_pct=False):
    ranked = [(k, a) for k, a in total.items() if a['games'] >= MIN_GAMES and a['row'][field] is not None]
    ranked.sort(key=lambda kv: kv[1]['row'][field], reverse=reverse)
    rows = ''.join(f'<tr><td>{i + 1}. <a href="players/{file_key(k)}.html">{esc(a["name"])}</a></td>'
                   f'<td>{pct(a["row"][field]) if as_pct else num(a["row"][field], places)}</td><td>{a["games"]}</td></tr>'
                   for i, (k, a) in enumerate(ranked[:10]))
    return (f'<table style="display:inline-table; margin-right:18px; vertical-align:top"><caption>{title}</caption>'
            f'<tr><th>Player</th><th>{explain}</th><th>Games</th></tr>{rows}</table>')


def players_page(total, table):
    head = '<th>Player</th>' + ''.join(f'<th>{label}</th>' for _, label, _, _ in AGG_COLUMNS)
    rows = []
    for k, a in sorted(total.items(), key=lambda kv: -kv[1]['games']):
        if a['games'] == 0:
            continue
        r = a['row']
        rows.append(f'<tr data-games="{a["games"]}"><td><a href="players/{file_key(k)}.html">{esc(a["name"])}</a></td>'
                    + ''.join(cell(r[f], places, as_pct) for f, _, places, as_pct in AGG_COLUMNS) + '</tr>')
    ep_rows = ''.join(f'<tr><td>{b * BIN}–{b * BIN + BIN}</td><td>{v:.2f}</td><td>{n}</td></tr>'
                      for b, (v, n) in sorted(table.items()))
    boards = (
        '<h2>Overall</h2><p class="explain"><b>Game rating</b> = points scored + ½ per assist + ¼ per second assist '
        '+ expected points taken away by steals and interceptions − expected points given up by turnovers. '
        'This is the average over every game they finished (5+ minutes).</p>'
        + top_list(total, 'rating_pg', 'Best average game rating', True, 'per game')
        + top_list(total, 'rating_pg', 'Worst average game rating', False, 'per game')
        + '<h2>Offense</h2><p class="explain">Only stats that don\'t depend on where players are. '
        '"Goal involvement" = goals + assists + second assists per game. "vs average player" = how much more (or less) '
        'often possessions this player touched ended in a goal than possessions the average player touched.</p>'
        + top_list(total, 'involvement_pg', 'Most goal involvement', True, 'per game')
        + top_list(total, 'involvement_pg', 'Least goal involvement', False, 'per game')
        + top_list(total, 'touched_lift', 'Possessions score most when they touch it', True, 'vs average player', as_pct=True)
        + top_list(total, 'touched_lift', 'Possessions score least when they touch it', False, 'vs average player', as_pct=True)
        + '<h2>Defense and turnovers</h2><p class="explain">"xP given up" = expected points the other team got from '
          'where this player lost the egg, per game. "Points given up" = points actually scored on the possession right after their turnover, per game. '
          '"xP taken away" = expected points the other team lost to this player\'s steals and interceptions, per game.</p>'
        + top_list(total, 'xp_given_pg', 'Gives up the most (xP per game)', True, 'xP given up')
        + top_list(total, 'points_given_pg', 'Most points scored off their turnovers', True, 'per game')
        + top_list(total, 'xp_taken_pg', 'Takes away the most (xP per game)', True, 'xP taken away')
        + top_list(total, 'net_turnover_xp_pg', 'Best net turnover value', True, 'taken − given')
        + top_list(total, 'net_turnover_xp_pg', 'Worst net turnover value', False, 'taken − given'))
    body = (f'<h1>Eggball ranked players</h1><p><b>Who is best and worst at what.</b> Each list is the top or bottom 10 of players with at least {MIN_GAMES} finished games; '
            'click a name for their profile. '
            f'Games a player left before the end don\'t count. Everything in the big table is per game unless it says otherwise. '
            f'Updated {datetime.datetime.now():%Y-%m-%d %H:%M}.</p>'
            + boards
            + f'<h2>Every player</h2><p><label>Minimum games <input type="number" id="minimum-games" value="{MIN_GAMES}" min="0" style="width:5em"></label> '
              'Click a heading to sort.</p>'
            + f'<div class="wide"><table class="sortable" id="players-table"><thead><tr>{head}</tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>'
            + '<table><caption>Expected points by the yard line a possession starts on</caption>'
              '<tr><th>Yard line (from own goal)</th><th>Expected points</th><th>Possessions</th></tr>' + ep_rows + '</table>'
            + DEFINITIONS
            + """<script>
var minimumGamesInput = document.getElementById('minimum-games');
function applyMinimumGames() {
  var minimum = parseInt(minimumGamesInput.value || '0', 10);
  document.querySelectorAll('#players-table tbody tr').forEach(function (row) {
    row.style.display = parseInt(row.dataset.games, 10) >= minimum ? '' : 'none';
  });
}
minimumGamesInput.addEventListener('input', applyMinimumGames);
applyMinimumGames();
</script>""")
    return page('Eggball Players', 'players.html', body)


def with_against(k, a, per):
    """Teammates and opponents of player k in their finished games: key -> [name, wins, losses].
    Same rules as the With and Against page: only players still in the game at the end, on the team they finished on."""
    withs, against = {}, {}
    for g, p in a['log']:
        if not p['finished'] or not g['info']['winner']:
            continue
        won = p['team'] == g['info']['winner']
        for k2, q in per[g['info']['id']]['players'].items():
            if k2 == k or not q['finished']:
                continue
            r = (withs if q['team'] == p['team'] else against).setdefault(k2, [q['name'], 0, 0])
            r[0] = q['name']
            r[1 if won else 2] += 1
    return withs, against


def pair_table(title, rows, keys):
    body = ''.join(
        f'<tr><td>' + (f'<a href="{file_key(k2)}.html">{esc(n)}</a>' if k2 in keys else esc(n)) + '</td>'
        f'<td data-v="{w + l}">{w + l}</td><td data-v="{w}">{w}</td><td data-v="{l}">{l}</td>'
        f'<td data-v="{w - l}">{w - l:+d}</td><td data-v="{w / (w + l)}">{w / (w + l):.0%}</td></tr>'
        for k2, (n, w, l) in sorted(rows.items(), key=lambda x: (-(x[1][1] + x[1][2]), x[1][0].lower())))
    return (f'<table class="sortable pair-table"><caption>{title}</caption><thead><tr><th>Player</th><th>Games</th>'
            f'<th>Wins</th><th>Losses</th><th>+/-</th><th>Win %</th></tr></thead><tbody>{body}</tbody></table>')


def best_worst_pairs(name, withs, against, keys):
    """Best and worst teammate and opponent by plus/minus (wins minus losses), ties to the better or worse win %."""
    def pick(rows, best):
        if not rows:
            return None
        side = 1 if best else -1
        return max(rows.items(), key=lambda x: (side * (x[1][1] - x[1][2]), side * x[1][1] / (x[1][1] + x[1][2])))
    out = []
    for label, rows, best in (('Best with', withs, True), ('Worst with', withs, False),
                              ('Best against', against, True), ('Worst against', against, False)):
        r = pick(rows, best)
        if r is None:
            out.append(f'<tr><td>{label}</td><td colspan="5">No one</td></tr>')
            continue
        k2, (n, w, l) = r
        link = f'<a href="{file_key(k2)}.html">{esc(n)}</a>' if k2 in keys else esc(n)
        out.append(f'<tr><td>{label}</td><td>{link}</td><td>{w - l:+d}</td><td>{w + l}</td><td>{w}–{l}</td><td>{w / (w + l):.0%}</td></tr>')
    return (f'<table><caption>{esc(name)}: best and worst teammates and opponents (by wins minus losses together)</caption>'
            '<tr><th></th><th>Player</th><th>+/-</th><th>Games</th><th>Won–lost</th><th>Win %</th></tr>' + ''.join(out) + '</table>')


def player_streaks(a):
    """Longest win streak, longest losing streak and the current streak, over finished games."""
    results = [(g, p['team'] == g['info']['winner']) for g, p in a['log'] if p['finished'] and g['info']['winner']]
    best = {True: [], False: []}
    run = []
    for g, won in results:
        run = run + [(g, won)] if run and run[-1][1] == won else [(g, won)]
        if len(run) > len(best[won]):
            best[won] = list(run)
    return best[True], best[False], run


def rating_chart(rated):
    """A plain line chart: one dot per game (oldest left), and the average of the last 10 games as a line."""
    if len(rated) < 2:
        return ''
    w, h, pad = 720, 200, 30
    ys = [x for x, _ in rated]
    top, bottom = max(max(ys), 1), min(min(ys), -1)
    def X(i): return pad + i * (w - 2 * pad) / (len(rated) - 1)
    def Y(v): return pad / 2 + (top - v) * (h - pad) / (top - bottom)
    dots = ''.join(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="2.5" fill="{"#3a3" if won else "#c44"}"><title>{when(g)}: {v:+.2f}</title></circle>'
                   for i, (v, (g, won)) in enumerate(rated))
    avg = []
    for i in range(len(rated)):
        window = ys[max(0, i - 9):i + 1]
        avg.append(f'{X(i):.1f},{Y(sum(window) / len(window)):.1f}')
    return (f'<svg class="rating-chart" viewBox="0 0 {w} {h}" role="img" aria-label="Game rating over time">'
            f'<line x1="{pad}" x2="{w - pad}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#999" stroke-dasharray="4 3"/>'
            f'<text x="2" y="{Y(0) + 4:.1f}" font-size="11">0</text>'
            f'<text x="2" y="{Y(top) + 10:.1f}" font-size="11">{top:+.0f}</text>'
            f'<text x="2" y="{Y(bottom):.1f}" font-size="11">{bottom:+.0f}</text>'
            f'{dots}<polyline points="{" ".join(avg)}" fill="none" stroke="#36c" stroke-width="2"/></svg>'
            '<p class="explain">Each dot is one game (green = won, red = lost), oldest on the left; '
            'hover a dot for the date. The blue line is the average of the last 10 games.</p>')


def player_page(k, a, per, keys, ranks):
    r = a['row']
    summary = ''.join(f'<tr><td>{label}</td>{cell(r[f], places, as_pct)}</tr>' for f, label, places, as_pct in AGG_COLUMNS)

    # best and worst single game, same game rating as the Best and worst page
    rated = [(game_rating(p), g, p) for g, p in a['log'] if p['finished'] and p['minutes'] >= 5]
    cards = []
    if rated:
        top = max(rated, key=lambda x: x[0])
        low = min(rated, key=lambda x: x[0])
        cards.append(poster('best', 'their career', top[0], top[1], k, top[2], keys, up='../'))
        cards.append(poster('worst', 'their career', low[0], low[1], k, low[2], keys, up='../'))
    win_run, loss_run, now_run = player_streaks(a)
    for run, kind, title in ((win_run, 'best', 'Best win streak'), (loss_run, 'worst', 'Worst losing streak')):
        if not run:
            cards.append(f'<div class="poster {kind}"><h3>{title}</h3><div class="poster-rating">None yet</div></div>')
            continue
        first, last = run[0][0], run[-1][0]
        cards.append(f'<div class="poster {kind}"><h3>{title}</h3><div class="poster-name">{len(run)} in a row</div>'
                     f'<div><a href="../games/{first["info"]["id"]}.html">{when(first)}</a> to '
                     f'<a href="../games/{last["info"]["id"]}.html">{when(last)}</a></div></div>')
    finished = [(g, p) for g, p in a['log'] if p['finished'] and g['info']['winner']]
    form = ''.join(f'<a class="{"win" if p["team"] == g["info"]["winner"] else "loss"}" href="../games/{g["info"]["id"]}.html" '
                   f'title="{when(g)}">{"W" if p["team"] == g["info"]["winner"] else "L"}</a>' for g, p in finished[-10:])
    chart = rating_chart([(game_rating(p), (g, p['team'] == g['info']['winner']))
                          for g, p in a['log'] if p['finished'] and p['minutes'] >= 5])
    if r['rating_pg'] is None:
        rating_line = ''
    elif k in ranks:
        rating_line = (f'Average game rating <b>{r["rating_pg"]:+.2f}</b>, '
                       f'<b>{ranks[k][0]}</b> of {ranks[k][1]} players with {MIN_GAMES}+ games.')
    else:
        rating_line = (f'Average game rating <b>{r["rating_pg"]:+.2f}</b> '
                       f'(ranked once they have {MIN_GAMES} finished games).')
    current = (f'Current streak: {len(now_run)} {"win" if now_run[0][1] else "loss"}{"" if len(now_run) == 1 else ("s" if now_run[0][1] else "es")} in a row.'
               if now_run else '')

    withs, against = with_against(k, a, per)
    rows = []
    for g, p in reversed(a['log']):
        info, l = g['info'], p['lists']
        result = 'left' if not p['finished'] else ('won' if p['team'] == info['winner'] else 'lost')
        rating = game_rating(p) if p['finished'] else None
        rows.append(
            f'<tr class="{p["team"]}-team"><td data-v="{info["at"]}"><a href="../games/{info["id"]}.html">{when(g)}</a></td>'
            f'<td>{result}</td><td>{info["score"]["red"]}–{info["score"]["blue"]}</td>' + cell(rating, 2) + cell(p['goals']) + cell(p['assists'])
            + cell(p['second_assists']) + f'<td data-v="{p["passes"]}">{p["passes"]}/{p["throws"]}</td>'
            + cell(p['possessions_touched']) + cell(p['turnovers']) + cell(sum(l['xpoints_given']), 2)
            + cell(p['points_given']) + cell(p['steals']) + cell(p['interceptions']) + cell(sum(l['xpoints_taken']), 2) + '</tr>')
    losses = a['games'] - a['wins']
    left_count = len(a['log']) - a['games']
    left = f', plus {left_count} they left early' if left_count else ''
    body = (f'<h1>{esc(a["name"])}</h1>'
            f'<p><b>{a["wins"]} wins, {losses} losses</b> ({a["wins"] / max(a["games"], 1):.0%}) in {a["games"]} finished ranked games'
            f'{left}. {current} '
            '<a href="../players.html">All players</a></p>'
            f'<p>{rating_line}</p>'
            + (f'<p class="form">Last {len(finished[-10:])} games, oldest first: {form}</p>' if form else '')
            + '<h2>Best and worst</h2><p class="explain"><b>Game rating</b> = points scored + ½ per assist + ¼ per second assist '
            '+ expected points taken away − expected points given up (only games they finished, 5+ minutes). '
            'Streaks count only games they finished.</p>' + ''.join(cards)
            + '<h2>Game rating over time</h2>' + (chart or '<p>Not enough games yet.</p>')
            + f'<h2>Stats</h2><table><caption>Per game</caption>{summary}</table>'
            + '<h2>With and against</h2><p class="explain">Their wins and losses with each teammate and against each opponent. '
            'Only players still in the game at the end count, on the team they finished on. Click a heading to sort.</p>'
            + best_worst_pairs(a['name'], withs, against, keys)
            + f'<p><a href="../compare.html?a={file_key(k)}">Compare {esc(a["name"])} head to head with someone</a></p>'
            + '<div class="pair-tables">' + pair_table('With each teammate (most games together first)', withs, keys)
            + pair_table('Against each opponent', against, keys) + '</div>'
            + '<h2>Every game</h2>'
            '<div class="wide"><table class="sortable"><caption>Newest first. Click a date to see the game.</caption><thead><tr><th>Date</th><th>Result</th>'
            '<th>Score (red–blue)</th><th>Game rating</th><th>Goals</th><th>Assists</th><th>2nd assists</th><th>Passes / throws</th>'
            '<th>Possessions touched</th><th>Turnovers</th><th>xP given up</th><th>Points given up</th><th>Steals</th>'
            '<th>Interceptions</th><th>xP taken away</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
            + DEFINITIONS)
    text = page(f'{a["name"]} – Eggball', None, body, depth=1)
    return text.replace('</style>', POSTER_CSS + PROFILE_CSS + '</style>', 1)


PROFILE_CSS = """
.pair-table { display: inline-table; vertical-align: top; margin-right: 24px; }
"""


def game_rating(p):
    """One number for a single game: points scored, plus half a point per assist and a quarter per second
    assist, plus expected points taken away by steals and interceptions, minus expected points given up by turnovers."""
    l = p['lists']
    return (p['points_scored'] + 0.5 * p['assists'] + 0.25 * p['second_assists']
            + sum(l['xpoints_taken']) - sum(l['xpoints_given']))


POSTER_CSS = """
.poster { display: inline-block; vertical-align: top; width: 330px; max-width: 100%; box-sizing: border-box; margin: 0 14px 18px 0; padding: 12px 16px;
          border: 4px solid #333; background: #fffbea; }
.poster.worst { background: #fdeeee; border-color: #a33; }
.poster.best { background: #eef8ee; border-color: #383; }
.poster h3 { margin: 0 0 2px; font-size: 0.95em; text-transform: uppercase; letter-spacing: 1px; }
.poster .poster-name { font-size: 2em; font-weight: bold; margin: 4px 0; }
.poster .poster-rating { font-size: 1.3em; font-weight: bold; }
.poster table { margin: 6px 0; }
.poster td { white-space: normal; }
"""


def poster(kind, period, rating, g, k, p, keys, up=''):
    info, l = g['info'], p['lists']
    result = 'won' if p['team'] == info['winner'] else 'lost'
    name = f'<a href="{up}players/{file_key(k)}.html">{esc(p["name"])}</a>' if k in keys else esc(p['name'])
    lines = [('Goals', p['goals']), ('Assists', p['assists']), ('2nd assists', p['second_assists']),
             ('Passes / throws', f'{p["passes"]}/{p["throws"]}'),
             ('Turnovers', f'{p["turnovers"]} ({p["sacked"]} sacked, {p["throws_lost"]} throws lost)'),
             ('Points scored off their turnovers', p['points_given']),
             ('xP given up', f'{sum(l["xpoints_given"]):.2f}'),
             ('Steals / interceptions', f'{p["steals"]} / {p["interceptions"]}'),
             ('xP taken away', f'{sum(l["xpoints_taken"]):.2f}')]
    rows = ''.join(f'<tr><td>{a}</td><td>{b}</td></tr>' for a, b in lines)
    return (f'<div class="poster {kind}"><h3>{"Best" if kind == "best" else "Worst"} game: {period}</h3>'
            f'<div class="poster-name">{name}</div>'
            f'<div class="poster-rating">Game rating {rating:+.2f}</div>'
            f'<div>{p["team"].capitalize()}, {result} {info["score"]["red"]}–{info["score"]["blue"]} (red–blue), '
            f'<a href="{up}games/{info["id"]}.html">{when(g)}</a></div>'
            f'<table>{rows}</table></div>')


def streaks(games, per, keep):
    """Longest run of wins and of losses in a row for each player, using only their finished games
    that pass keep(datetime). Returns [(length, kind, name, key, first game, last game)]."""
    history = collections.defaultdict(list)
    for g in games:
        at = datetime.datetime.fromtimestamp(g['info']['at'] / 1000)
        if not keep(at):
            continue
        for k, p in per[g['info']['id']]['players'].items():
            if p['finished'] and g['info']['winner']:
                history[k].append((g, p['name'], p['team'] == g['info']['winner']))
    out = []
    for k, items in history.items():
        for want in (True, False):
            best, run = None, []
            for g, name, won in items:
                run = run + [g] if won == want else []
                if run and (best is None or len(run) > len(best[0])):
                    best = (run, name)
            if best:
                out.append((len(best[0]), 'win' if want else 'loss', best[1], k, best[0][0], best[0][-1]))
    return out


def streak_section(games, per, now):
    periods = [('all time', lambda at: True),
               ('last 7 days', lambda at: at >= now - datetime.timedelta(days=7)),
               ('today', lambda at: at.date() == now.date())]
    parts = ['<h2>Streaks</h2><p class="explain">Wins or losses in a row, counting only games the player finished.</p>']
    for kind, title, css in (('win', 'Best win streak', 'best'), ('loss', 'Worst losing streak', 'worst')):
        for period, keep in periods:
            pool = [x for x in streaks(games, per, keep) if x[1] == kind]
            if not pool:
                parts.append(f'<p>No games {period} yet.</p>')
                continue
            top = max(x[0] for x in pool)
            tied = sorted([x for x in pool if x[0] == top], key=lambda x: x[2].lower())
            names = ', '.join(f'<a href="players/{file_key(x[3])}.html">{esc(x[2])}</a>' for x in tied)
            spans = '<br>'.join(f'{esc(x[2])}: <a href="games/{x[4]["info"]["id"]}.html">{when(x[4])}</a> to '
                                f'<a href="games/{x[5]["info"]["id"]}.html">{when(x[5])}</a>' for x in tied[:5])
            parts.append(f'<div class="poster {css}"><h3>{title}: {period}</h3><div class="poster-name">{names}</div>'
                         f'<div class="poster-rating">{top} {"wins" if kind == "win" else "losses"} in a row</div>'
                         f'<div>{spans}{"<br>and more" if len(tied) > 5 else ""}</div></div>')
    return '\n'.join(parts)


def posters_page(games, per, keys):
    now = datetime.datetime.now()
    entries = []
    for g in games:
        at = datetime.datetime.fromtimestamp(g['info']['at'] / 1000)
        for k, p in per[g['info']['id']]['players'].items():
            if p['finished'] and p['minutes'] >= 5:
                entries.append((game_rating(p), at, g, k, p))
    periods = [('all time', lambda at: True),
               ('last 7 days', lambda at: at >= now - datetime.timedelta(days=7)),
               ('today', lambda at: at.date() == now.date())]
    body = ['<h1>Best and worst: single games and streaks</h1>',
            '<p class="explain"><b>Game rating</b> = points scored + ½ per assist + ¼ per second assist '
            '+ expected points taken away (steals and interceptions) − expected points given up (turnovers). '
            'Only players who played 5+ minutes and finished the game. "Today" and "last 7 days" use the server\'s clock (Pacific time). '
            f'Updated {now:%Y-%m-%d %H:%M}.</p>']
    for kind in ('best', 'worst'):
        body.append(f'<h2>{"Best" if kind == "best" else "Worst"} stat lines</h2>')
        for period, keep in periods:
            pool = [e for e in entries if keep(e[1])]
            if not pool:
                body.append(f'<p>No games {period} yet.</p>')
                continue
            e = max(pool, key=lambda e: e[0]) if kind == 'best' else min(pool, key=lambda e: e[0])
            body.append(poster(kind, period, e[0], e[2], e[3], e[4], keys))
        # runners-up, all time
        ranked = sorted(entries, key=lambda e: e[0], reverse=kind == 'best')[:10]
        body.append(f'<table><caption>{"Best" if kind == "best" else "Worst"} 10 all time</caption>'
                    '<tr><th>Player</th><th>Rating</th><th>Game</th><th>Goals</th><th>Assists</th><th>Turnovers</th></tr>'
                    + ''.join(f'<tr><td>{esc(p["name"])}</td><td>{r:+.2f}</td><td><a href="games/{g["info"]["id"]}.html">{when(g)}</a></td>'
                              f'<td>{p["goals"]}</td><td>{p["assists"]}</td><td>{p["turnovers"]}</td></tr>'
                              for r, at, g, k, p in ranked) + '</table>')
    body.append(streak_section(games, per, now))
    text = page('Eggball Best and Worst Games', 'posters.html', '\n'.join(body))
    return text.replace('</style>', POSTER_CSS + '</style>', 1)


def home_page(games, per, total, keys):
    """Today at a glance: today's games, best and worst stat lines today, who is on a streak, the latest results."""
    now = datetime.datetime.now()
    today = [g for g in games if datetime.datetime.fromtimestamp(g['info']['at'] / 1000).date() == now.date()]
    parts = [f'<h1>Eggball ranked: today</h1><p class="explain">Stats from every ranked game on playeggball.com, '
             f'updated every 10 minutes while games are being played (every 30 minutes when they are not). '
             f'Last updated {now:%Y-%m-%d %H:%M} (Pacific time).</p>']
    if today:
        goals = sum(g['info']['score']['red'] + g['info']['score']['blue'] for g in today)
        people = {k for g in today for k, p in per[g['info']['id']]['players'].items() if p['finished']}
        parts.append(f'<p><b>{len(today)} games today</b>, {goals} goals, {len(people)} different players.</p>')
        entries = [(game_rating(p), g, k, p) for g in today for k, p in per[g['info']['id']]['players'].items()
                   if p['finished'] and p['minutes'] >= 5]
        if entries:
            hi = max(entries, key=lambda e: e[0])
            lo = min(entries, key=lambda e: e[0])
            parts.append(poster('best', 'today', hi[0], hi[1], hi[2], hi[3], keys)
                         + poster('worst', 'today', lo[0], lo[1], lo[2], lo[3], keys))
    else:
        parts.append('<p><b>No ranked games yet today.</b></p>')

    # streaks still going, for players seen in the last 7 days
    recent = now - datetime.timedelta(days=7)
    going = []
    for k, a in total.items():
        win_run, loss_run, run = player_streaks(a)
        if len(run) >= 2 and datetime.datetime.fromtimestamp(run[-1][0]['info']['at'] / 1000) >= recent:
            going.append((len(run), run[-1][1], k, a))

    def streak_table(won, title):
        rows = sorted((x for x in going if x[1] == won), key=lambda x: (-x[0], x[3]['name'].lower()))[:8]
        body = ''.join(f'<tr><td><a href="players/{file_key(k)}.html">{esc(a["name"])}</a></td><td>{n}</td></tr>'
                       for n, _, k, a in rows) or '<tr><td colspan="2">No one</td></tr>'
        return (f'<table style="display:inline-table; margin-right:18px; vertical-align:top"><caption>{title}</caption>'
                f'<tr><th>Player</th><th>In a row</th></tr>{body}</table>')
    parts.append('<h2>Streaks going right now</h2><p class="explain">Players who played in the last 7 days, '
                 'counting games they finished. Two or more in a row.</p>'
                 + streak_table(True, 'Winning streaks') + streak_table(False, 'Losing streaks'))

    rows = []
    for g in list(reversed(games))[:15]:
        info, ps = g['info'], per[g['info']['id']]['players']
        rated = [(game_rating(p), k, p) for k, p in ps.items() if p['finished'] and p['minutes'] >= 5]
        star = ''
        if rated:
            r, k, p = max(rated, key=lambda x: x[0])
            star = (f'<a href="players/{file_key(k)}.html">{esc(p["name"])}</a> ({r:+.2f})' if k in keys else esc(p['name']))
        winner = info['winner'] or ''
        rows.append(f'<tr class="{winner}-team"><td><a href="games/{info["id"]}.html">{when(g)}</a></td>'
                    f'<td>{winner}</td><td>{info["score"]["red"]}–{info["score"]["blue"]}</td><td>{length(g)}</td><td>{star}</td></tr>')
    parts.append('<h2>Latest games</h2><table><tr><th>Date</th><th>Winner</th><th>Score (red–blue)</th>'
                 '<th>Length</th><th>Best player</th></tr>' + ''.join(rows) + '</table>'
                 '<p><a href="games.html">Every game</a> · <a href="players.html">Every player</a> · '
                 '<a href="posters.html">Best and worst of all time</a> · <a href="compare.html">Head to head</a></p>')
    text = page('Eggball Ranked Stats', 'home.html', '\n'.join(parts))
    return text.replace('</style>', POSTER_CSS + '</style>', 1)


def compare_page(games, per, total):
    """Pick two players: their record together and against each other, and their stats side by side.
    The page does the counting itself from a small table of every game."""
    order = sorted((k for k, a in total.items() if a['games']), key=lambda k: -total[k]['games'])
    index = {k: i for i, k in enumerate(order)}
    columns = [(f, label, places, as_pct) for f, label, places, as_pct in AGG_COLUMNS]

    def shown(v, places, as_pct):
        if v is None:
            return ''
        return pct(v) if as_pct else num(v, places)
    players = [[total[k]['name'], file_key(k), [shown(total[k]['row'][f], pl, ap) for f, _, pl, ap in columns]]
               for k in order]
    rows = []
    for g in games:
        info = g['info']
        if not info['winner']:
            continue
        line = [[index[k], 0 if p['team'] == 'red' else 1, round(game_rating(p), 2)]
                for k, p in per[info['id']]['players'].items() if p['finished'] and k in index]
        rows.append([info['id'], when(g), 0 if info['winner'] == 'red' else 1,
                     f'{info["score"]["red"]}–{info["score"]["blue"]}', line])
    data = json.dumps({'players': players, 'columns': [label for _, label, _, _ in columns], 'games': rows},
                      separators=(',', ':')).replace('</', '<\\/')
    body = ('<h1>Head to head</h1><p class="explain">Pick two players to see how they do on the same team and against each other. '
            'Only games both of them finished count. Wins and losses are the first player\'s.</p>'
            '<p><label>First player <select id="first-player"></select></label> '
            '<label>Second player <select id="second-player"></select></label> '
            '<button id="swap-players">Swap</button></p>'
            '<div id="compare-result"></div>'
            '<script>\nvar COMPARE = ' + data + ';\n' + r"""
(function () {
  var inLoader = !!window.EGGBALL_LOADER;   // the GitHub page that loads this one sets this
  function playerLink(i) {
    var p = COMPARE.players[i];
    var href = inLoader ? '?player=' + p[1] : 'players/' + p[1] + '.html';
    return '<a href="' + href + '">' + esc(p[0]) + '</a>';
  }
  function gameLink(id, text) { return '<a href="' + (inLoader ? '?game=' + id : 'games/' + id + '.html') + '">' + text + '</a>'; }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
  var first = document.getElementById('first-player'), second = document.getElementById('second-player');
  COMPARE.players.forEach(function (p, i) {
    first.add(new Option(p[0], i));
    second.add(new Option(p[0], i));
  });
  var query = new URLSearchParams(location.search);
  function find(file, fallback) {
    for (var i = 0; i < COMPARE.players.length; i++) if (COMPARE.players[i][1] === file) return i;
    return fallback;
  }
  first.value = find(query.get('a'), 0);
  second.value = find(query.get('b'), first.value === '0' ? 1 : 0);

  function show() {
    var a = +first.value, b = +second.value, out = document.getElementById('compare-result');
    var q = new URLSearchParams(location.search);
    q.set('a', COMPARE.players[a][1]); q.set('b', COMPARE.players[b][1]);
    history.replaceState(null, '', '?' + q.toString());
    if (a === b) { out.innerHTML = '<p>Pick two different players.</p>'; return; }
    var together = [0, 0], against = [0, 0], list = [];
    COMPARE.games.forEach(function (g) {
      var pa = null, pb = null;
      g[4].forEach(function (x) { if (x[0] === a) pa = x; if (x[0] === b) pb = x; });
      if (!pa || !pb) return;
      var won = pa[1] === g[2], same = pa[1] === pb[1];
      (same ? together : against)[won ? 0 : 1]++;
      list.push([g, same, won, pa[2], pb[2]]);
    });
    function rec(r) { return r[0] + r[1] ? r[0] + '–' + r[1] + ' (' + Math.round(100 * r[0] / (r[0] + r[1])) + '%)' : 'no games'; }
    var A = playerLink(a), B = playerLink(b);
    var html = '<table><caption>Records (' + esc(COMPARE.players[a][0]) + '\'s wins and losses)</caption>' +
      '<tr><td>Same team</td><td>' + rec(together) + '</td></tr>' +
      '<tr><td>' + A + ' against ' + B + '</td><td>' + rec(against) + '</td></tr></table>';
    html += '<table><caption>Stats per game, all their games</caption><tr><th></th><th>' + A + '</th><th>' + B + '</th></tr>' +
      COMPARE.columns.map(function (c, i) {
        return '<tr><td>' + esc(c) + '</td><td>' + COMPARE.players[a][2][i] + '</td><td>' + COMPARE.players[b][2][i] + '</td></tr>';
      }).join('') + '</table>';
    html += '<table><caption>Their games together, newest first (game rating for each)</caption><tr><th>Date</th><th>Score (red–blue)</th>' +
      '<th>Teams</th><th>' + esc(COMPARE.players[a][0]) + '</th><th>' + A + ' rating</th><th>' + B + ' rating</th></tr>' +
      (list.reverse().map(function (x) {
        return '<tr><td>' + gameLink(x[0][0], x[0][1]) + '</td><td>' + x[0][3] + '</td><td>' + (x[1] ? 'same team' : 'against') +
          '</td><td class="' + (x[2] ? 'win">won' : 'loss">lost') + '</td><td>' + x[3].toFixed(2) + '</td><td>' + x[4].toFixed(2) + '</td></tr>';
      }).join('') || '<tr><td colspan="6">They have not finished a game together.</td></tr>') + '</table>';
    out.innerHTML = html;
  }
  first.onchange = second.onchange = show;
  document.getElementById('swap-players').onclick = function () { var t = first.value; first.value = second.value; second.value = t; show(); };
  show();
})();
</script>""")
    return page('Eggball Head to Head', 'compare.html', body)


def main():
    games = load_games()
    for g in games:
        link_goals_to_possessions(g)
    table = expected_points_table(games)
    per = {g['info']['id']: per_game(g, table) for g in games}
    total = aggregate(games, per)
    name_profiles(total)
    os.makedirs(os.path.join(SITE, 'games'), exist_ok=True)
    os.makedirs(os.path.join(SITE, 'players'), exist_ok=True)

    def write(rel, text):
        path = os.path.join(SITE, rel)
        tmp = path + '.tmp'
        open(tmp, 'w').write(text)
        os.replace(tmp, path)

    write('games.html', games_page(games, per))
    keys = set(total)
    for g in games:
        write(f'games/{g["info"]["id"]}.html', game_page(g, per[g['info']['id']], keys))
    write('players.html', players_page(total, table))
    write('posters.html', posters_page(games, per, keys))
    write('home.html', home_page(games, per, total, keys))
    write('compare.html', compare_page(games, per, total))
    # for the search box and the With and Against page: every player's name and page, most games first
    order = sorted((k for k in total), key=lambda k: -len(total[k]['log']))
    write('players.json', json.dumps([[total[k]['name'], file_key(k)] for k in order]))
    write('profile_files.json', json.dumps({k: file_key(k) for k in total}))
    ranked = sorted((k for k, a in total.items() if a['games'] >= MIN_GAMES and a['row']['rating_pg'] is not None),
                    key=lambda k: -total[k]['row']['rating_pg'])
    ranks = {k: (i + 1, len(ranked)) for i, k in enumerate(ranked)}
    for k, a in total.items():
        write(f'players/{file_key(k)}.html', player_page(k, a, per, keys, ranks))
    # drop pages left from before (old account-id names, or a player who changed name)
    wanted = {file_key(k) + '.html' for k in total}
    for f in os.listdir(os.path.join(SITE, 'players')):
        if f.endswith('.html') and f not in wanted:
            os.remove(os.path.join(SITE, 'players', f))
    print(f'{len(games)} games, {len(total)} players -> {SITE}')


if __name__ == '__main__':
    main()
