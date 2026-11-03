"""Build ~/eggball-stats/scores.html: TPM eggball games on tagpro.eu vs playeggball.com ranked games, final scores.
Inputs: data/tpm_eggball_matches.json (from find_tpm_eggball.py) and data/playeggball/games.json."""
import json, math, statistics as st, collections, datetime, html

TPM_FILE = '/home/metjr/tagpro-analytics/data/tpm_eggball_matches.json'
PE_FILE = '/home/metjr/tagpro-analytics/data/playeggball/games.json'
import os, sys
OUT = sys.argv[1] if len(sys.argv) > 1 else '/home/metjr/eggball-stats/scores.html'
# more tab links (the live site adds Games and Players)
EXTRA_TABS = os.environ.get('EGGBALL_EXTRA_TABS', '')

tpm_all = json.load(open(TPM_FILE))
tpm_games = []  # (score a, score b, minutes)
for m in tpm_all:
    if not m['finished']:
        continue
    a, b = [t['score'] for t in m['teams']]
    tpm_games.append((a, b, m['duration'] / 3600))
pe_all = [g for g in json.load(open(PE_FILE)) if g['kind'] == 'ranked']
pe_games = [(g['score']['red'], g['score']['blue'], g['ms'] / 60000) for g in pe_all]


def numbers(games):
    total = [a + b for a, b, _ in games]
    margin = [abs(a - b) for a, b, _ in games]
    return {
        'games': len(games),
        'total': total,
        'winner': [max(a, b) for a, b, _ in games],
        'loser': [min(a, b) for a, b, _ in games],
        'margin': margin,
        'minutes': [d for *_, d in games],
        'per_minute': [(a + b) / d for a, b, d in games if d > 1],
        'ties': sum(a == b for a, b, _ in games) / len(games),
        'close': sum(x <= 1 for x in margin) / len(games),
        'blowout': sum(x >= 5 for x in margin) / len(games),
        'common': collections.Counter(f'{max(a, b)}-{min(a, b)}' for a, b, _ in games).most_common(8),
    }


T, P = numbers(tpm_games), numbers(pe_games)


def t_value(a, b):
    return (st.mean(a) - st.mean(b)) / math.sqrt(st.variance(a) / len(a) + st.variance(b) / len(b))


def avg(x, places=1):
    return f'{st.mean(x):.{places}f}'


def sd(x):
    return f'{st.stdev(x):.1f}'


def pct(x):
    return f'{x:.0%}'


tpm_names = collections.Counter()
for m in tpm_all:
    tpm_names[' vs '.join(sorted(t['name'] for t in m['teams']))] += 1
first_tpm = datetime.date.fromtimestamp(min(m['date'] for m in tpm_all))
last_tpm = datetime.date.fromtimestamp(max(m['date'] for m in tpm_all))
first_pe = datetime.date.fromtimestamp(min(g['at'] for g in pe_all) / 1000)
last_pe = datetime.date.fromtimestamp(max(g['at'] for g in pe_all) / 1000)
unfinished = len(tpm_all) - len(tpm_games)


def row(label, t, p, note=''):
    return f'<tr><td>{label}</td><td>{t}</td><td>{p}</td><td>{note}</td></tr>'


def bar_table(caption, buckets, t_values, p_values):
    """One row per bucket, a plain bar for each site showing the share of that site's games."""
    rows = []
    for label, test in buckets:
        t_share = sum(1 for v in t_values if test(v)) / len(t_values)
        p_share = sum(1 for v in p_values if test(v)) / len(p_values)
        rows.append(
            f'<tr><td>{label}</td>'
            f'<td><span class="bar tpm-bar" style="width:{t_share * 300:.0f}px"></span> {t_share:.0%}</td>'
            f'<td><span class="bar pe-bar" style="width:{p_share * 300:.0f}px"></span> {p_share:.0%}</td></tr>')
    return (f'<table><caption>{caption}</caption><tr><th></th><th>TPM</th><th>playeggball</th></tr>'
            + ''.join(rows) + '</table>')


margin_buckets = [('Tie', lambda v: v == 0), ('1 goal', lambda v: v == 1), ('2 goals', lambda v: v == 2),
                  ('3–4 goals', lambda v: 3 <= v <= 4), ('5–7 goals', lambda v: 5 <= v <= 7),
                  ('8–9 goals', lambda v: 8 <= v <= 9), ('10 or more', lambda v: v >= 10)]
total_buckets = [('Under 15', lambda v: v < 15), ('15–19', lambda v: 15 <= v <= 19), ('20–24', lambda v: 20 <= v <= 24),
                 ('25–29', lambda v: 25 <= v <= 29), ('30 or more', lambda v: v >= 30)]

common_rows = ''.join(
    f'<tr><td>{i + 1}</td><td>{t[0]} ({t[1] / T["games"]:.1%})</td><td>{p[0]} ({p[1] / P["games"]:.1%})</td></tr>'
    for i, (t, p) in enumerate(zip(T['common'], P['common'])))
name_rows = ''.join(f'<li>{html.escape(k)}: {v:,} games</li>' for k, v in tpm_names.most_common())

