import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "src" / "app.py"
SPEC = importlib.util.spec_from_file_location("music_search_app", APP_PATH)
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class AppTests(unittest.TestCase):
    def test_parse_pactl_devices_and_active_monitor(self):
        sinks = """Sink #1
    State: RUNNING
    Name: alsa_output.pci
    Monitor Source: alsa_output.pci.monitor
"""
        sources = """Source #1
    State: IDLE
    Name: alsa_output.pci.monitor
    Description: Built-in Audio Monitor
Source #2
    State: RUNNING
    Name: alsa_input.usb
    Description: USB Microphone
"""

        def fake_run_text(args):
            if args == ["pactl", "list", "sources"]:
                return Completed(sources)
            if args == ["pactl", "list", "sinks"]:
                return Completed(sinks)
            raise AssertionError(args)

        with mock.patch.object(app, "run_text", side_effect=fake_run_text):
            monitors = app.list_linux_audio_devices("monitor")
            microphones = app.list_linux_audio_devices("input")

        self.assertEqual(monitors[0]["id"], "alsa_output.pci.monitor")
        self.assertTrue(monitors[0]["active"])
        self.assertEqual(microphones[0]["id"], "alsa_input.usb")
        self.assertTrue(microphones[0]["active"])

    def test_app_state_dir_platforms_and_override(self):
        with mock.patch.dict(os.environ, {"MUSIC_SEARCH_STATE_DIR": "/tmp/music-state"}, clear=True):
            self.assertEqual(app.app_state_dir("linux"), Path("/tmp/music-state"))

        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/tmp/xdg-state"}, clear=True):
            self.assertEqual(app.app_state_dir("linux"), Path("/tmp/xdg-state/music-search"))

        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/Test/AppData/Local"}, clear=True):
            self.assertEqual(
                app.app_state_dir("win32"),
                Path("C:/Users/Test/AppData/Local") / "MusicSearch",
            )

    def test_float_audio_to_s32le_mixes_channels_and_clips(self):
        pcm = app.float_audio_to_s32le([(1.0, -1.0), (0.5, 0.5), (-2.0, 2.0)])
        samples = [
            int.from_bytes(pcm[offset:offset + 4], "little", signed=True)
            for offset in range(0, len(pcm), 4)
        ]
        self.assertEqual(samples[0], 0)
        self.assertEqual(samples[1], int(0.5 * 2147483647))
        self.assertEqual(samples[2], 0)

    def test_pcm_signal_detection(self):
        silent = (0).to_bytes(4, "little", signed=True)
        loud = (app.PCM_SIGNAL_THRESHOLD + 1).to_bytes(4, "little", signed=True)
        self.assertFalse(app.pcm_has_signal(silent))
        self.assertTrue(app.pcm_has_signal(loud))

    def test_history_roundtrip_respects_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(app, "STATE_DIR", Path(tmp)), mock.patch.object(
                app, "HISTORY_FILE", Path(tmp) / "history.jsonl"
            ):
                for index in range(app.HISTORY_LIMIT + 2):
                    app.save_history(
                        {
                            "title": f"Song {index}",
                            "artist": "Artist",
                            "href": "",
                            "created_at": str(index),
                        }
                    )

                items = app.load_history()
                self.assertEqual(len(items), app.HISTORY_LIMIT)
                self.assertEqual(items[0]["title"], f"Song {app.HISTORY_LIMIT + 1}")

                raw_lines = (Path(tmp) / "history.jsonl").read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(raw_lines), app.HISTORY_LIMIT)
                self.assertEqual(json.loads(raw_lines[-1])["title"], f"Song {app.HISTORY_LIMIT + 1}")


if __name__ == "__main__":
    unittest.main()
