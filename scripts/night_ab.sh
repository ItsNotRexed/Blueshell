#!/usr/bin/env bash
# (blueshell) Flash A/Bs in a row on the attract demos, one flash_ab.sh run per "name|env" argument; touch work/runs/STOP to end
# the batch after the run in progress.
#   bash scripts/night_ab.sh <seconds> "base|" "nomotion|RX_VK_NO_MOTION_WB=1" ...
set -u
cd "$(dirname "$0")/.."
secs=$1; shift
rm -f work/runs/STOP
for spec in "$@"; do
    [ -e work/runs/STOP ] && { echo "stopped before ${spec%%|*}"; break; }
    name=${spec%%|*}; envs=${spec#*|}
    echo "=== $name ($envs)"
    bash scripts/flash_ab.sh "$name" "$secs" "$envs" 2>&1 | tail -7
done
echo "batch done"
