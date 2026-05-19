#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.parse


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "web"
HISTORY_FILE = ROOT / "history.jsonl"
HISTORY_LIMIT = 10
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
ATTEMPT_MARKS = (3, 5, 8, 10)
RATE = 44100
CHANNELS = 1
BITS = 32

recognize_lock = threading.Lock()


def history_id(item):
    raw = "\x1f".join(
        str(item.get(key, ""))
        for key in ("title", "artist", "href", "created_at")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def normalize_history_item(item):
    normalized = dict(item)
    normalized.setdefault("id", history_id(normalized))
    return normalized


def run_text(args):
    return subprocess.run(args, text=True, capture_output=True, check=False)


def parse_sinks(pactl_output):
    sinks = []
    current = {}

    for raw_line in pactl_output.splitlines():
        line = raw_line.strip()
        if raw_line.startswith("Sink #"):
            if current:
                sinks.append(current)
            current = {}
        elif line.startswith("Name:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("State:"):
            current["state"] = line.split(":", 1)[1].strip()
        elif line.startswith("Monitor Source:"):
            current["monitor"] = line.split(":", 1)[1].strip()

    if current:
        sinks.append(current)
    return sinks


def detect_device():
    forced = os.environ.get("VIBRA_DEVICE", "").strip()
    if forced:
        return forced

    listed = run_text(["pactl", "list", "sinks"])
    if listed.returncode != 0:
        raise RuntimeError("Khong doc duoc pactl list sinks")

    sinks = parse_sinks(listed.stdout)
    for sink in sinks:
        if sink.get("state") == "RUNNING" and sink.get("monitor"):
            return sink["monitor"]

    default = run_text(["pactl", "get-default-sink"])
    default_sink = default.stdout.strip() if default.returncode == 0 else ""
    if default_sink:
        for sink in sinks:
            if sink.get("name") == default_sink and sink.get("monitor"):
                return sink["monitor"]

    for sink in sinks:
        if sink.get("monitor"):
            return sink["monitor"]

    raise RuntimeError("Khong tim thay PulseAudio sink monitor")


def capture_audio(device, seconds):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "pulse",
        "-i",
        device,
        "-t",
        str(seconds),
        "-ac",
        str(CHANNELS),
        "-ar",
        str(RATE),
        "-f",
        "s32le",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err or "ffmpeg failed")
    return proc.stdout


def recognize_pcm(pcm, seconds):
    cmd = [
        "vibra",
        "--recognize",
        "--seconds",
        str(seconds),
        "--rate",
        str(RATE),
        "--channels",
        str(CHANNELS),
        "--bits",
        str(BITS),
    ]
    proc = subprocess.run(cmd, input=pcm, capture_output=True, check=False)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err or "vibra failed")

    raw = proc.stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"vibra returned invalid JSON: {exc}") from exc


def write_history(items):
    with HISTORY_FILE.open("w", encoding="utf-8") as fh:
        for history_item in items[-HISTORY_LIMIT:]:
            fh.write(json.dumps(history_item, ensure_ascii=False) + "\n")


def save_history(item):
    items = load_history(oldest_first=True)
    items.append(normalize_history_item(item))
    write_history(items)


def load_history(limit=HISTORY_LIMIT, oldest_first=False):
    if not HISTORY_FILE.exists():
        return []

    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
    items = []
    for line in lines:
        try:
            items.append(normalize_history_item(json.loads(line)))
        except json.JSONDecodeError:
            continue
    if oldest_first:
        return items
    return list(reversed(items))


def clear_history():
    HISTORY_FILE.write_text("", encoding="utf-8")


def delete_history_item(item_id):
    items = load_history(oldest_first=True)
    kept = [item for item in items if item.get("id") != item_id]
    write_history(kept)
    return kept


def first_image_url(track):
    images = track.get("images") or {}
    for key in ("coverart", "coverarthq", "background"):
        value = images.get(key)
        if value:
            return value

    for section in track.get("sections") or []:
        for metapage in section.get("metapages") or []:
            image = metapage.get("image")
            if image:
                return image

    return ""


def recognize_track():
    if not recognize_lock.acquire(blocking=False):
        raise RuntimeError("Dang nhan dien roi")

    try:
        started = time.time()
        device = detect_device()
        pcm = b""
        prev_mark = 0
        result = None

        for mark in ATTEMPT_MARKS:
            chunk_seconds = mark - prev_mark
            prev_mark = mark
            pcm += capture_audio(device, chunk_seconds)

            data = recognize_pcm(pcm, mark)
            track = data.get("track") or {}
            title = track.get("title") or ""
            artist = track.get("subtitle") or ""
            href = ((track.get("share") or {}).get("href") or "")
            cover_url = first_image_url(track)

            if title:
                result = {
                    "ok": True,
                    "found": True,
                    "id": "",
                    "title": title,
                    "artist": artist,
                    "href": href,
                    "cover_url": cover_url,
                    "device": device,
                    "seconds": mark,
                    "elapsed": round(time.time() - started, 2),
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                result["id"] = history_id(result)
                save_history(result)
                return result

        result = {
            "ok": True,
            "found": False,
            "device": device,
            "elapsed": round(time.time() - started, 2),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return result
    finally:
        recognize_lock.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/history":
            self.send_json(200, {"items": load_history()})
            return

        path = parsed.path
        if path == "/":
            path = "/index.html"

        target = (PUBLIC / path.lstrip("/")).resolve()
        if not str(target).startswith(str(PUBLIC.resolve())) or not target.exists():
            self.send_error(404)
            return

        content_type = "text/plain; charset=utf-8"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"

        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        path = "/index.html" if parsed.path == "/" else parsed.path
        target = (PUBLIC / path.lstrip("/")).resolve()
        if not str(target).startswith(str(PUBLIC.resolve())) or not target.exists():
            self.send_error(404)
            return

        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/clear-history":
            clear_history()
            self.send_json(200, {"ok": True, "items": []})
            return

        if parsed.path == "/api/delete-history":
            query = urllib.parse.parse_qs(parsed.query)
            item_id = (query.get("id") or [""])[0]
            if not item_id:
                self.send_json(400, {"ok": False, "error": "Missing history id"})
                return
            delete_history_item(item_id)
            self.send_json(200, {"ok": True, "items": load_history()})
            return

        if parsed.path != "/api/recognize":
            self.send_error(404)
            return

        try:
            self.send_json(200, recognize_track())
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Track web running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
