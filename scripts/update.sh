#!/bin/bash
# Hourly (systemd user timer eggball-stats.timer): download new ranked replays, rebuild the page, push if it changed.
set -e
DATA=~/tagpro-analytics/data/playeggball
python3 -u ~/tagpro-analytics/scripts/fetch_playeggball_replays.py "$DATA"
python3 ~/tagpro-analytics/scripts/playeggball_with_against.py "$DATA"
cd ~/eggball-stats
cp "$DATA/with_against.html" index.html
cp ~/tagpro-analytics/scripts/fetch_playeggball_replays.py ~/tagpro-analytics/scripts/playeggball_with_against.py scripts/
git add -A
git diff --cached --quiet && { echo "no change"; exit 0; }
git commit -q -m "Update stats $(date '+%Y-%m-%d %H:%M')"
git push -q
echo pushed
