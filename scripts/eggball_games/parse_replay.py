"""Read one playeggball.com replay (.eggball-replay.gz) into possessions, passes, goals and turnovers.

File format (version 3): first line is JSON {"eggballReplay": 3, "info": {...}}; every other line is
"<ms>\t<kind>\t<json>". The kinds used here:
  players   {"list": [{id, name, team, ...}]}           a player joins (team is "red"/"blue")
  update    {"tick", "moves": [[id, px, py, vx, vy, spin?, turn?]], "changes": [...]}
            moves are sent about 4 times a second; a null means "same as last time"
  eggState  {"state": ""|"waiting"|"huddle"|"play", "holder": player id or null}
  body      the egg in flight after a throw (px, py, vx, vy); "shown": true on the first one
  score     {"red": n, "blue": n}; a Raptor Boat sends two of these at the same moment
  boat      a Raptor Boat happened
  tiles     endzone tiles change (halftime switch); {"x": 1, ..., "to": "R"} means red now scores on the left
  result    the final box score for every player

Field: 64 x 22 tiles of 0.4 units, walls on the outside. The playable area runs x = 0 .. 24.8.
Endzones are the 3 tiles at each end (x < 1.2 and x > 23.6). The 22.4 units between them are 100 yards.
Red scores in the endzone made of "R" tiles (the right one at kickoff, the left one after halftime).
"""
import gzip
import json

TILE = 0.4
FIELD_LEFT = 3 * TILE    # goal line of the left endzone
FIELD_RIGHT = 24.8 - 3 * TILE
YARDS_PER_UNIT = 100 / (FIELD_RIGHT - FIELD_LEFT)


def yards_from_own_goal(x, attacks_right):
    """0 = your own goal line, 100 = the goal line you score on."""
    y = (x - FIELD_LEFT) * YARDS_PER_UNIT if attacks_right else (FIELD_RIGHT - x) * YARDS_PER_UNIT
    return max(0.0, min(100.0, y))


