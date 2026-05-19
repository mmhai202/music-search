#!/bin/bash
PIPE="/tmp/vibra_pipe"
DEVICE="${VIBRA_DEVICE:-}"
LISTEN_SECONDS=3
MAX_SECONDS=10
ATTEMPT_MARKS=(3 5 8 10)

update_overlay() {
  printf '%s\n' "$1" > "$PIPE"
}

elapsed_s() {
  local ms="$1"
  awk -v v="$ms" 'BEGIN { printf "%.2f", v / 1000 }'
}

monitor_for_sink() {
  local sink="$1"

  pactl list sinks 2>/dev/null | awk -v target="$sink" '
    BEGIN { RS = ""; FS = "\n" }
    {
      name = "";
      monitor = "";
      for (i = 1; i <= NF; i++) {
        line = $i;
        sub(/^[ \t]+/, "", line);
        if (line ~ /^Name:/) {
          sub(/^Name:[ \t]*/, "", line);
          name = line;
        } else if (line ~ /^Monitor Source:/) {
          sub(/^Monitor Source:[ \t]*/, "", line);
          monitor = line;
        }
      }
      if (name == target && monitor != "") {
        print monitor;
        exit;
      }
    }
  '
}

detect_device() {
  local device default_sink

  if ! command -v pactl >/dev/null 2>&1; then
    return 1
  fi

  device="$(
    pactl list sinks 2>/dev/null | awk '
      BEGIN { RS = ""; FS = "\n" }
      {
        state = "";
        monitor = "";
        for (i = 1; i <= NF; i++) {
          line = $i;
          sub(/^[ \t]+/, "", line);
          if (line ~ /^State:/) {
            sub(/^State:[ \t]*/, "", line);
            state = line;
          } else if (line ~ /^Monitor Source:/) {
            sub(/^Monitor Source:[ \t]*/, "", line);
            monitor = line;
          }
        }
        if (state == "RUNNING" && monitor != "") {
          print monitor;
          exit;
        }
      }
    '
  )"
  if [ -n "$device" ]; then
    printf '%s\n' "$device"
    return 0
  fi

  default_sink="$(pactl get-default-sink 2>/dev/null)"
  if [ -n "$default_sink" ]; then
    device="$(monitor_for_sink "$default_sink")"
    if [ -n "$device" ]; then
      printf '%s\n' "$device"
      return 0
    fi
  fi

  pactl list sinks 2>/dev/null | awk '
    BEGIN { RS = ""; FS = "\n" }
    {
      for (i = 1; i <= NF; i++) {
        line = $i;
        sub(/^[ \t]+/, "", line);
        if (line ~ /^Monitor Source:/) {
          sub(/^Monitor Source:[ \t]*/, "", line);
          print line;
          exit;
        }
      }
    }
  '
}

TMP_JSON="$(mktemp /tmp/vibra_result.XXXX.json)"
PCM_RAW="$(mktemp /tmp/vibra_audio.XXXX.pcm)"
trap 'rm -f "$TMP_JSON" "$PCM_RAW"' EXIT

start_ns=$(date +%s%N)
update_overlay "Listening..."

if [ -z "$DEVICE" ]; then
  DEVICE="$(detect_device)"
fi
if [ -z "$DEVICE" ]; then
  update_overlay "No PulseAudio sink monitor found"
  exit 1
fi

found=0
TITLE=""
ARTIST=""
prev_mark=0

for mark in "${ATTEMPT_MARKS[@]}"; do
  if [ "$mark" -gt "$MAX_SECONDS" ]; then
    mark="$MAX_SECONDS"
  fi
  if [ "$mark" -le "$prev_mark" ]; then
    continue
  fi
  chunk=$((mark - prev_mark))
  prev_mark="$mark"

  # Capture only the next chunk and append it to cumulative PCM buffer.
  if ! ffmpeg -hide_banner -loglevel error \
    -f pulse -i "$DEVICE" -t "$chunk" \
    -ac 1 -ar 44100 -f s32le - \
    >> "$PCM_RAW"
  then
    end_ns=$(date +%s%N)
    elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
    update_overlay "vibra/ffmpeg failed [$(elapsed_s "$elapsed_ms")s]"
    exit 1
  fi

  # Recognize on the full cumulative audio (3s, then 5s, then 8s, then 10s).
  if ! cat "$PCM_RAW" \
    | vibra --recognize --seconds "$mark" --rate 44100 --channels 1 --bits 32 > "$TMP_JSON"
  then
    end_ns=$(date +%s%N)
    elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
    update_overlay "vibra failed [$(elapsed_s "$elapsed_ms")s]"
    exit 1
  fi

  TITLE="$(jq -r '.track.title // empty' "$TMP_JSON")"
  ARTIST="$(jq -r '.track.subtitle // empty' "$TMP_JSON")"
  if [ -n "$TITLE" ]; then
    found=1
    break
  fi
done

end_ns=$(date +%s%N)
elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
elapsed="$(elapsed_s "$elapsed_ms")"

if [ "$found" -eq 1 ] && [ -n "$TITLE" ] && [ -n "$ARTIST" ]; then
  update_overlay "♪ $TITLE - $ARTIST [${elapsed}s]"
elif [ "$found" -eq 1 ] && [ -n "$TITLE" ]; then
  update_overlay "♪ $TITLE [${elapsed}s]"
else
  update_overlay "No match found [${elapsed}s]"
fi
