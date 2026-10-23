#!/bin/bash
# Reports which meme tests are stopped (the hourly check then restarts them with run_in_background).
cd /home/claude/meme
start() { # name script log datadir
  if grep -q "WEEK DONE" "$3" 2>/dev/null; then echo "$1: week done"; return; fi
  if pgrep -f "python3 [${2:0:1}]${2:1} run" >/dev/null; then echo "$1: running"; return; fi
  echo "$1: STOPPED -> restart with: cd /home/claude/meme && timeout 7150 python3 $2 run 7000 >> $3 2>&1"
}
start main meme_live.py run.log
start earlybird earlybird.py eb_run.log
start v2 v2.py v2_run.log
start snipe snipe.py snipe_run.log
