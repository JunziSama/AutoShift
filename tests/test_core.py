import ctypes
import json
from pathlib import Path
import tempfile
import unittest

from autoshift.controller import Controller, State
from autoshift.settings import Settings, Hotkey
from autoshift.win32 import INPUT, KEYBDINPUT

class Fake:
    def __init__(self):
        self.foreground = True
        self.down = self.fail_press = self.fail_release = False
        self.events = []
    def is_target_foreground(self, _):
        return self.foreground
    def shift_is_down(self):
        return self.down
    def press_shift(self):
        self.events.append("down")
        if self.fail_press:
            raise OSError("press denied")
        self.down = True
    def release_shift(self):
        self.events.append("up")
        if self.fail_release:
            raise OSError("release denied")
        self.down = False

class InputTests(unittest.TestCase):
    def setUp(self):
        self.backend = Fake()
        self.now = 0
        self.controller = Controller(self.backend, lambda: self.now)
        self.controller.select(object())
    def tick(self, now):
        self.now = now
        self.controller.tick()

    def test_immediate_click_fifty_ms_release_one_second_interval(self):
        self.assertTrue(self.controller.start())
        self.assertEqual(self.backend.events, ["down"])
        self.tick(.049)
        self.assertTrue(self.controller.owns_shift)
        self.tick(.05)
        self.assertFalse(self.controller.owns_shift)
        self.assertTrue(self.controller.is_running)
        self.tick(.999)
        self.assertEqual(self.backend.events, ["down", "up"])
        self.tick(1)
        self.assertEqual(self.backend.events, ["down", "up", "down"])
        self.tick(1.05)
        self.assertEqual(self.backend.events, ["down", "up", "down", "up"])

    def test_stop_during_pulse_releases_once(self):
        self.controller.start()
        self.controller.stop()
        self.controller.stop()
        self.tick(5)
        self.assertEqual(self.backend.events, ["down", "up"])
        self.assertFalse(self.controller.is_running)

    def test_toggle_during_gap_stops_without_extra_keyup(self):
        self.controller.start()
        self.tick(.05)
        self.controller.toggle()
        self.tick(5)
        self.assertEqual(self.backend.events, ["down", "up"])
        self.assertEqual(self.controller.state, State.IDLE)

    def test_focus_loss_during_pulse_and_gap(self):
        for gap in (False, True):
            with self.subTest(gap=gap):
                self.setUp()
                self.controller.start()
                if gap:
                    self.tick(.05)
                self.backend.foreground = False
                self.tick(.1)
                self.backend.foreground = True
                self.tick(2)
                self.assertEqual(self.backend.events, ["down", "up"])
                self.assertFalse(self.controller.is_running)

    def test_background_start_rejected(self):
        self.backend.foreground = False
        self.assertFalse(self.controller.start())
        self.assertEqual(self.backend.events, [])

    def test_countdown_checks_focus_at_deadline(self):
        self.controller.countdown()
        self.tick(2.9)
        self.assertEqual(self.backend.events, [])
        self.backend.foreground = False
        self.tick(3)
        self.assertEqual(self.controller.state, State.IDLE)

    def test_countdown_start_and_cancel(self):
        self.controller.countdown()
        self.tick(3)
        self.assertTrue(self.controller.is_running)
        self.assertTrue(self.controller.owns_shift)
        self.controller.stop()
        self.controller.countdown()
        self.controller.stop()
        self.tick(7)
        self.assertEqual(self.backend.events, ["down", "up"])

    def test_physical_shift_is_not_taken_over(self):
        self.backend.down = True
        self.assertFalse(self.controller.start())
        self.controller.stop()
        self.assertEqual(self.backend.events, [])

    def test_physical_shift_before_next_click_stops_without_releasing_it(self):
        self.controller.start()
        self.tick(.05)
        self.backend.down = True
        self.tick(1)
        self.assertFalse(self.controller.is_running)
        self.assertTrue(self.backend.down)
        self.assertEqual(self.backend.events, ["down", "up"])

    def test_release_failure_retains_ownership_and_cancels_clicks(self):
        self.controller.start()
        self.backend.fail_release = True
        self.tick(.05)
        self.assertEqual(self.controller.state, State.UNCONFIRMED)
        self.assertTrue(self.controller.owns_shift)
        self.assertIsNone(self.controller.next_click_at)
        self.tick(5)
        self.assertEqual(self.backend.events, ["down", "up"])
        self.assertFalse(self.controller.start())
        self.assertFalse(self.controller.select(object()))
        self.backend.fail_release = False
        self.assertTrue(self.controller.stop())
        self.assertFalse(self.controller.owns_shift)

    def test_press_failure_attempts_cleanup(self):
        self.backend.fail_press = True
        self.assertFalse(self.controller.start())
        self.assertEqual(self.backend.events, ["down", "up"])
        self.assertEqual(self.controller.state, State.ERROR)

    def test_later_press_failure_cancels_cycle(self):
        self.controller.start()
        self.tick(.05)
        self.backend.fail_press = True
        self.tick(1)
        self.tick(5)
        self.assertEqual(self.backend.events, ["down", "up", "down", "up"])
        self.assertFalse(self.controller.is_running)

    def test_target_change_releases_before_reselection(self):
        self.controller.start()
        target = object()
        self.assertTrue(self.controller.select(target))
        self.assertIs(self.controller.target, target)
        self.assertEqual(self.backend.events, ["down", "up"])

    def test_late_tick_during_gap_does_not_catch_up(self):
        self.controller.start()
        self.tick(.05)
        self.tick(5)
        self.assertEqual(self.backend.events, ["down", "up", "down"])
        self.tick(5.05)
        self.assertEqual(self.backend.events, ["down", "up", "down", "up"])
        self.assertEqual(self.controller.next_click_at, 6)

    def test_late_release_does_not_create_up_down_burst(self):
        self.controller.start()
        self.tick(5)
        self.assertEqual(self.backend.events, ["down", "up"])
        self.assertEqual(self.controller.next_click_at, 6)
        self.tick(6)
        self.assertEqual(self.backend.events, ["down", "up", "down"])

    def test_cannot_restart_while_running_between_clicks(self):
        self.controller.start()
        self.tick(.05)
        self.assertFalse(self.controller.start())
        self.assertFalse(self.controller.countdown())
        self.assertEqual(self.backend.events, ["down", "up"])

    def test_elapsed_spans_the_click_gaps(self):
        self.controller.start()
        self.tick(.05)
        self.now = 12
        self.assertEqual(self.controller.elapsed(), 12)
        self.controller.stop()
        self.assertEqual(self.controller.elapsed(), 0)


