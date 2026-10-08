import os
from pathlib import Path
import sys

__version__ = "1.1.0"

# Some bundled interpreters need explicit script locations. Frozen builds use
# PyInstaller's runtime hook instead; no global environment is modified.
if not getattr(sys, "frozen", False):
    for base in (Path(__file__).resolve().parents[1] / ".runtime" / "tcl",
                 Path(sys.base_prefix) / "tcl"):
        if (base / "tcl8.6" / "init.tcl").is_file() and (base / "tk8.6" / "tk.tcl").is_file():
            os.environ.setdefault("TCL_LIBRARY", str(base / "tcl8.6"))
            os.environ.setdefault("TK_LIBRARY", str(base / "tk8.6"))
            break
