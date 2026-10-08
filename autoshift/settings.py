import json
import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Hotkey:
    key: int
    ctrl: bool = False
    alt: bool = False

    def label(self):
        return ("Ctrl+" if self.ctrl else "") + ("Alt+" if self.alt else "") + f"F{self.key}"

    def to_dict(self):
        return {"key": self.key, "ctrl": self.ctrl, "alt": self.alt}

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict):
            raise ValueError("热键设置格式错误")
        key = value.get("key")
        ctrl, alt = value.get("ctrl", False), value.get("alt", False)
        if type(key) is not int or not 1 <= key <= 11:
            raise ValueError("热键仅支持 F1–F11")
        if type(ctrl) is not bool or type(alt) is not bool:
            raise ValueError("热键修饰键格式错误")
        return cls(key, ctrl, alt)

class Settings:
    def __init__(self, directory=None):
        base = directory or os.environ.get("AUTOSHIFT_DATA_DIR")
        if not base:
            base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AutoShift"
        self.directory = Path(base)
        self.path = self.directory / "settings.json"
        self.topmost = True
        self.target_exe = "Overwatch.exe"
        self.toggle, self.stop = Hotkey(8), Hotkey(9)
        self.warning = ""

    def load(self):
        if not self.path.exists():
            return self
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1:
                raise ValueError("配置版本不支持")
            toggle, stop = Hotkey.parse(value["toggle"]), Hotkey.parse(value["stop"])
            if toggle == stop:
                raise ValueError("开启和停止热键不能相同")
            if type(value["topmost"]) is not bool or not isinstance(value["target_exe"], str):
                raise ValueError("配置字段格式错误")
            self.topmost, self.target_exe = value["topmost"], value["target_exe"]
            self.toggle, self.stop = toggle, stop
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.warning = "配置读取失败，使用默认设置：" + str(exc)
        return self

    def save(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "topmost": self.topmost, "target_exe": self.target_exe,
                   "toggle": self.toggle.to_dict(), "stop": self.stop.to_dict()}
        pending = self.path.with_suffix(".tmp")
        pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(pending, self.path)