page = f'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eggball Final Scores</title>
<style>
body {{ font-family: sans-serif; max-width: 780px; margin: 16px auto; padding: 0 16px; line-height: 1.5; }}
table {{ border-collapse: collapse; margin: 12px 0 20px; }}
caption {{ font-weight: bold; text-align: left; padding: 4px 0; }}
th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; vertical-align: middle; }}
th {{ background: #eee; }}
.bar {{ display: inline-block; height: 12px; vertical-align: middle; }}
.tpm-bar {{ background: #4a7fc1; }}
.pe-bar {{ background: #d9822b; }}
#caveats {{ border: 1px solid #c9a227; background: #fdf6dc; padding: 4px 14px; }}
#short-answer {{ font-size: 1.1em; }}
#page-tabs {{ margin-bottom: 12px; border-bottom: 2px solid #999; }}
#page-tabs a {{ display: inline-block; padding: 6px 14px; border: 1px solid #999; border-bottom: none; text-decoration: none; color: #06c; }}
#page-tabs a.current-tab {{ background: #ddd; color: #000; font-weight: bold; }}
</style></head><body>
<nav id="page-tabs"><a href="index.html">With and Against</a> <a href="scores.html" class="current-tab">Final scores: TPM vs playeggball</a> {EXTRA_TABS}</nav>

<h1>Eggball final scores: TPM vs playeggball</h1>

<p id="short-answer"><b>Short answer:</b> playeggball ranked games end with about <b>{st.mean(P['total']) - st.mean(T['total']):.1f} more goals</b>
({avg(P['total'])} vs {avg(T['total'])}) and are <b>more one-sided</b> (the winner is ahead by {avg(P['margin'])} on average vs {avg(T['margin'])}).
Goals come at the <b>same speed</b> on both ({avg(P['per_minute'], 2)} vs {avg(T['per_minute'], 2)} per minute); the extra goals mostly come from playeggball games running longer.</p>

<div id="caveats">
<p><b>Read this first</b></p>
<ul>
<li>The two sets are from different times. TPM games: {first_tpm:%b %Y} to {last_tpm:%b %Y}. playeggball games: {first_pe:%b %d} to {last_pe:%b %d, %Y}. Players, skill and habits may have changed in between.</li>
<li>playeggball has only {P['games']:,} ranked games so far against {T['games']:,} TPM games, so its numbers are less certain (but still enough for the gaps below to be real, see the end).</li>
<li>The rules are not identical. TPM games stop at 8:00 and can end tied. playeggball games never tie and can run past 8 minutes.</li>
<li>Scores include Raptor Boats (2-point goals) on both sides; they are not split out here.</li>
</ul>
</div>

<h2>The main numbers</h2>
<p>"Spread" is the standard deviation: about two thirds of games land within that many goals of the average.</p>
<table>
<tr><th>Per game</th><th>TPM (tagpro.eu)</th><th>playeggball ranked</th><th></th></tr>
{row('Games', f"{T['games']:,}", f"{P['games']:,}")}
{row('<b>Total goals</b>', f"<b>{avg(T['total'])}</b> (spread {sd(T['total'])})", f"<b>{avg(P['total'])}</b> (spread {sd(P['total'])})", 'playeggball higher')}
{row('Winner scores', f"{avg(T['winner'])} (spread {sd(T['winner'])})", f"{avg(P['winner'])} (spread {sd(P['winner'])})", 'this is where the gap is')}
{row('Loser scores', f"{avg(T['loser'])} (spread {sd(T['loser'])})", f"{avg(P['loser'])} (spread {sd(P['loser'])})", 'about the same')}
{row('<b>Winning margin</b>', f"<b>{avg(T['margin'])}</b> (spread {sd(T['margin'])})", f"<b>{avg(P['margin'])}</b> (spread {sd(P['margin'])})", 'playeggball more one-sided')}
{row('Game length', f"{avg(T['minutes'])} min", f"{avg(P['minutes'])} min", 'TPM is nearly always 8:00')}
{row('<b>Goals per minute</b>', f"<b>{avg(T['per_minute'], 2)}</b>", f"<b>{avg(P['per_minute'], 2)}</b>", 'same pace')}
{row('Ties', pct(T['ties']), pct(P['ties']), 'playeggball has no ties')}
{row('Won by 1 or tied', pct(T['close']), pct(P['close']))}
{row('Won by 5 or more', pct(T['blowout']), pct(P['blowout']))}
</table>

<h2>How close are the games?</h2>
{bar_table('Winning margin (share of each site’s games)', margin_buckets, T['margin'], P['margin'])}
<p>TPM has more ties and one-goal games. playeggball has more games won by 5 or more. Neither site has a margin above 11, which looks like both end a game at a 10-goal lead.</p>

<h2>How many goals in a game?</h2>
{bar_table('Total goals (share of each site’s games)', total_buckets, T['total'], P['total'])}

<h2>Most common final scores</h2>
<table><tr><th>#</th><th>TPM</th><th>playeggball</th></tr>{common_rows}</table>
<p>TPM’s top four are all one-goal games. playeggball’s list mixes blowouts (13-3, 10-0, 15-5) with close games.</p>

<h2>Is the difference real or just luck?</h2>
<p>Yes, it is real. With this many games, the gap in total goals is {abs(t_value(T['total'], P['total'])):.1f} times bigger than random variation would explain,
and the gap in margin is {abs(t_value(T['margin'], P['margin'])):.1f} times bigger (anything over about 2 is usually counted as real).
That says the averages really differ, not why: the caveats above (different years, different rules) could be part of the reason.</p>

<h2>How this was made</h2>
<ul>
<li><b>TPM games:</b> every match in a full copy of tagpro.eu (all years) on the eggball maps ("eggball" and the older "Egg Ball") where a team name contains "tpm".
Found {len(tpm_all):,}; {unfinished} never finished and are left out. Team pairings:<ul>{name_rows}</ul></li>
<li><b>playeggball games:</b> every ranked game collected from playeggball.com since we started saving them (checked hourly). Casual games are left out.</li>
<li>Scores are the final team scores each site records.</li>
</ul>
<p>Made {datetime.date.today():%B %d, %Y}.</p>
</body></html>
'''
open(OUT, 'w').write(page)
print('wrote', OUT)
