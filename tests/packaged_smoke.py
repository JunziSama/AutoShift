"""Validate the shipped EXE with Python removed from the child search path."""
import ctypes as c
from ctypes import wintypes as w
import json
import inspect
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tests"))
from autoshift.settings import Settings
from autoshift.win32 import Backend, Window, list_windows, send_key, user, pid_for, executable_for, shell
user.PostMessageW.argtypes, user.PostMessageW.restype = [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL

DATA = BASE / ".test-data" / "packaged"
DATA.mkdir(parents=True, exist_ok=True)
LOG = DATA / "results.json"
EXE = BASE / "dist" / "AutoShift" / "AutoShift.exe"
passed = []
target = app = duplicate = None
hwnd = app_hwnd = None
def check(ok, label):
    if not ok:
        raise AssertionError(label)
    passed.append(label)
    print("PASS:", label, flush=True)
def wait_for(callback, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = callback()
        if value:
            return value
        time.sleep(.03)
    raise AssertionError("Timed out at caller line " + str(inspect.currentframe().f_back.f_lineno) + ": foreground=" + str(user.GetForegroundWindow()) + ", target=" + str(hwnd) + ", app=" + str(app_hwnd) + ", shift=" + str(Backend().shift_is_down()))
def focus(handle):
    if not user.SetForegroundWindow(handle):
        foreground = user.GetForegroundWindow()
        if foreground not in (hwnd, app_hwnd):
            raise AssertionError("Foreground left our test windows; refusing to move another app")
        # Windows foreground-lock rules can reject an automation caller after
        # the EXE injects a pulse. Temporarily share only our test input queue.
        message = w.MSG()
        user.PeekMessageW(c.byref(message), None, 0, 0, 0)
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentThreadId.argtypes, kernel.GetCurrentThreadId.restype = [], w.DWORD
        user.AttachThreadInput.argtypes, user.AttachThreadInput.restype = [w.DWORD, w.DWORD, w.BOOL], w.BOOL
        current = kernel.GetCurrentThreadId()
        other = user.GetWindowThreadProcessId(foreground, None)
        attached = current != other and user.AttachThreadInput(current, other, True)
        try:
            user.SetForegroundWindow(handle)
        finally:
            if attached:
                user.AttachThreadInput(current, other, False)
    wait_for(lambda: user.GetForegroundWindow() == handle, 3)

def tap(vk):
    send_key(vk=vk)
    time.sleep(.1)
    send_key(vk=vk, up=True)
    time.sleep(.15)

try:
    check(bool(shell.IsUserAnAdmin()), "native test process has administrator privileges")
    record = DATA / "target.json"
    if record.exists():
        record.unlink()
    eventfile = record.with_suffix(".events.jsonl")
    if eventfile.exists():
        eventfile.unlink()
    target = subprocess.Popen([sys.executable, str(BASE / "tests/native_target.py"), str(record)])
    wait_for(record.exists)
    hwnd = json.loads(record.read_text())["hwnd"]
    settings = Settings(DATA / "settings")
    settings.target_exe = executable_for(pid_for(hwnd))
    settings.save()
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH"):
        environment.pop(name, None)
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    environment["AUTOSHIFT_DATA_DIR"] = str(settings.directory)
    empty = DATA / "empty-working-directory"
    empty.mkdir(exist_ok=True)
    app = subprocess.Popen([str(EXE)], cwd=empty, env=environment)
    def find_main():
        return next((win for win in list_windows()
                     if win.title == "AutoShift · 每秒点击 Shift"
                     and win.executable.casefold() == str(EXE).casefold()), None)
    window = wait_for(find_main)
    app_hwnd = window.hwnd
    check(app.poll() is None, "portable EXE starts from empty directory without Python on PATH")
    check(not Backend().shift_is_down(), "portable EXE starts with clicking disabled")
    # Capture separately from timing-sensitive input tests.

    # Verify the interpreter actually loaded from the portable bundle.
    kernel = c.WinDLL("kernel32", use_last_error=True)
    psapi = c.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    psapi.EnumProcessModules.argtypes = [w.HANDLE, c.POINTER(w.HMODULE), w.DWORD, c.POINTER(w.DWORD)]
    psapi.GetModuleFileNameExW.argtypes = [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]
    process = kernel.OpenProcess(0x410, False, window.pid)
    check(bool(process), "portable process modules readable")
    try:
        modules = (w.HMODULE * 1024)()
        needed = w.DWORD()
        check(bool(psapi.EnumProcessModules(process, modules, c.sizeof(modules), c.byref(needed))), "portable process module enumeration")
        paths = []
        for module in modules[:needed.value // c.sizeof(w.HMODULE)]:
            path = c.create_unicode_buffer(32768)
            if psapi.GetModuleFileNameExW(process, module, path, len(path)):
                paths.append(path.value)
        expected = str(EXE.parent / "_internal" / "python312.dll").casefold()
        check(expected in [path.casefold() for path in paths], "Python DLL loaded from portable _internal directory")
    finally:
        kernel.CloseHandle(process)

    def eventlog():
        file = record.with_suffix(".events.jsonl")
        return [e for e in map(json.loads, file.read_text().splitlines()) if e["key"] == "Shift_L"]
    focus(hwnd)
    tap(0x77)
    wait_for(lambda: len(eventlog()) >= 2)
    check(not Backend().shift_is_down(), "packaged first click releases Shift before the next second")
    time.sleep(3)
    # Do not send synchronous WM_PRINT during the input timing test.
    tap(0x77)
    time.sleep(.2)
    clicks = eventlog()
    check(len(clicks) >= 8 and len(clicks) % 2 == 0, "packaged cycle generates complete repeated clicks")
    check(all(e["kind"] == ("down" if i % 2 == 0 else "up") for i, e in enumerate(clicks)), "packaged down and up alternate")
    widths = [clicks[i+1]["time"] - clicks[i]["time"] for i in range(0, len(clicks), 2)]
    intervals = [clicks[i+2]["time"] - clicks[i]["time"] for i in range(0, len(clicks)-2, 2)]
    check(all(.025 <= value <= .2 for value in widths), "packaged press duration near 50ms")
    check(all(.9 <= value <= 1.2 for value in intervals), "packaged keydown interval near one second")
    count = len(clicks)
    time.sleep(1.15)
    check(not Backend().shift_is_down() and len(eventlog()) == count, "packaged F8 stops during click gap")
    tap(0x77)
    tap(0x78)
    count = len(eventlog())
    time.sleep(1.15)
    check(not Backend().shift_is_down() and len(eventlog()) == count, "packaged F9 stops cycle during gap")
    tap(0x77)
    wait_for(lambda: Backend().shift_is_down())
    focus(app_hwnd)
    wait_for(lambda: not Backend().shift_is_down())
    check(True, "packaged focus loss releases an active pulse")
    count = len(eventlog())
    time.sleep(1.15)
    check(len(eventlog()) == count, "packaged focus loss cancels future clicks")
    focus(hwnd)
    time.sleep(1.15)
    check(not Backend().shift_is_down() and len(eventlog()) == count, "packaged return to target remains stopped")


    duplicate = subprocess.Popen([str(EXE)], cwd=empty, env=environment)
    def find_dialog():
        return next((win for win in list_windows()
                     if win.pid == duplicate.pid and win.title == "AutoShift"), None)
    dialog = wait_for(find_dialog)
    check(len([win for win in list_windows() if win.title == "AutoShift · 每秒点击 Shift"]) == 1,
          "duplicate EXE shows notice rather than second controller")
    user.PostMessageW(dialog.hwnd, 0x0111, 1, 0)
    duplicate.wait(timeout=8)
    check(duplicate.returncode == 0, "duplicate EXE exits cleanly")

    focus(hwnd)
    tap(0x77)
    wait_for(lambda: Backend().shift_is_down())
    user.PostMessageW(app_hwnd, 0x0010, 0, 0)
    app.wait(timeout=8)
    check(app.returncode == 0 and not Backend().shift_is_down(), "packaged normal close releases pulse and cancels cycle")
    errors = settings.directory / "autoshift.log"
    check(not errors.exists() or not errors.read_text(encoding="utf-8").strip(), "packaged run logged no errors")
    LOG.write_text(json.dumps({"version": "1.1.0", "passed": passed, "press_durations": widths, "keydown_intervals": intervals}, ensure_ascii=False, indent=2), encoding="utf-8")
except Exception as exc:
    LOG.write_text(json.dumps({"passed": passed, "error": str(exc)}, ensure_ascii=False, indent=2), encoding="utf-8")
    raise
finally:
    for handle in (app_hwnd, hwnd):
        if handle and user.IsWindow(handle):
            user.PostMessageW(handle, 0x0010, 0, 0)
    for process in (duplicate, app, target):
        if process and process.poll() is None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
    for vk in (0x77, 0x78):
        try:
            send_key(vk=vk, up=True)
        except OSError:
            pass
    try:
        send_key(scan=0x2A, up=True)
    except OSError:
        pass
