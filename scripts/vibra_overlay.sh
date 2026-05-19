#!/bin/bash
# bash /home/hai/scripts/vibra_overlay.sh

PIPE="/tmp/vibra_pipe"

rm -f "$PIPE"
mkfifo "$PIPE"

cleanup() {
  rm -f "$PIPE"
  printf '\n'
}

trap cleanup EXIT INT TERM

echo "Vibra overlay ready. Waiting for updates..."
exec 3<> "$PIPE"

while IFS= read -r line <&3; do
  cols="${COLUMNS:-$(tput cols 2>/dev/null || echo 80)}"
  max_cols=$((cols - 1))
  if [ "$max_cols" -lt 10 ]; then
    max_cols=10
  fi

  if [ "${#line}" -gt "$max_cols" ]; then
    line="${line:0:$max_cols}"
  fi

  printf '\r\033[2K%s' "$line"
done