class SettingsTests(unittest.TestCase):
    def test_roundtrip_without_runtime_state(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(directory)
            settings.toggle = Hotkey(7, True, True)
            settings.topmost = False
            settings.target_exe = "C:/example/test.exe"
            settings.save()
            recovered = Settings(directory).load()
            self.assertEqual(recovered.toggle, settings.toggle)
            self.assertFalse(recovered.topmost)
            self.assertEqual(recovered.target_exe, settings.target_exe)
            self.assertNotIn("holding", json.loads(settings.path.read_text(encoding="utf-8")))

    def test_corrupt_and_invalid_settings_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for content in ("{", "[]", '{"version":9}', '{"version":1,"toggle":{"key":12}}'):
                path.write_text(content)
                recovered = Settings(directory).load()
                self.assertTrue(recovered.warning)
                self.assertEqual(recovered.toggle, Hotkey(8))
                self.assertTrue(recovered.topmost)

    def test_hotkey_validation(self):
        for value in (None, {"key": True}, {"key": 0}, {"key": 12}, {"key": 8, "ctrl": 1}):
            with self.assertRaises(ValueError):
                Hotkey.parse(value)

    def test_duplicate_bindings_rejected_on_load(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(directory)
            settings.save()
            value = json.loads(settings.path.read_text(encoding="utf-8"))
            value["stop"] = value["toggle"]
            settings.path.write_text(json.dumps(value))
            self.assertTrue(Settings(directory).load().warning)

class LayoutTests(unittest.TestCase):
    def test_native_input_structure_layout(self):
        self.assertEqual(ctypes.sizeof(KEYBDINPUT), 24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

if __name__ == "__main__":
    unittest.main()
