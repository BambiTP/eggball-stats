# Eggball Stats

Stats from every ranked game on playeggball.com: today's games, every game and player, best and worst games
and streaks, head to head, and each player's wins and losses with and against everyone else.

Page: https://bambitp.github.io/eggball-stats/

## How it works

The stats are built on a home computer and served through a Cloudflare quick tunnel. `index.html` (and `live.html`,
the same file) looks up the tunnel's current address in a gist and loads the live pages into itself.

Short addresses: `?player=Bambi`, `?game=<id>`, `?page=games`, `players`, `best-and-worst`, `head-to-head`,
`with-and-against`, `final-scores`. No address shows the home page.

On the home computer (`scripts/live-update.sh`, started by a systemd timer every 10 minutes; when no ranked
game has been played for an hour it only runs every 30 minutes):
1. `fetch_playeggball_replays.py` downloads new ranked replays
2. `eggball_games/build_site.py` builds home, games, players, profiles, best and worst, head to head
3. `playeggball_with_against.py` builds With and Against (names link to the profiles from step 2)
4. `eggball_score_comparison.py` builds Final scores (TPM on tagpro.eu vs playeggball)

`live-server.py` serves the pages; `live-tunnel.py` runs the tunnel and writes its address to the gist.

`archive/` has saved copies of With and Against and Final scores from November 2, 2026, linked when the live site is offline.
