#!/bin/bash
# Every 10 minutes (systemd user timer eggball-live.timer): download new ranked replays and rebuild the live site
# in ~/eggball-live/site, which eggball-live-server serves and eggball-live-tunnel puts on the internet.
# GitHub (bambitp.github.io/eggball-stats) is no longer updated; it keeps the stats it already had.
set -e
DATA=~/tagpro-analytics/data/playeggball
SCRIPTS=~/tagpro-analytics/scripts
SITE=~/eggball-live/site
mkdir -p "$SITE"
python3 -u "$SCRIPTS/fetch_playeggball_replays.py" "$DATA"
export EGGBALL_EXTRA_TABS='<a href="games.html">Games</a> <a href="players.html">Players</a>'
python3 "$SCRIPTS/playeggball_with_against.py" "$DATA"
cp "$DATA/with_against.html" "$SITE/index.html.tmp" && mv "$SITE/index.html.tmp" "$SITE/index.html"
python3 "$SCRIPTS/eggball_score_comparison.py" "$SITE/scores.html"
python3 "$SCRIPTS/eggball_games/build_site.py" "$SITE"
