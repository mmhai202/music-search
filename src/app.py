#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser


APP_NAME = "Music Search"
APP_ID = "music-search"
IS_FROZEN = getattr(sys, "frozen", False)
ALLOW_SOURCE_RUN = os.environ.get("MUSIC_SEARCH_ALLOW_SOURCE_RUN") == "1"
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
RUNTIME_ROOT = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
PUBLIC = RESOURCE_ROOT / "web"


def app_version():
    candidates = [
        RESOURCE_ROOT / "VERSION",
        Path(__file__).resolve().parents[1] / "build_linux" / "VERSION",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    return "0.0.0"


APP_VERSION = app_version()
ARTIFACT_NAME = f"MusicSearch-{APP_VERSION}-{os.uname().machine}.AppImage"


def app_state_dir():
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / APP_ID
    return Path.home() / ".local" / "state" / APP_ID


STATE_DIR = app_state_dir()
HISTORY_FILE = STATE_DIR / "history.jsonl"
HISTORY_LIMIT = 10
HOST = os.environ.get("HOST", "127.0.0.1")
PORT_ENV = os.environ.get("PORT")
PORT = int(PORT_ENV or "8765")
OPEN_BROWSER = os.environ.get("OPEN_BROWSER", "1") != "0"
SYSTEM_ATTEMPT_MARKS = (3, 6)
DEFAULT_UPLOAD_SECONDS = 10
RATE = 44100
CHANNELS = 1
BITS = 32
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MIN_AUDIO_SECONDS = 3
ALLOWED_UPLOAD_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".flac", ".ogg", ".webm"}
ALLOWED_UPLOAD_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/flac",
    "audio/x-flac",
    "audio/ogg",
    "video/mp4",
    "video/webm",
    "application/ogg",
}

recognize_lock = threading.Lock()


class AppError(RuntimeError):
    def __init__(self, message, status=400, code="bad_request"):
        super().__init__(message)
        self.status = status
        self.code = code


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


