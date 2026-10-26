# Eggball Stats

Ranked players' wins and losses with and against every other player, from playeggball.com replays.

Page: https://bambitp.github.io/eggball-stats/

To update:
1. `python3 scripts/fetch_playeggball_replays.py` downloads new ranked replays (the site only lists its newest 1000 games, so run it every few days)
2. `python3 scripts/playeggball_with_against.py` builds with_against.html; copy it here as index.html
