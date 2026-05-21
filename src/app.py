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
DEBUG_TIMING = os.environ.get("MUSIC_SEARCH_DEBUG_TIMING") == "1"
AUTO_SHUTDOWN = os.environ.get("MUSIC_SEARCH_AUTO_SHUTDOWN", "1") != "0"
CLIENT_HEARTBEAT_TIMEOUT = 8
CLIENT_SHUTDOWN_GRACE = 2
SYSTEM_ATTEMPT_MARKS = (3, 6)
DEFAULT_UPLOAD_SECONDS = 10
RATE = 44100
CHANNELS = 1
BITS = 32
BYTES_PER_SECOND = RATE * CHANNELS * (BITS // 8)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MIN_AUDIO_SECONDS = 3
PCM_SIGNAL_THRESHOLD = 1024
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
history_lock = threading.RLock()
client_lock = threading.Lock()
client_seen = {}
client_tracking_started = False
shutdown_scheduled = False
http_server = None


class AppError(RuntimeError):
    def __init__(self, message, status=400, code="bad_request"):
        super().__init__(message)
        self.status = status
        self.code = code


def timing_log(label, started, **fields):
    if not DEBUG_TIMING:
        return

    elapsed = time.monotonic() - started
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    suffix = f" {details}" if details else ""
    print(f"[timing] {label} elapsed={elapsed:.3f}s{suffix}", file=sys.stderr)


def active_client_count(now=None):
    now = now or time.monotonic()
    expired_before = now - CLIENT_HEARTBEAT_TIMEOUT
    expired = [
        client_id
        for client_id, seen_at in client_seen.items()
        if seen_at < expired_before
    ]
    for client_id in expired:
        client_seen.pop(client_id, None)
    return len(client_seen)


def mark_client_seen(client_id):
    global client_tracking_started
    if not client_id or not AUTO_SHUTDOWN:
        return

    with client_lock:
        client_tracking_started = True
        client_seen[client_id] = time.monotonic()


def mark_client_closed(client_id):
    if not client_id or not AUTO_SHUTDOWN:
        return

    with client_lock:
        client_seen.pop(client_id, None)
        should_shutdown = client_tracking_started and active_client_count() == 0
    if should_shutdown:
        schedule_shutdown_if_idle("last client closed")


def schedule_shutdown_if_idle(reason):
    global shutdown_scheduled
    if not AUTO_SHUTDOWN:
        return

    with client_lock:
        if shutdown_scheduled:
            return
        shutdown_scheduled = True

    def shutdown_when_still_idle():
        global shutdown_scheduled
        time.sleep(CLIENT_SHUTDOWN_GRACE)
        with client_lock:
            shutdown_scheduled = False
            should_shutdown = client_tracking_started and active_client_count() == 0
        if should_shutdown and http_server:
            print(f"Music Search shutting down: {reason}", file=sys.stderr)
            http_server.shutdown()

    threading.Thread(target=shutdown_when_still_idle, daemon=True).start()


def monitor_clients():
    while True:
        time.sleep(1)
        with client_lock:
            should_shutdown = client_tracking_started and active_client_count() == 0
        if should_shutdown:
            schedule_shutdown_if_idle("browser heartbeat stopped")


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


def no_audio_playing_error():
    return AppError(
        "Không có audio đang phát. Mở nhạc hoặc video rồi thử lại.",
        status=409,
        code="no_audio_playing",
    )


def no_microphone_signal_error():
    return AppError(
        "Không nghe thấy âm thanh từ micro. Kiểm tra quyền micro hoặc thử nói gần micro hơn.",
        status=409,
        code="no_microphone_signal",
    )


def microphone_not_found_error():
    return AppError(
        "Không tìm thấy microphone để thu âm.",
        status=503,
        code="microphone_not_found",
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


def parse_sources(pactl_output):
    sources = []
    current = {}

    for raw_line in pactl_output.splitlines():
        line = raw_line.strip()
        if raw_line.startswith("Source #"):
            if current:
                sources.append(current)
            current = {}
        elif line.startswith("Name:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Description:"):
            current["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("State:"):
            current["state"] = line.split(":", 1)[1].strip()

    if current:
        sources.append(current)
    return sources


def list_audio_devices(kind="all"):
    listed_sources = run_text(["pactl", "list", "sources"])
    if listed_sources.returncode != 0:
        raise RuntimeError("Khong doc duoc pactl list sources")

    listed_sinks = run_text(["pactl", "list", "sinks"])
    if listed_sinks.returncode != 0:
        raise RuntimeError("Khong doc duoc pactl list sinks")

    running_monitors = {
        sink["monitor"]
        for sink in parse_sinks(listed_sinks.stdout)
        if sink.get("state") == "RUNNING" and sink.get("monitor")
    }

    devices = []
    for source in parse_sources(listed_sources.stdout):
        name = source.get("name") or ""
        if not name:
            continue
        state = source.get("state") or ""
        is_monitor = name.endswith(".monitor")
        device_kind = "monitor" if is_monitor else "input"
        if kind != "all" and device_kind != kind:
            continue
        devices.append(
            {
                "id": name,
                "label": source.get("description") or name,
                "state": state,
                "active": name in running_monitors if is_monitor else state == "RUNNING",
                "kind": device_kind,
            }
        )
    return devices


def list_system_audio_devices():
    return list_audio_devices("monitor")


def list_microphone_devices():
    return list_audio_devices("input")


def detect_device(selected_device=""):
    selected = selected_device.strip()
    if selected:
        devices = list_system_audio_devices()
        selected_info = next((device for device in devices if device["id"] == selected), None)
        if not selected_info:
            raise AppError(
                "Thiết bị audio đã chọn không còn khả dụng. Chọn Auto hoặc tải lại danh sách.",
                status=404,
                code="audio_device_not_found",
            )
        if not selected_info.get("active"):
            raise no_audio_playing_error()
        return selected

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
        raise no_audio_playing_error()

    raise AppError(
        "Không tìm thấy thiết bị audio để thu âm.",
        status=503,
        code="audio_device_not_found",
    )


def default_source_name():
    listed_default = run_text(["pactl", "get-default-source"])
    if listed_default.returncode != 0:
        return ""
    return listed_default.stdout.strip()


def detect_microphone(selected_device=""):
    selected = selected_device.strip()
    devices = list_microphone_devices()

    if selected:
        selected_info = next((device for device in devices if device["id"] == selected), None)
        if not selected_info:
            raise AppError(
                "Microphone đã chọn không còn khả dụng. Chọn Auto hoặc tải lại danh sách.",
                status=404,
                code="microphone_not_found",
            )
        return selected

    forced = os.environ.get("MUSIC_SEARCH_MICROPHONE", "").strip()
    if forced:
        return forced

    running = next((device for device in devices if device.get("active")), None)
    if running:
        return running["id"]

    default_source = default_source_name()
    if default_source:
        default_device = next((device for device in devices if device["id"] == default_source), None)
        if default_device:
            return default_source

    if devices:
        return devices[0]["id"]

    raise microphone_not_found_error()


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


def pcm_has_signal(pcm):
    sample_width = BITS // 8
    if len(pcm) < sample_width:
        return False

    # PCM is s32le; sampling every ~20ms is enough to reject digital silence.
    samples_per_probe = max(1, RATE // 50)
    byte_step = samples_per_probe * CHANNELS * sample_width
    for offset in range(0, len(pcm) - sample_width + 1, byte_step):
        sample = int.from_bytes(pcm[offset:offset + sample_width], byteorder="little", signed=True)
        if abs(sample) > PCM_SIGNAL_THRESHOLD:
            return True
    return False


def decode_audio_file(audio_bytes, seconds, start_seconds=0):
    started = time.monotonic()
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
    timing_log(
        "upload.ffmpeg.decode.done",
        started,
        seconds=seconds,
        start=start_seconds,
        input_bytes=len(audio_bytes),
        output_bytes=len(proc.stdout),
        returncode=proc.returncode,
    )
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
    started = time.monotonic()
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
    timing_log("vibra.recognize.done", started, seconds=seconds, bytes=len(pcm), returncode=proc.returncode)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err or "vibra failed")

    return parse_vibra_output(proc.stdout)


def parse_vibra_output(raw):
    raw = raw.decode("utf-8", errors="replace").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"vibra returned invalid JSON: {exc}") from exc


def terminate_process(proc):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def recognize_stream_attempts_from_device(device, marks, silence_error=None, log_prefix="system"):
    if silence_error is None:
        silence_error = no_audio_playing_error

    marks = tuple(sorted(set(marks)))
    if not marks:
        return {}, 0

    started = time.monotonic()
    max_seconds = marks[-1]
    ffmpeg_cmd = [
        executable_path("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "pulse",
        "-fragment_size",
        "4096",
        "-i",
        device,
        "-t",
        str(max_seconds),
        "-ac",
        str(CHANNELS),
        "-ar",
        str(RATE),
        "-f",
        "s32le",
        "-",
    ]
    ffmpeg = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timing_log(f"{log_prefix}.stream.started", started, seconds=max_seconds, device=device)
    condition = threading.Condition()
    pcm_buffer = bytearray()
    state = {
        "done": False,
        "error": None,
        "ffmpeg_stderr": "",
        "ffmpeg_returncode": None,
        "capture_complete": False,
        "signal_checked": False,
    }
    target_bytes = math.ceil(max_seconds * BYTES_PER_SECOND)
    chunk_size = 4096

    def read_stream():
        first_second = bytearray()
        total_bytes = 0
        while True:
            chunk = ffmpeg.stdout.read1(chunk_size)
            if not chunk:
                break

            remaining = target_bytes - total_bytes
            feed_chunk = chunk[:remaining]
            total_bytes += len(feed_chunk)
            with condition:
                pcm_buffer.extend(feed_chunk)
                condition.notify_all()

            if not state["signal_checked"]:
                need = BYTES_PER_SECOND - len(first_second)
                if need > 0:
                    first_second.extend(feed_chunk[:need])
                if len(first_second) >= BYTES_PER_SECOND:
                    state["signal_checked"] = True
                    timing_log(f"{log_prefix}.signal_check.ready", started, seconds=max_seconds)
                    if not pcm_has_signal(first_second):
                        timing_log(f"{log_prefix}.signal_check.silent", started, seconds=max_seconds)
                        with condition:
                            state["error"] = silence_error()
                            condition.notify_all()
                        terminate_process(ffmpeg)
                        return
                    timing_log(f"{log_prefix}.signal_check.ok", started, seconds=max_seconds)

            if total_bytes >= target_bytes:
                state["capture_complete"] = True
                timing_log(f"{log_prefix}.ffmpeg.target_reached", started, seconds=max_seconds, bytes=total_bytes)
                terminate_process(ffmpeg)
                break

        if not state["signal_checked"] and not pcm_has_signal(first_second):
            timing_log(f"{log_prefix}.signal_check.short_or_silent", started, seconds=max_seconds)
            with condition:
                state["error"] = silence_error()
                condition.notify_all()
            return

        timing_log(f"{log_prefix}.ffmpeg.stdout_done", started, seconds=max_seconds, bytes=total_bytes)
        state["ffmpeg_stderr"] = ffmpeg.stderr.read().decode("utf-8", errors="replace").strip()
        state["ffmpeg_returncode"] = ffmpeg.wait()
        timing_log(f"{log_prefix}.ffmpeg.exited", started, seconds=max_seconds, returncode=state["ffmpeg_returncode"])
        with condition:
            state["done"] = True
            condition.notify_all()

    reader = threading.Thread(target=read_stream, daemon=True)
    reader.start()

    try:
        for mark in marks:
            mark_bytes = math.ceil(mark * BYTES_PER_SECOND)
            with condition:
                while len(pcm_buffer) < mark_bytes and not state["done"] and not state["error"]:
                    condition.wait(timeout=0.2)
                if state["error"]:
                    raise state["error"]
                pcm = bytes(pcm_buffer[:mark_bytes])

            if len(pcm) < mark_bytes:
                break

            timing_log(f"{log_prefix}.attempt.buffer_ready", started, seconds=mark, bytes=len(pcm))
            data = recognize_pcm(pcm, mark)
            timing_log(f"{log_prefix}.attempt.done", started, seconds=mark, found=bool(data.get("track")))
            if data.get("track"):
                timing_log(f"{log_prefix}.stream.done", started, seconds=mark, found=True)
                return data, mark

        reader.join(timeout=0.1)
        if state["error"]:
            raise state["error"]
        if state["ffmpeg_returncode"] not in (None, 0) and not state["capture_complete"]:
            raise RuntimeError(state["ffmpeg_stderr"] or "ffmpeg failed")
        timing_log(f"{log_prefix}.stream.done", started, seconds=max_seconds, found=False)
        return {}, max_seconds
    finally:
        terminate_process(ffmpeg)
        reader.join(timeout=1)


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
    with history_lock:
        items = load_history(oldest_first=True)
        items.append(normalize_history_item(item))
        write_history(items)


def load_history(limit=HISTORY_LIMIT, oldest_first=False):
    with history_lock:
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
    with history_lock:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text("", encoding="utf-8")


def delete_history_item(item_id):
    with history_lock:
        items = load_history(oldest_first=True)
        kept = [item for item in items if item.get("id") != item_id]
        write_history(kept)
        return kept


def static_target(path):
    if path == "/":
        path = "/index.html"

    public_root = PUBLIC.resolve()
    target = (public_root / path.lstrip("/")).resolve()
    try:
        target.relative_to(public_root)
    except ValueError:
        return None
    if not target.exists() or not target.is_file():
        return None
    return target


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


def recognize_track(selected_device=""):
    if not recognize_lock.acquire(blocking=False):
        raise AppError(
            "Đang có lượt nhận diện khác chạy. Chờ lượt hiện tại kết thúc rồi thử lại.",
            status=409,
            code="recognition_busy",
        )

    try:
        started = time.time()
        timing_started = time.monotonic()
        timing_log("system.request.started", timing_started, selected=bool(selected_device))
        device = detect_device(selected_device)
        timing_log("system.detect_device.done", timing_started, device=device)

        data, seconds = recognize_stream_attempts_from_device(device, SYSTEM_ATTEMPT_MARKS)
        track = data.get("track") or {}
        result = result_from_track(track, started, seconds, "system")
        if result:
            result["device"] = device
            save_history(result)
            timing_log("system.request.done", timing_started, found=True, seconds=seconds)
            return result

        result = {
            "ok": True,
            "found": False,
            "device": device,
            "elapsed": round(time.time() - started, 2),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        timing_log("system.request.done", timing_started, found=False)
        return result
    finally:
        recognize_lock.release()


def recognize_microphone(selected_device=""):
    if not recognize_lock.acquire(blocking=False):
        raise AppError(
            "Đang có lượt nhận diện khác chạy. Chờ lượt hiện tại kết thúc rồi thử lại.",
            status=409,
            code="recognition_busy",
        )

    try:
        started = time.time()
        timing_started = time.monotonic()
        timing_log("microphone.request.started", timing_started, selected=bool(selected_device))
        device = detect_microphone(selected_device)
        timing_log("microphone.detect_device.done", timing_started, device=device)

        data, seconds = recognize_stream_attempts_from_device(
            device,
            SYSTEM_ATTEMPT_MARKS,
            silence_error=no_microphone_signal_error,
            log_prefix="microphone",
        )
        track = data.get("track") or {}
        result = result_from_track(track, started, seconds, "microphone")
        if result:
            result["device"] = device
            save_history(result)
            timing_log("microphone.request.done", timing_started, found=True, seconds=seconds)
            return result

        result = {
            "ok": True,
            "found": False,
            "source": "microphone",
            "device": device,
            "elapsed": round(time.time() - started, 2),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        timing_log("microphone.request.done", timing_started, found=False)
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
        timing_started = time.monotonic()
        timing_log("upload.request.started", timing_started, filename=filename or "-")
        requested_range = (end_seconds or start_seconds + DEFAULT_UPLOAD_SECONDS) - start_seconds
        requested_seconds = max(MIN_AUDIO_SECONDS, math.ceil(requested_range))
        pcm = decode_audio_file(audio_bytes, requested_seconds, start_seconds)
        if not pcm:
            raise AppError("File không có audio đọc được.", status=415, code="empty_audio")

        final_seconds = max(1, math.ceil(len(pcm) / BYTES_PER_SECOND))
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
            timing_log("upload.request.done", timing_started, found=True, seconds=final_seconds)
            return result

        timing_log("upload.request.done", timing_started, found=False, seconds=final_seconds)
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

        if parsed.path == "/api/devices":
            try:
                self.send_json(200, {"devices": list_system_audio_devices()})
            except Exception as exc:
                self.send_error_json(exc)
            return

        if parsed.path == "/api/microphones":
            try:
                self.send_json(200, {"devices": list_microphone_devices()})
            except Exception as exc:
                self.send_error_json(exc)
            return

        target = static_target(parsed.path)
        if not target:
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
        target = static_target(parsed.path)
        if not target:
            self.send_error(404)
            return

        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/client-heartbeat":
            query = urllib.parse.parse_qs(parsed.query)
            client_id = (query.get("id") or [""])[0]
            mark_client_seen(client_id)
            self.send_json(200, {"ok": True})
            return

        if parsed.path == "/api/client-close":
            query = urllib.parse.parse_qs(parsed.query)
            client_id = (query.get("id") or [""])[0]
            mark_client_closed(client_id)
            self.send_json(200, {"ok": True})
            return

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

        if parsed.path == "/api/recognize-mic":
            query = urllib.parse.parse_qs(parsed.query)
            selected_device = (query.get("device") or [""])[0]
            try:
                self.send_json(200, recognize_microphone(selected_device))
            except Exception as exc:
                self.send_error_json(exc)
            return

        if parsed.path == "/api/recognize":
            query = urllib.parse.parse_qs(parsed.query)
            selected_device = (query.get("device") or [""])[0]
            try:
                self.send_json(200, recognize_track(selected_device))
            except Exception as exc:
                self.send_error_json(exc)
            return

        self.send_error(404)


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
    global http_server

    if not IS_FROZEN and not ALLOW_SOURCE_RUN:
        print(
            "Music Search is intended to run from the packaged Linux artifact.\n"
            "Build it with: bash build_linux/build_linux.sh --clean\n"
            f"Then run: ./build_linux/dist/{ARTIFACT_NAME}",
            file=sys.stderr,
        )
        return 1

    server, port = make_server()
    http_server = server
    if port == 0:
        port = server.server_address[1]
    url = f"http://{HOST}:{port}"
    print(f"Music Search running at {url}")
    if OPEN_BROWSER:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    if AUTO_SHUTDOWN:
        threading.Thread(target=monitor_clients, daemon=True).start()
    server.serve_forever()
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
