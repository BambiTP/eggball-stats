#!/bin/bash
# The timer (eggball-live.timer) starts this every 10 minutes. During game time (a ranked game in the last hour)
# it runs every time; when games have stopped it only runs every 30 minutes and skips the other runs.
# Each run downloads new ranked replays and rebuilds the live site
# in ~/eggball-live/site, which eggball-live-server serves and eggball-live-tunnel puts on the internet.
# GitHub (bambitp.github.io/eggball-stats) is no longer updated; it keeps the stats it already had.
set -e
DATA=~/tagpro-analytics/data/playeggball
SCRIPTS=~/tagpro-analytics/scripts
SITE=~/eggball-live/site
mkdir -p "$SITE"
LAST_RUN=~/eggball-live/last-run
# minutes since the newest saved game, and since the last run that did not skip
QUIET=$(python3 -c "import json,time; g=json.load(open('$DATA/games.json')); print(int((time.time()*1000-max(x['at'] for x in g))/60000))")
SINCE_RUN=$(( ($(date +%s) - $(stat -c %Y "$LAST_RUN" 2>/dev/null || echo 0)) / 60 ))
if [ "$QUIET" -ge 60 ] && [ "$SINCE_RUN" -lt 29 ]; then
  echo "$(date '+%F %T') no games for $QUIET minutes, last run $SINCE_RUN minutes ago: skipping (quiet time runs every 30 minutes)"
  exit 0
fi
touch "$LAST_RUN"
echo "$(date '+%F %T') newest game $QUIET minutes ago: updating"
python3 -u "$SCRIPTS/fetch_playeggball_replays.py" "$DATA"
# the game and player pages first: they write profile_files.json, which the With and Against page links names with
python3 "$SCRIPTS/eggball_games/build_site.py" "$SITE"
export EGGBALL_EXTRA_TABS='<a href="games.html">Games</a> <a href="players.html">Players</a> <a href="posters.html">Best and worst</a> <a href="compare.html">Head to head</a>'
export EGGBALL_PROFILE_FILES="$SITE/profile_files.json"
python3 "$SCRIPTS/playeggball_with_against.py" "$DATA"
cp "$DATA/with_against.html" "$SITE/index.html.tmp" && mv "$SITE/index.html.tmp" "$SITE/index.html"
python3 "$SCRIPTS/eggball_score_comparison.py" "$SITE/scores.html"
