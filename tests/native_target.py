"""A separate-process window created solely for native smoke tests."""
import json
import time
from pathlib import Path
import sys
import tkinter as tk
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoshift.win32 import user
root = tk.Tk()
root.title("AutoShift input test target")
root.geometry("350x180+800+200")
tk.Label(root, text="AutoShift local input test window").pack(pady=25)
record = Path(sys.argv[1])
events = record.with_suffix(".events.jsonl")
def key_event(event, kind):
    with events.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"kind": kind, "key": event.keysym, "time": time.monotonic()}) + "\n")
root.bind("<KeyPress>", lambda e: key_event(e, "down"))
root.bind("<KeyRelease>", lambda e: key_event(e, "up"))
root.update()
hwnd = user.GetAncestor(root.winfo_id(), 2)
record.write_text(json.dumps({"hwnd": hwnd}), encoding="utf-8")
root.after(90000, root.destroy)
root.mainloop()
