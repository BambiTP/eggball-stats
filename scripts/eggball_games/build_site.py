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
MERGE = {'Bambi1': 'Bambi', 'waoter': '3'}   # alt name -> main name, same as the with/against page
MIN_GAMES = 20
BIN = 10   # yards per expected-points bucket

TABS = [('index.html', 'With and Against'), ('scores.html', 'Final scores: TPM vs playeggball'),
        ('games.html', 'Games'), ('players.html', 'Players'), ('posters.html', 'Best and worst')]

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
.wide { overflow-x: auto; }
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


def file_key(key):
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
    ('Player', None), ('Min', 'minutes'), ('Goals', 'goals'), ('Assists', 'assists'),
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
            f'<tr class="{p["team"]}-team"><td>{name}</td>' + cell(p['minutes']) + cell(p['goals']) + cell(p['assists'])
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
    kickoff = g['possessions'][0]['start'] if g['possessions'] else 0

    def clock(ms):
        ms = max(0, ms - kickoff)
        return f'{ms // 60000}:{ms // 1000 % 60:02d}'
    goal_rows = ''.join(
        f'<tr class="{x["team"]}-team"><td>{clock(x["time"])}</td><td>{x["red"]}–{x["blue"]}</td>'
        f'<td>{esc(names.get(x["scorer"], ""))}</td><td>{esc(names.get(x["assist"], ""))}</td>'
        f'<td>{esc(names.get(x["second_assist"], ""))}</td><td>{"yes" if x["boat"] else ""}</td>'
        f'<td>{"" if x["passes"] is None else x["passes"]}</td>'
        f'<td>{num(x.get("possession_seconds"))}</td><td>{num(x.get("possession_start_yard"))}</td></tr>'
        for x in g['goals'])
    body = (f'<h1>{info["score"]["red"]}–{info["score"]["blue"]}: {esc(info["map"])}, {when(g)}</h1>'
            f'<p>Length {length(g)}. Winner: {esc(info["winner"] or "none")}'
            f'{" (mercy)" if (g.get("over") or {}).get("mercy") else ""}. First goal: {esc(s["first"] or "none")}. '
            f'Lead changes: {s["lead_changes"]}. <a href="../games.html">All games</a></p>'
            + team_table
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
                                     'team_rate_touched': 0.0, 'log': []})
            a['name'] = p['name']
            if not p['finished']:
                a['log'].append((g, p))
                continue
            a['games'] += 1
            a['wins'] += p['team'] == winner
            a['minutes'] += p['minutes']
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
    ('games', 'Games', 0, False), ('win_rate', 'Win %', 0, True),
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
        '<h2>Offense</h2><p class="explain">Only stats that don\'t depend on where players are. '
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
    body = (f'<h1>Eggball ranked players</h1><p>Lists rank players with at least {MIN_GAMES} finished games. '
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


def player_page(k, a):
    r = a['row']
    summary = ''.join(f'<tr><td>{label}</td>{cell(r[f], places, as_pct)}</tr>' for f, label, places, as_pct in AGG_COLUMNS)
    rows = []
    for g, p in reversed(a['log']):
        info, l = g['info'], p['lists']
        result = 'left' if not p['finished'] else ('won' if p['team'] == info['winner'] else 'lost')
        rows.append(
            f'<tr class="{p["team"]}-team"><td data-v="{info["at"]}"><a href="../games/{info["id"]}.html">{when(g)}</a></td>'
            f'<td>{result}</td><td>{info["score"]["red"]}–{info["score"]["blue"]}</td>' + cell(p['goals']) + cell(p['assists'])
            + cell(p['second_assists']) + f'<td data-v="{p["passes"]}">{p["passes"]}/{p["throws"]}</td>'
            + cell(p['possessions_touched']) + cell(p['turnovers']) + cell(sum(l['xpoints_given']), 2)
            + cell(p['points_given']) + cell(p['steals']) + cell(p['interceptions']) + cell(sum(l['xpoints_taken']), 2) + '</tr>')
    body = (f'<h1>{esc(a["name"])}</h1><p>{a["games"]} finished ranked games, {a["wins"]} won. '
            '<a href="../players.html">All players</a></p>'
            f'<table><caption>Per game</caption>{summary}</table>'
            '<div class="wide"><table class="sortable"><caption>Every game (newest first)</caption><thead><tr><th>Date</th><th>Result</th>'
            '<th>Score (red–blue)</th><th>Goals</th><th>Assists</th><th>2nd assists</th><th>Passes / throws</th>'
            '<th>Possessions touched</th><th>Turnovers</th><th>xP given up</th><th>Points given up</th><th>Steals</th>'
            '<th>Interceptions</th><th>xP taken away</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
            + DEFINITIONS)
    return page(f'{a["name"]} – Eggball', None, body, depth=1)


def game_rating(p):
    """One number for a single game: points scored, plus half a point per assist and a quarter per second
    assist, plus expected points taken away by steals and interceptions, minus expected points given up by turnovers."""
    l = p['lists']
    return (p['points_scored'] + 0.5 * p['assists'] + 0.25 * p['second_assists']
            + sum(l['xpoints_taken']) - sum(l['xpoints_given']))


POSTER_CSS = """
.poster { display: inline-block; vertical-align: top; width: 330px; margin: 0 14px 18px 0; padding: 12px 16px;
          border: 4px solid #333; background: #fffbea; }
.poster.worst { background: #fdeeee; border-color: #a33; }
.poster.best { background: #eef8ee; border-color: #383; }
.poster h3 { margin: 0 0 2px; font-size: 0.95em; text-transform: uppercase; letter-spacing: 1px; }
.poster .poster-name { font-size: 2em; font-weight: bold; margin: 4px 0; }
.poster .poster-rating { font-size: 1.3em; font-weight: bold; }
.poster table { margin: 6px 0; }
.poster td { white-space: normal; }
"""


def poster(kind, period, rating, g, k, p, keys):
    info, l = g['info'], p['lists']
    result = 'won' if p['team'] == info['winner'] else 'lost'
    name = f'<a href="players/{file_key(k)}.html">{esc(p["name"])}</a>' if k in keys else esc(p['name'])
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
            f'<a href="games/{info["id"]}.html">{when(g)}</a></div>'
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


def main():
    games = load_games()
    for g in games:
        link_goals_to_possessions(g)
    table = expected_points_table(games)
    per = {g['info']['id']: per_game(g, table) for g in games}
    total = aggregate(games, per)
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
    for k, a in total.items():
        write(f'players/{file_key(k)}.html', player_page(k, a))
    print(f'{len(games)} games, {len(total)} players -> {SITE}')


if __name__ == '__main__':
    main()