def parse(path):
    lines = gzip.open(path, 'rt').read().split('\n')
    head = json.loads(lines[0])
    info = head['info']
    # player id -> "red"/"blue", from the header; "players" lines below fill in anyone missing
    team = {p['id']: p['team'] for p in info['players'] if 'id' in p}
    name = {p['id']: p['name'] for p in info['players'] if 'id' in p}
    pos = {}           # player id -> [ms, px, py, vx, vy]
    red_attacks_right = True
    state = ''
    holder = None
    last_thrower = None
    egg_xy = None      # last egg position in flight
    score = {'red': 0, 'blue': 0}
    result = None
    over = None

    possessions = []
    poss = None        # the open possession
    goals = []
    passes = []        # every throw: thrower, catcher, outcome
    open_throw = None
    boat_time = -10**9
    halftime = None

    def where(pid, t):
        p = pos.get(pid)
        if not p or p[1] is None or p[2] is None:
            return None
        dt = min(max(t - p[0], 0), 300) / 1000
        return (p[1] + (p[3] or 0) * dt, p[2] + (p[4] or 0) * dt)

    def attacks_right(tm):
        return red_attacks_right if tm == 'red' else not red_attacks_right

    def yard(pid, t, tm=None):
        xy = where(pid, t)
        if xy is None:
            return None
        return round(yards_from_own_goal(xy[0], attacks_right(tm or team[pid])), 1)

    def start_possession(t, tm, how, pid, forced_by=None, lost_by=None):
        nonlocal poss
        poss = {'team': tm, 'start': t, 'how': how, 'start_yard': yard(pid, t, tm) if pid else None,
                'touches': [pid] if pid else [], 'passes': 0, 'end': None, 'end_how': None,
                'end_yard': None, 'lost_by': None, 'forced_by': None,
                'came_from_turnover_by': lost_by, 'came_from_forced_by': forced_by}
        possessions.append(poss)

    def end_possession(t, how, yard_value=None, lost_by=None, forced_by=None):
        nonlocal poss
        if poss is None:
            return
        poss.update(end=t, end_how=how, end_yard=yard_value, lost_by=lost_by, forced_by=forced_by)
        poss = None

    for line in lines[1:]:
        if not line:
            continue
        a, kind, data = line.split('\t', 2)
        t = int(a)
        if kind == 'players':
            for p in json.loads(data)['list']:
                team[p['id']] = p['team']
                name[p['id']] = p['name']
                if p.get('px') is not None:
                    pos[p['id']] = [t, p['px'], p['py'], p.get('vx', 0), p.get('vy', 0)]
        elif kind == 'update':
            for m in json.loads(data)['moves']:
                old = pos.get(m[0], [t, None, None, 0, 0])
                new = [t] + [m[i] if i < len(m) and m[i] is not None else old[i] for i in range(1, 5)]
                pos[m[0]] = new
        elif kind == 'tiles':
            halftime = t
            for tile in json.loads(data)['list']:
                if tile['x'] == 1:
                    red_attacks_right = tile['to'] != 'R'
                    break
        elif kind == 'body':
            b = json.loads(data)
            egg_xy = (b['px'], b['py'])
        elif kind == 'boat':
            # sent just before the score packets of a Raptor Boat
            boat_time = t
        elif kind == 'score':
            new = json.loads(data)
            for tm in ('red', 'blue'):
                gained = new[tm] - score[tm]
                if gained > 0:
                    if goals and t - goals[-1]['time'] < 50 and goals[-1]['team'] == tm:
                        goals[-1]['points'] += gained
                    else:
                        scorer = holder if holder is not None and team.get(holder) == tm else None
                        g = {'time': t, 'team': tm, 'scorer': scorer, 'points': gained, 'boat': t - boat_time < 50,
                             'assist': None, 'second_assist': None, 'passes': None,
                             'red': new['red'], 'blue': new['blue']}
                        if poss and poss['team'] == tm:
                            touches = poss['touches']
                            chain = [p for i, p in enumerate(touches) if i == 0 or p != touches[i - 1]]
                            if len(chain) >= 2 and chain[-1] == scorer:
                                g['assist'] = chain[-2]
                            if len(chain) >= 3 and chain[-1] == scorer:
                                g['second_assist'] = chain[-3]
                            g['passes'] = poss['passes']
                            g['possession_seconds'] = round((t - poss['start']) / 1000, 1)
                            g['possession_start_yard'] = poss['start_yard']
                        goals.append(g)
                        end_possession(t, 'goal', 100.0)
            score = {**score, **new}
            goals and goals[-1].update(red=score['red'], blue=score['blue'])
        elif kind == 'eggState':
            d = json.loads(data)
            st, h = d['state'], d['holder']
            if st == 'play' and state != 'play' and h is not None:
                # kickoff: the possession starts when play starts, wherever the holder is then
                end_possession(t, 'stop')
                start_possession(t, team[h], 'kickoff', h)
                last_thrower = None
                open_throw = None
            elif st == 'play' and state == 'play' and h != holder:
                if holder is not None and h is None:
                    # a throw
                    last_thrower = holder
                    open_throw = {'time': t, 'thrower': holder, 'team': team[holder],
                                  'from_yard': yard(holder, t), 'catcher': None, 'outcome': None}
                    passes.append(open_throw)
                elif holder is None and h is not None:
                    tm = team[h]
                    if open_throw and open_throw['outcome'] is None:
                        if h == open_throw['thrower']:
                            open_throw['outcome'] = 'own'
                        elif tm == open_throw['team']:
                            open_throw['outcome'] = 'complete'
                        else:
                            open_throw['outcome'] = 'intercepted'
                        open_throw['catcher'] = h
                    if poss and poss['team'] == tm:
                        if last_thrower is not None and h != last_thrower and team.get(last_thrower) == tm:
                            poss['passes'] += 1
                        poss['touches'].append(h)
                    else:
                        thrower = last_thrower if last_thrower is not None and team.get(last_thrower) != tm else None
                        catch_yard = yard(h, t)
                        if poss:
                            # yard line from the side that lost it
                            end_possession(t, 'intercepted', None if catch_yard is None else round(100 - catch_yard, 1),
                                           lost_by=thrower, forced_by=h)
                        start_possession(t, tm, 'interception', h, forced_by=h, lost_by=thrower)
                elif holder is not None and h is not None:
                    tm = team[h]
                    if tm != team[holder]:
                        lost_yard = yard(holder, t)
                        end_possession(t, 'sacked', lost_yard, lost_by=holder, forced_by=h)
                        start_possession(t, tm, 'steal', h, forced_by=h, lost_by=holder)
                    else:
                        # thrown and caught by a teammate within one update: a completed pass
                        passes.append({'time': t, 'thrower': holder, 'team': tm, 'from_yard': yard(holder, t),
                                       'catcher': h, 'outcome': 'complete'})
                        if poss:
                            poss['passes'] += 1
                            poss['touches'].append(h)
            state, holder = st, h
        elif kind == 'result':
            result = json.loads(data)
        elif kind == 'over':
            over = json.loads(data)
    end_possession(int(lines[-2].split('\t', 1)[0]) if len(lines) > 2 else 0, 'end')
    return {'info': info, 'team': team, 'name': name, 'possessions': possessions, 'goals': goals,
            'passes': passes, 'result': result, 'over': over, 'halftime': halftime}


if __name__ == '__main__':
    import sys
    g = parse(sys.argv[1])
    print(json.dumps({k: v for k, v in g.items() if k not in ('possessions', 'passes')}, indent=1)[:3000])
    for p in g['possessions'][:25]:
        print(p)
