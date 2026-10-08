"""Small, explicit Win32 surface. No hooks, drivers, or process injection."""
import ctypes as c
from ctypes import wintypes as w
from dataclasses import dataclass
import os
import queue
import threading
import time

user = c.WinDLL("user32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
shell = c.WinDLL("shell32", use_last_error=True)
ULONG_PTR = c.c_size_t

class KEYBDINPUT(c.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]
class MOUSEINPUT(c.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]
class HARDWAREINPUT(c.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]
class INPUTUNION(c.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]
class INPUT(c.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", w.DWORD), ("value", INPUTUNION)]

ENUMPROC = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
def bind(dll, name, args, result):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn

bind(user, "SendInput", [w.UINT, c.POINTER(INPUT), c.c_int], w.UINT)
bind(user, "GetForegroundWindow", [], w.HWND)
bind(user, "IsWindow", [w.HWND], w.BOOL)
bind(user, "IsWindowVisible", [w.HWND], w.BOOL)
bind(user, "GetWindowTextLengthW", [w.HWND], c.c_int)
bind(user, "GetWindowTextW", [w.HWND, w.LPWSTR, c.c_int], c.c_int)
bind(user, "GetWindowThreadProcessId", [w.HWND, c.POINTER(w.DWORD)], w.DWORD)
bind(user, "EnumWindows", [ENUMPROC, w.LPARAM], w.BOOL)
bind(user, "GetAsyncKeyState", [c.c_int], c.c_short)
bind(user, "RegisterHotKey", [w.HWND, c.c_int, w.UINT, w.UINT], w.BOOL)
bind(user, "UnregisterHotKey", [w.HWND, c.c_int], w.BOOL)
bind(user, "PeekMessageW", [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT], w.BOOL)
bind(user, "SetForegroundWindow", [w.HWND], w.BOOL)
bind(user, "GetAncestor", [w.HWND, w.UINT], w.HWND)
bind(kernel, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
bind(kernel, "QueryFullProcessImageNameW", [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL)
bind(kernel, "CloseHandle", [w.HANDLE], w.BOOL)
bind(kernel, "CreateMutexW", [c.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE)
bind(shell, "IsUserAnAdmin", [], w.BOOL)

def pid_for(hwnd):
    pid = w.DWORD()
    user.GetWindowThreadProcessId(hwnd, c.byref(pid))
    return pid.value

def executable_for(pid):
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf, size = c.create_unicode_buffer(32768), w.DWORD(32768)
        return buf.value if kernel.QueryFullProcessImageNameW(handle, 0, buf, c.byref(size)) else ""
    finally:
        kernel.CloseHandle(handle)

@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    executable: str
    title: str

    def label(self):
        return f"{os.path.basename(self.executable) or '未知程序'} · {self.title[:65]} · PID {self.pid}"

def list_windows():
    found = []
    @ENUMPROC
    def visit(hwnd, _):
        try:
            if not user.IsWindowVisible(hwnd):
                return True
            pid = pid_for(hwnd)
            length = user.GetWindowTextLengthW(hwnd)
            if not length or pid == os.getpid():
                return True
            buf = c.create_unicode_buffer(length + 1)
            user.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value.strip():
                found.append(Window(int(hwnd), pid, executable_for(pid), buf.value))
        except Exception:
            pass  # A window/process can disappear during enumeration.
        return True
    user.EnumWindows(visit, 0)
    return sorted(found, key=lambda win: (os.path.basename(win.executable).lower(), win.title.lower()))

def send_key(vk=0, scan=0, up=False):
    entry = INPUT()
    entry.type = 1
    entry.ki = KEYBDINPUT(vk, scan, (8 if scan else 0) | (2 if up else 0), 0, 0)
    if user.SendInput(1, c.byref(entry), c.sizeof(INPUT)) != 1:
        error = c.get_last_error()
        raise OSError(error, "Windows 未接收输入事件（权限或输入桌面限制）")

class Backend:
    def is_target_foreground(self, target):
        return bool(target and user.IsWindow(target.hwnd)
                    and pid_for(target.hwnd) == target.pid
                    and user.GetForegroundWindow() == target.hwnd)

    def shift_is_down(self):
        return bool(user.GetAsyncKeyState(0x10) & 0x8000)

    def press_shift(self):
        send_key(scan=0x2A)

    def release_shift(self):
        send_key(scan=0x2A, up=True)

class SingleInstance:
    def __init__(self):
        c.set_last_error(0)
        self.handle = kernel.CreateMutexW(None, False, "Local\\AutoShift_v1")
        if not self.handle:
            raise c.WinError(c.get_last_error())
        self.already_running = c.get_last_error() == 183

    def close(self):
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None

class Hotkeys:
    """Registrations and message queue belong to one dedicated OS thread."""
    def __init__(self, toggle, stop):
        self.events, self.commands = queue.Queue(), queue.Queue()
        self.registered, self.bindings = {}, {}
        self.ready = threading.Event()
        self.error = ""
        self.initial = {"toggle": toggle, "stop": stop}
        self.thread = threading.Thread(target=self._run, name="AutoShift-hotkeys", daemon=True)
        self.thread.start()
        if not self.ready.wait(3):
            raise RuntimeError("热键线程启动超时")
        if self.error:
            self.events.put(("error", self.error))

    def _register(self, bindings):
        registered = {}
        try:
            for action, hotkey in bindings.items():
                mods = (2 if hotkey.ctrl else 0) | (1 if hotkey.alt else 0) | 0x4000
                for shift in (0, 4):
                    ident = 0x400 + len(registered)
                    if not user.RegisterHotKey(None, ident, mods | shift, 0x6F + hotkey.key):
                        raise OSError(c.get_last_error(), f"{hotkey.label()} 已被占用，或无法注册")
                    registered[ident] = action
        except Exception:
            for ident in registered:
                user.UnregisterHotKey(None, ident)
            raise
        return registered

    def _unregister(self):
        for ident in self.registered:
            user.UnregisterHotKey(None, ident)
        self.registered = {}

    def _run(self):
        message = w.MSG()
        user.PeekMessageW(c.byref(message), None, 0, 0, 0)
        latched = set()
        try:
            try:
                self.registered = self._register(self.initial)
                self.bindings = self.initial
            except Exception as exc:
                self.error = str(exc)
            self.ready.set()
            running = True
            while running:
                try:
                    command, payload, reply = self.commands.get_nowait()
                except queue.Empty:
                    command = None
                if command == "close":
                    running = False
                    continue
                if command == "update":
                    old = self.bindings.copy()
                    self._unregister()
                    latched.clear()
                    try:
                        self.registered = self._register(payload)
                        self.bindings, self.error = payload, ""
                        reply.put((True, ""))
                    except Exception as exc:
                        reason = str(exc)
                        try:
                            self.registered = self._register(old) if old else {}
                            self.bindings = old
                        except Exception as rollback:
                            self.bindings = {}
                            reason += "；原热键恢复失败：" + str(rollback)
                            self.events.put(("error", reason))
                        reply.put((False, reason))
                for action in list(latched):
                    hotkey = self.bindings.get(action)
                    if not hotkey or not (user.GetAsyncKeyState(0x6F + hotkey.key) & 0x8000):
                        latched.discard(action)
                while user.PeekMessageW(c.byref(message), None, 0, 0, 1):
                    if message.message == 0x0312:
                        action = self.registered.get(message.wParam)
                        if action and action not in latched:
                            latched.add(action)
                            self.events.put((action, ""))
                time.sleep(0.005)
        except Exception as exc:
            self.error = "热键线程异常：" + str(exc)
            self.events.put(("error", self.error))
            self.ready.set()
        finally:
            self._unregister()

    def update(self, toggle, stop):
        if toggle == stop:
            return False, "开启和停止热键不能相同"
        if not self.thread.is_alive():
            return False, "热键线程已停止，请重启程序"
        reply = queue.Queue()
        self.commands.put(("update", {"toggle": toggle, "stop": stop}, reply))
        try:
            return reply.get(timeout=3)
        except queue.Empty:
            return False, "热键设置超时，请重启程序"

    def close(self):
        self.commands.put(("close", None, None))
        self.thread.join(timeout=3)