def executable_path(name):
    candidates = [
        RESOURCE_ROOT / "bin" / name,
        RUNTIME_ROOT / "bin" / name,
        Path(__file__).resolve().parent / "bin" / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    found = shutil.which(name)
    if found:
        return found
    raise AppError(
        f"Không tìm thấy {name}. Hãy đặt file này trong thư mục bin cạnh ứng dụng.",
        status=503,
        code="missing_dependency",
    )


def run_text(args):
    resolved = [executable_path(args[0]), *args[1:]]
    return subprocess.run(resolved, text=True, capture_output=True, check=False)


def user_error_message(error):
    message = str(error)
    lowered = message.lower()
    if "does not contain any stream" in lowered:
        return "Không tìm thấy audio trong file."
    if "invalid data found when processing input" in lowered:
        return "Định dạng file không đọc được. Thử file MP3, WAV, M4A, MP4, FLAC, OGG hoặc WEBM."
    if "file audio khong co du lieu am thanh doc duoc" in lowered:
        return "File không có audio đọc được."
    return message


def validate_upload_type(filename, content_type):
    suffix = Path(filename).suffix.lower()
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if suffix in ALLOWED_UPLOAD_EXTENSIONS:
        return
    if normalized_type in ALLOWED_UPLOAD_TYPES:
        return
    raise AppError(
        "Chỉ hỗ trợ file MP3, WAV, M4A, MP4, FLAC, OGG hoặc WEBM.",
        status=415,
        code="unsupported_upload_type",
    )


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

    if sinks:
        raise AppError(
            "Không có audio đang phát. Mở nhạc hoặc video rồi thử lại.",
            status=409,
            code="no_audio_playing",
        )

    raise AppError(
        "Không tìm thấy thiết bị audio để thu âm.",
        status=503,
        code="audio_device_not_found",
    )


def capture_audio(device, seconds):
    cmd = [
        executable_path("ffmpeg"),
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


def decode_audio_file(audio_bytes, seconds, start_seconds=0):
    cmd = [
        executable_path("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-ss",
        str(start_seconds),
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
    proc = subprocess.run(cmd, input=audio_bytes, capture_output=True, check=False)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        if "does not contain any stream" in err.lower():
            raise AppError("Không tìm thấy audio trong file.", status=415, code="no_audio_stream")
        raise AppError(
            user_error_message(err or "ffmpeg khong doc duoc file audio"),
            status=415,
            code="unsupported_audio_file",
        )
    return proc.stdout


def recognize_pcm(pcm, seconds):
    cmd = [
        executable_path("vibra"),
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


def result_from_track(track, started, seconds, source, filename=""):
    title = track.get("title") or ""
    artist = track.get("subtitle") or ""
    href = ((track.get("share") or {}).get("href") or "")
    cover_url = first_image_url(track)

    if not title:
        return None

    result = {
        "ok": True,
        "found": True,
        "id": "",
        "title": title,
        "artist": artist,
        "href": href,
        "cover_url": cover_url,
        "source": source,
        "seconds": seconds,
        "elapsed": round(time.time() - started, 2),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if filename:
        result["filename"] = filename
    result["id"] = history_id(result)
    return result


def write_history(items):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
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
    STATE_DIR.mkdir(parents=True, exist_ok=True)
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
        raise AppError(
            "Đang có lượt nhận diện khác chạy. Chờ lượt hiện tại kết thúc rồi thử lại.",
            status=409,
            code="recognition_busy",
        )

    try:
        started = time.time()
        device = detect_device()
        pcm = b""
        prev_mark = 0

        for mark in SYSTEM_ATTEMPT_MARKS:
            chunk_seconds = mark - prev_mark
            prev_mark = mark
            pcm += capture_audio(device, chunk_seconds)

            data = recognize_pcm(pcm, mark)
            track = data.get("track") or {}
            result = result_from_track(track, started, mark, "system")

            if result:
                result["device"] = device
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


def recognize_uploaded_file(audio_bytes, filename="", start_seconds=0, end_seconds=0):
    if not recognize_lock.acquire(blocking=False):
        raise AppError(
            "Đang có lượt nhận diện khác chạy. Chờ lượt hiện tại kết thúc rồi thử lại.",
            status=409,
            code="recognition_busy",
        )

    try:
        started = time.time()
        requested_range = (end_seconds or start_seconds + DEFAULT_UPLOAD_SECONDS) - start_seconds
        requested_seconds = max(MIN_AUDIO_SECONDS, math.ceil(requested_range))
        pcm = decode_audio_file(audio_bytes, requested_seconds, start_seconds)
        bytes_per_second = RATE * CHANNELS * (BITS // 8)
        if not pcm:
            raise AppError("File không có audio đọc được.", status=415, code="empty_audio")

        final_seconds = max(1, math.ceil(len(pcm) / bytes_per_second))
        if final_seconds < MIN_AUDIO_SECONDS:
            raise AppError(
                "File audio quá ngắn. Cần tối thiểu 3 giây để nhận diện.",
                status=422,
                code="audio_too_short",
            )

        data = recognize_pcm(pcm, final_seconds)
        track = data.get("track") or {}
        result = result_from_track(track, started, final_seconds, "upload", filename)
        if result:
            result["start_seconds"] = start_seconds
            result["end_seconds"] = start_seconds + final_seconds
            save_history(result)
            return result

        return {
            "ok": True,
            "found": False,
            "source": "upload",
            "filename": filename,
            "start_seconds": start_seconds,
            "end_seconds": start_seconds + final_seconds,
            "elapsed": round(time.time() - started, 2),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
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

    def send_error_json(self, error):
        if isinstance(error, AppError):
            payload = {"ok": False, "error": str(error), "code": error.code}
            self.send_json(error.status, payload)
            return
        self.send_json(
            500,
            {"ok": False, "error": user_error_message(error), "code": "server_error"},
        )

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

        if parsed.path == "/api/recognize-file":
            try:
                content_length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                self.send_json(400, {"ok": False, "error": "Content-Length không hợp lệ.", "code": "bad_content_length"})
                return
            if content_length <= 0:
                self.send_json(400, {"ok": False, "error": "Chọn một file audio trước khi nhận diện.", "code": "missing_audio_file"})
                return
            if content_length > MAX_UPLOAD_BYTES:
                self.send_json(413, {"ok": False, "error": "File audio quá lớn, tối đa 50MB.", "code": "file_too_large"})
                return

            filename = urllib.parse.unquote(self.headers.get("X-Filename", "")).strip()
            content_type = self.headers.get("Content-Type", "")
            try:
                validate_upload_type(filename, content_type)
            except AppError as exc:
                self.send_error_json(exc)
                return
            try:
                start_seconds = max(0, float(self.headers.get("X-Start-Seconds") or "0"))
                end_seconds = max(start_seconds + 1, float(self.headers.get("X-End-Seconds") or str(start_seconds + DEFAULT_UPLOAD_SECONDS)))
            except ValueError:
                self.send_json(400, {"ok": False, "error": "Khoảng audio đã chọn không hợp lệ.", "code": "invalid_selected_range"})
                return

            audio_bytes = self.rfile.read(content_length)
            try:
                self.send_json(200, recognize_uploaded_file(audio_bytes, filename, start_seconds, end_seconds))
            except Exception as exc:
                self.send_error_json(exc)
            return

        if parsed.path != "/api/recognize":
            self.send_error(404)
            return

        try:
            self.send_json(200, recognize_track())
        except Exception as exc:
            self.send_error_json(exc)


def make_server():
    if PORT_ENV:
        return ThreadingHTTPServer((HOST, PORT), Handler), PORT

    for port in range(PORT, PORT + 20):
        try:
            return ThreadingHTTPServer((HOST, port), Handler), port
        except OSError:
            continue
    return ThreadingHTTPServer((HOST, 0), Handler), 0


def main():
    if not IS_FROZEN and not ALLOW_SOURCE_RUN:
        print(
            "Music Search is intended to run from the packaged Linux artifact.\n"
            "Build it with: bash build_linux/build_linux.sh --clean\n"
            f"Then run: ./build_linux/dist/{ARTIFACT_NAME}",
            file=sys.stderr,
        )
        return 1

    server, port = make_server()
    if port == 0:
        port = server.server_address[1]
    url = f"http://{HOST}:{port}"
    print(f"Music Search running at {url}")
    if OPEN_BROWSER:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
