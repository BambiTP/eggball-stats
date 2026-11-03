"""Put the live eggball site (served on 127.0.0.1:8100) on the internet with a free Cloudflare quick tunnel,
and write the tunnel's address into a GitHub gist that bambitp.github.io/eggball-stats/live.html reads.
Quick tunnels get a new address every time cloudflared starts, so the address is republished each time.
usage: python3 tunnel.py   (needs cloudflared and a logged-in gh)"""
import json, re, subprocess, sys, time, urllib.request
from datetime import datetime, timezone

GIST = 'a591c82f75da2b09bdd7cb6b98b77db5'
FILE = 'eggball-live.json'
ORIGIN = 'http://127.0.0.1:8100'


def log(*a):
    print(datetime.now().isoformat(timespec='seconds'), *a, flush=True)


def publish(url):
    body = json.dumps({'files': {FILE: {'content': json.dumps({'url': url, 'at': datetime.now(timezone.utc).isoformat()})}}})
    subprocess.run(['gh', 'api', '-X', 'PATCH', 'gists/' + GIST, '--input', '-'], input=body.encode(),
                   stdout=subprocess.DEVNULL, check=True)
    log('published', url)


def answers(url):
    # new quick tunnels can take half a minute before they answer
    for _ in range(60):
        try:
            if urllib.request.urlopen(url + '/games.html', timeout=10).status == 200:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


while True:
    cf = subprocess.Popen(['cloudflared', 'tunnel', '--no-autoupdate', '--url', ORIGIN],
                          stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
    for line in cf.stderr:
        m = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
        if m:
            log('tunnel', m.group(0), 'waiting for it to answer')
            if answers(m.group(0)):
                publish(m.group(0))
            else:
                log('tunnel never answered; restarting')
                cf.kill()
            break
    for line in cf.stderr:   # keep reading so cloudflared never blocks on a full pipe
        pass
    cf.wait()
    log('cloudflared stopped, restarting in 10 s')
    time.sleep(10)
