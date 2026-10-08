import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import queue
import tkinter as tk
from tkinter import ttk, messagebox

from .controller import Controller, State
from .settings import Settings, Hotkey
from .win32 import Backend, Hotkeys, SingleInstance, list_windows, shell

class App:
    def __init__(self, root, settings=None):
        self.root = root
        self.settings = settings or Settings().load()
        self.controller = Controller(Backend())
        self.hotkeys = Hotkeys(self.settings.toggle, self.settings.stop)
        self.windows, self.closed = [], False
        self.notice = self.settings.warning
        root.title("AutoShift · 每秒点击 Shift")
        root.geometry("490x430")
        root.minsize(460, 430)
        root.attributes("-topmost", self.settings.topmost)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self.callback_error

        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="AutoShift", font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w")
        admin = "管理员权限" if shell.IsUserAnAdmin() else "普通权限（高权限目标可能不接收输入）"
        ttk.Label(frame, text=admin).pack(anchor="w", pady=(0, 10))
        ttk.Label(frame, text="目标窗口").pack(anchor="w")
        line = ttk.Frame(frame)
        line.pack(fill="x", pady=(4, 12))
        self.target_box = ttk.Combobox(line, state="readonly")
        self.target_box.pack(side="left", fill="x", expand=True)
        self.target_box.bind("<<ComboboxSelected>>", self.select_target)
        ttk.Button(line, text="刷新", command=self.refresh_windows).pack(side="right", padx=(8, 0))

        self.state_text, self.detail_text = tk.StringVar(), tk.StringVar()
        self.time_text, self.hotkey_text = tk.StringVar(), tk.StringVar()
        self.state_label = tk.Label(frame, textvariable=self.state_text, anchor="w",
                                    font=("Microsoft YaHei UI", 17, "bold"))
        self.state_label.pack(fill="x")
        ttk.Label(frame, textvariable=self.time_text).pack(anchor="w", pady=(3, 6))
        ttk.Label(frame, textvariable=self.detail_text, wraplength=440).pack(anchor="w", fill="x")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(16, 8))
        self.start_button = ttk.Button(buttons, text="开始（三秒后）", command=self.begin)
        self.start_button.pack(side="left", fill="x", expand=True)
        ttk.Button(buttons, text="停止 / 重试释放", command=self.stop).pack(side="left", padx=(8, 0))

        ttk.Label(frame, textvariable=self.hotkey_text).pack(anchor="w", pady=(2, 8))
        bottom = ttk.Frame(frame)
        bottom.pack(fill="x")
        self.topmost = tk.BooleanVar(value=self.settings.topmost)
        ttk.Checkbutton(bottom, text="窗口置顶", variable=self.topmost, command=self.set_topmost).pack(side="left")
        ttk.Button(bottom, text="热键设置", command=self.edit_hotkeys).pack(side="right")
        ttk.Label(frame, text="切走即停止 · 返回后需重新开启 · 状态仅代表输入发送",
                  wraplength=440).pack(anchor="w", pady=(12, 0))
        self.refresh_windows()
        self.render()
        self.timer = root.after(50, self.tick)

    def refresh_windows(self):
        self.windows = list_windows()
        self.target_box["values"] = [win.label() for win in self.windows]
        selected = self.controller.target
        index = next((i for i, win in enumerate(self.windows)
                      if selected and win.hwnd == selected.hwnd and win.pid == selected.pid), None)
        if index is None and selected is None:
            wanted = self.settings.target_exe.casefold()
            index = next((i for i, win in enumerate(self.windows)
                          if win.executable.casefold() == wanted
                          or os.path.basename(win.executable).casefold() == wanted), None)
            if index is not None:
                self.controller.select(self.windows[index])
        if index is not None:
            self.target_box.current(index)
        else:
            self.target_box.set("目标已关闭，请重新选择" if selected else "请选择目标窗口")

    def select_target(self, _=None):
        index = self.target_box.current()
        if not 0 <= index < len(self.windows):
            return
        target = self.windows[index]
        if self.controller.select(target):
            self.settings.target_exe = target.executable or ""
            self.notice = ""
            self.persist()
        self.render()

    def persist(self):
        try:
            self.settings.save()
        except OSError as exc:
            self.notice = "设置未保存：" + str(exc)
            logging.exception("Settings save failed")

    def set_topmost(self):
        self.settings.topmost = self.topmost.get()
        self.root.attributes("-topmost", self.settings.topmost)
        self.persist()
        self.render()

    def begin(self):
        self.notice = ""
        self.controller.countdown()
        self.render()

    def stop(self):
        self.notice = ""
        self.controller.stop()
        self.render()

    def render(self):
        ctrl = self.controller
        text = ctrl.state.value
        if ctrl.state is State.COUNTDOWN:
            text += f" · {max(0, math.ceil(ctrl.deadline - ctrl.clock()))} 秒"
        self.state_text.set(text)
        colors = {State.RUNNING: "#16713f", State.ERROR: "#b02a2a", State.UNCONFIRMED: "#b02a2a",
                  State.COUNTDOWN: "#9a6500"}
        self.state_label.configure(fg=colors.get(ctrl.state, "#394555"))
        self.detail_text.set(self.notice or ctrl.message)
        elapsed = int(ctrl.elapsed())
        self.time_text.set(f"运行时间  {elapsed // 3600:02d}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}")
        self.hotkey_text.set(f"开启 / 关闭：{self.settings.toggle.label()}    停止：{self.settings.stop.label()}")
        self.start_button["state"] = "disabled" if ctrl.is_running or ctrl.owns_shift or ctrl.state is State.COUNTDOWN else "normal"


    def tick(self):
        if self.closed:
            return
        try:
            self.controller.tick()
            while True:
                try:
                    action, reason = self.hotkeys.events.get_nowait()
                except queue.Empty:
                    break
                if action == "toggle":
                    self.notice = ""
                    self.controller.toggle()
                elif action == "stop":
                    self.stop()
                elif action == "error":
                    self.controller.stop("热键不可用")
                    self.notice = reason
                    logging.error("Hotkey registration or thread failure: %s", reason)
            self.render()
        except Exception as exc:
            self.controller.stop("运行异常：" + str(exc))
            self.notice = ""
            logging.exception("Runtime tick failed")
            self.render()
        finally:
            if not self.closed:
                self.timer = self.root.after(50, self.tick)

    def edit_hotkeys(self):
        if not self.controller.stop("已停止：正在设置热键"):
            self.render()
            return
        self.render()
        dialog = tk.Toplevel(self.root)
        dialog.title("热键设置")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.attributes("-topmost", self.settings.topmost)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        rows = []
        for number, (label, binding) in enumerate((("开启 / 关闭", self.settings.toggle), ("停止", self.settings.stop))):
            ttk.Label(frame, text=label).grid(row=number, column=0, sticky="w", padx=(0, 12), pady=8)
            key = tk.StringVar(value=f"F{binding.key}")
            ctrl, alt = tk.BooleanVar(value=binding.ctrl), tk.BooleanVar(value=binding.alt)
            ttk.Combobox(frame, textvariable=key, values=[f"F{i}" for i in range(1, 12)],
                         width=5, state="readonly").grid(row=number, column=1)
            ttk.Checkbutton(frame, text="Ctrl", variable=ctrl).grid(row=number, column=2, padx=8)
            ttk.Checkbutton(frame, text="Alt", variable=alt).grid(row=number, column=3)
            rows.append((key, ctrl, alt))
        error = tk.StringVar()
        ttk.Label(frame, textvariable=error, foreground="#b02a2a", wraplength=330).grid(
            row=2, column=0, columnspan=4, sticky="w", pady=8)
        ttk.Label(frame, text="支持 F1–F11；无需额外按 Shift").grid(row=3, column=0, columnspan=4, sticky="w")
        def apply():
            toggle, stop = [Hotkey(int(key.get()[1:]), ctrl.get(), alt.get()) for key, ctrl, alt in rows]
            ok, reason = self.hotkeys.update(toggle, stop)
            if not ok:
                error.set(reason)
                return
            self.settings.toggle, self.settings.stop = toggle, stop
            self.persist()
            self.render()
            dialog.destroy()
        ttk.Button(frame, text="保存", command=apply).grid(row=4, column=2, columnspan=2, sticky="e", pady=(12, 0))
        dialog.grab_set()

    def callback_error(self, kind, value, trace):
        logging.error("UI callback failed", exc_info=(kind, value, trace))
        self.controller.stop("界面异常：" + str(value))
        self.notice = ""
        self.render()

    def close(self):
        if not self.controller.stop("已停止：程序关闭"):
            self.notice = ""
            self.render()
            return  # Leave the retry control available if release wasn't confirmed.
        self.closed = True
        self.root.after_cancel(self.timer)
        self.hotkeys.close()
        self.root.destroy()

def main():
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    instance = SingleInstance()
    if instance.already_running:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("AutoShift", "AutoShift 已在运行，请查看已打开的窗口。", parent=root)
        root.destroy()
        instance.close()
        return
    settings = Settings().load()
    try:
        settings.directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(settings.directory / "autoshift.log", maxBytes=262144,
                                      backupCount=1, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        logging.basicConfig(level=logging.CRITICAL)
    app = None
    try:
        root = tk.Tk()
        app = App(root, settings)
        root.mainloop()
    except Exception:
        logging.exception("Application failure")
        if app:
            app.controller.stop("程序异常退出")
        raise
    finally:
        if app:
            app.controller.stop("程序退出")
            app.hotkeys.close()
        instance.close()
