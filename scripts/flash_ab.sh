#!/usr/bin/env bash
# (blueshell) Flash count A/B on MKW's attract demos (no input: the title cycles through scenes, where the flashes are
# most common): every frame into a frame log (RX_VK_FRAMELOG), counted by scripts/framelog.py.
#   bash scripts/flash_ab.sh <name> <seconds> "<extra env A=1;B=2>"
set -u
cd "$(dirname "$0")/.."
name=$1; secs=${2:-360}; extra=${3:-}
run=work/runs/$name
rm -rf "$run"; mkdir -p "$run"
log=$(cygpath -w "$PWD/$run")\\frames.bin
: > "$run/frames.bin.go"
powershell -NoProfile -File scripts/run-vk.ps1 -Window -Seconds "$secs" -Name "$name" -ShotEvery 100000 -MaxGB 12 \
    -Priority BelowNormal -Env "RX_VK_FRAMELOG=$log;HOS_INPUT_EXCLUSIVE=1;$extra;"
python -I scripts/framelog.py "$run/frames.bin" "$run/flashes.png" | tail -15
grep -o "([0-9.]* fps" "$run/log.txt" | tail -40 | tr -d '(' | awk '{s+=$1;n++} END {if (n) printf "mean fps %.1f over %d samples\n", s/n, n}'
# the game's clock against real time (60 = real speed), loading samples (the first 4) left out
grep -o "the game's clock ran [0-9.]*" "$run/log.txt" | awk 'NR > 4 {v=$NF; s+=v; n++; if (v < 55) low++} END {if (n) printf "game clock %.1f vsyncs/s mean, %d of %d samples under 55\n", s/n, low, n}'
