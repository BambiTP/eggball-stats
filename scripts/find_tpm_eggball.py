"""Find every tagpro.eu eggball match (maps 14803 "eggball" and 8210 "Egg Ball") where a team name contains "tpm".
Reads every file in ~/tagpro.eu/manifest.json with 4 processes; writes ~/tagpro-analytics/data/tpm_eggball_matches.json."""
import sys, json, re
sys.path.insert(0, '/home/metjr/tagpro.eu')
from combine import matches
from pathlib import Path
from multiprocessing import Pool

EGG_MAP = re.compile(rb'"mapId":(14803|8210)[,}]')
TPM = re.compile(rb'tpm', re.I)

def scan(path):
    found = []
    for match_id, raw in matches(path):
        if not EGG_MAP.search(raw) or not TPM.search(raw):
            continue
        d = json.loads(raw)
        teams = d.get('teams') or []
        if any('tpm' in (t.get('name') or '').lower() for t in teams):
            found.append({'id': int(match_id), 'mapId': d['mapId'], 'date': d['date'], 'finished': d.get('finished'),
                          'duration': d.get('duration'), 'players': len(d.get('players') or []),
                          'teams': [{'name': t.get('name'), 'score': t.get('score')} for t in teams]})
    return found

if __name__ == '__main__':
    manifest = json.load(open('/home/metjr/tagpro.eu/manifest.json'))['files']
    files = sorted({Path('/home/metjr/tagpro.eu') / f['file'] for f in manifest}, key=lambda p: -p.stat().st_size)
    files = [p for p in files if p.stat().st_size > 1000]
    with Pool(4) as pool:
        by_id = {m['id']: m for part in pool.map(scan, files) for m in part}
    out = sorted(by_id.values(), key=lambda m: m['id'])
    json.dump(out, open('/home/metjr/tagpro-analytics/data/tpm_eggball_matches.json', 'w'))
    print(len(files), 'files', len(out), 'matches')
