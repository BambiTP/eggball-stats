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

Since November 4, 2026 the stats are password protected ("Password protected until unbanned"). Replays and stats are still collected. The live server only answers with the password, logs every password try and every page viewed, and shows who got in on a report page on the home computer's private network. The November 2 saved copies (`archive/`) were taken off this site.
