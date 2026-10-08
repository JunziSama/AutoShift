"""Exercise our own desktop windows and actual Win32 key/registration APIs."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import time
import tkinter as tk

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from autoshift.app import App
from autoshift.controller import State
from autoshift.settings import Hotkey, Settings
from autoshift.win32 import Window, Hotkeys, SingleInstance, Backend, send_key, user, pid_for, executable_for
user.PostMessageW.argtypes, user.PostMessageW.restype = [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL

DATA = BASE / ".test-data"
DATA.mkdir(exist_ok=True)
os.environ["AUTOSHIFT_DATA_DIR"] = str(DATA / "source")
results = []
def check(condition, label):
    if not condition:
        raise AssertionError(label)
    results.append(label)
    print("PASS:", label, flush=True)

def capture(hwnd, filename):
    """Capture only the application window, without reading other desktop content."""
    from PIL import Image
    gdi = c.WinDLL("gdi32", use_last_error=True)
    class RECT(c.Structure):
        _fields_ = [("left", w.LONG), ("top", w.LONG), ("right", w.LONG), ("bottom", w.LONG)]
    class HEADER(c.Structure):
        _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
                    ("planes", w.WORD), ("bits", w.WORD), ("compression", w.DWORD),
                    ("image_size", w.DWORD), ("x", w.LONG), ("y", w.LONG),
                    ("used", w.DWORD), ("important", w.DWORD)]
    class INFO(c.Structure):
        _fields_ = [("header", HEADER), ("colors", w.DWORD * 3)]
    user.GetWindowRect.argtypes = [w.HWND, c.POINTER(RECT)]
    user.GetWindowDC.argtypes, user.GetWindowDC.restype = [w.HWND], w.HDC
    user.ReleaseDC.argtypes = [w.HWND, w.HDC]
    user.PrintWindow.argtypes, user.PrintWindow.restype = [w.HWND, w.HDC, w.UINT], w.BOOL
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [w.HDC], w.HDC
    gdi.CreateCompatibleBitmap.argtypes, gdi.CreateCompatibleBitmap.restype = [w.HDC, c.c_int, c.c_int], w.HBITMAP
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [w.HDC, w.HANDLE], w.HANDLE
    gdi.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, c.c_void_p, c.POINTER(INFO), w.UINT]
    gdi.DeleteObject.argtypes = [w.HANDLE]
    gdi.DeleteDC.argtypes = [w.HDC]
    rect = RECT()
    user.GetWindowRect(hwnd, c.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    dc = user.GetWindowDC(hwnd)
    memory = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    previous = gdi.SelectObject(memory, bitmap)
    try:
        if not user.PrintWindow(hwnd, memory, 2):
            raise OSError("PrintWindow failed")
        gdi.SelectObject(memory, previous)
        info = INFO(HEADER(c.sizeof(HEADER), width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0))
        pixels = c.create_string_buffer(width * height * 4)
        if gdi.GetDIBits(memory, bitmap, 0, height, pixels, c.byref(info), 0) != height:
            raise OSError("GetDIBits failed")
        Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX").save(filename)
    finally:
        gdi.SelectObject(memory, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, dc)

if __name__ == "__main__":
    record = DATA / "target.json"
    eventfile = record.with_suffix(".events.jsonl")
    for file in (record, eventfile):
        if file.exists():
            file.unlink()
    target = subprocess.Popen([sys.executable, str(BASE / "tests/native_target.py"), str(record)])
    app = root = None
    hwnd = None
    try:
        limit = time.monotonic() + 10
        while not record.exists() and time.monotonic() < limit:
            time.sleep(.05)
        check(record.exists(), "separate-process target created")
        hwnd = json.loads(record.read_text())["hwnd"]
        root = tk.Tk()
        root.geometry("+100+100")
        app = App(root, Settings(DATA / "source").load())
        root.update()
        check(not app.hotkeys.error, "default hotkeys registered")
        window = Window(hwnd, pid_for(hwnd), executable_for(pid_for(hwnd)), "test target")
        app.controller.select(window)
        app.refresh_windows()
        own = user.GetAncestor(root.winfo_id(), 2)

        def pump(duration=.25):
            end = time.monotonic() + duration
            while time.monotonic() < end:
                root.update()
                time.sleep(.005)
        def focus(handle):
            user.SetForegroundWindow(handle)
            pump(.1)
            check(user.GetForegroundWindow() == handle, "own test foreground established")
        def tap(vk):
            send_key(vk=vk)
            pump(.08)
            send_key(vk=vk, up=True)
            pump(.12)
        def shift_events():
            return [e for e in map(json.loads, eventfile.read_text().splitlines()) if e["key"] == "Shift_L"]

        focus(hwnd)
        check(not Backend().shift_is_down(), "Shift initially released")
        tap(0x77)
        check(app.controller.is_running and not app.controller.owns_shift, "F8 starts cycle and Shift is released between clicks")
        pump(3.05)
        tap(0x77)
        check(not app.controller.is_running and not Backend().shift_is_down(), "F8 stops cycle during gap")
        pump(.2)
        first = shift_events()
        check(len(first) >= 8 and len(first) % 2 == 0, "at least four complete real clicks")
        check(all(e["kind"] == ("down" if i % 2 == 0 else "up") for i, e in enumerate(first)), "keydown and keyup strictly alternate")
        widths = [first[i+1]["time"] - first[i]["time"] for i in range(0, len(first), 2)]
        intervals = [first[i+2]["time"] - first[i]["time"] for i in range(0, len(first)-2, 2)]
        check(all(.025 <= width <= .20 for width in widths), "native press duration near 50ms")
        check(all(.9 <= gap <= 1.15 for gap in intervals), "native keydown intervals near one second")
        count = len(first)
        pump(1.2)
        check(len(shift_events()) == count, "stopped cycle emits no more clicks")

        for cycle in range(3):
            tap(0x77)
            check(app.controller.is_running, "F8 can restart cycle repeatedly")
            pump(.2)
            tap(0x77)
            check(not app.controller.is_running, "F8 can stop restarted cycle")
            pump(.2)

        app.controller.start()
        tap(0x78)
        check(not app.controller.is_running and not Backend().shift_is_down(), "F9 stops from active pulse")
        app.controller.start()
        pump(.15)
        tap(0x78)
        check(not app.controller.is_running, "F9 stops between clicks")

        for pulse in (True, False):
            focus(hwnd)
            app.controller.start()
            if not pulse:
                pump(.15)
            focus(own)
            check(not app.controller.is_running and not Backend().shift_is_down(), "focus loss stops during pulse or gap")
            count = len(shift_events())
            pump(1.1)
            check(len(shift_events()) == count, "focus loss cancels future clicks")
            focus(hwnd)
            check(not app.controller.is_running, "return does not resume")
        focus(own)
        tap(0x77)
        check(not app.controller.is_running, "background hotkey start rejected")
        app.begin()
        focus(hwnd)
        pump(3.15)
        check(app.controller.is_running, "three-second countdown starts cycle")
        app.stop()
        app.begin()
        app.stop()
        pump(3.15)
        check(not app.controller.is_running, "cancelled countdown remains stopped")

        competitor = Hotkeys(Hotkey(6, True, True), Hotkey(5, True, True))
        check(not competitor.error, "competitor test hotkeys registered")
        ok, reason = app.hotkeys.update(Hotkey(6, True, True), Hotkey(9))
        check(not ok and bool(reason), "hotkey conflict rejected")
        competitor.close()
        focus(hwnd)
        tap(0x77)
        check(app.controller.is_running, "original F8 restored after conflict")
        app.stop()
        check(app.hotkeys.update(Hotkey(7, True), Hotkey(9, True))[0], "custom hotkeys registered")
        send_key(vk=0x11)
        try:
            tap(0x76)
            check(app.controller.is_running, "Ctrl+F7 starts cycle")
            tap(0x78)
            check(not app.controller.is_running, "Ctrl+F9 stops cycle")
        finally:
            send_key(vk=0x11, up=True)
        check(app.hotkeys.update(Hotkey(8), Hotkey(9))[0], "default hotkeys restored")

        app.topmost.set(False)
        app.set_topmost()
        check(not bool(root.attributes("-topmost")), "topmost disabled")
        app.topmost.set(True)
        app.set_topmost()
        check(bool(root.attributes("-topmost")), "topmost enabled")
        first_mutex, second_mutex = SingleInstance(), SingleInstance()
        check(not first_mutex.already_running and second_mutex.already_running, "duplicate mutex rejected")
        second_mutex.close()
        first_mutex.close()
        focus(hwnd)
        tap(0x77)
        try:
            capture(own, DATA / "AutoShift-window.png")
        except ImportError:
            print("Screenshot skipped: Pillow unavailable", flush=True)
        user.PostMessageW(hwnd, 0x0010, 0, 0)
        target.wait(timeout=5)
        pump(.2)
        check(not app.controller.is_running and not Backend().shift_is_down(), "target exit cancels cycle and releases Shift")

        record2 = DATA / "close-target.json"
        if record2.exists():
            record2.unlink()
        target = subprocess.Popen([sys.executable, str(BASE / "tests/native_target.py"), str(record2)])
        limit = time.monotonic() + 10
        while not record2.exists() and time.monotonic() < limit:
            pump(.05)
        check(record2.exists(), "close-test window created")
        hwnd = json.loads(record2.read_text())["hwnd"]
        app.controller.select(Window(hwnd, pid_for(hwnd), executable_for(pid_for(hwnd)), "close target"))
        focus(hwnd)
        check(app.controller.start() and app.controller.owns_shift, "close test begins during pulse")
        app.close()
        app = None
        check(not Backend().shift_is_down(), "normal close during pulse releases Shift")
        (DATA / "native-results.json").write_text(json.dumps(
            {"version": "1.1.0", "passed": results, "press_durations": widths, "keydown_intervals": intervals},
            ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        if app:
            app.stop()
            app.close()
        if hwnd and user.IsWindow(hwnd):
            user.PostMessageW(hwnd, 0x0010, 0, 0)
        if target.poll() is None:
            target.wait(timeout=5)
        for vk in (0x11, 0x77, 0x78):
            send_key(vk=vk, up=True)
        send_key(scan=0x2A, up=True)
