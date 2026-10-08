import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
import pefile

BASE = Path(__file__).resolve().parents[1]
folder = BASE / "dist/AutoShift"
exe = folder / "AutoShift.exe"
archive = BASE / "dist/AutoShift-1.1.0-win64.zip"
pe = pefile.PE(str(exe))
assert pe.FILE_HEADER.Machine == 0x8664, "EXE must target AMD64"
assert pe.OPTIONAL_HEADER.Subsystem == 2, "EXE must be a windowed application"
manifests = []
for resource in pe.DIRECTORY_ENTRY_RESOURCE.entries:
    if resource.id == 24:
        for name in resource.directory.entries:
            for language in name.directory.entries:
                entry = language.data.struct
                manifests.append(pe.get_data(entry.OffsetToData, entry.Size))
levels = []
for manifest in manifests:
    root = ET.fromstring(manifest)
    levels += [item.attrib for item in root.iter() if item.tag.endswith("requestedExecutionLevel")]
assert any(item.get("level") == "requireAdministrator" and item.get("uiAccess") == "false" for item in levels)
for relative in ("_internal/python312.dll", "_internal/_tkinter.pyd",
                 "_internal/_tcl_data/init.tcl", "_internal/_tk_data/tk.tcl"):
    assert (folder / relative).is_file(), relative
local = {file.relative_to(folder).as_posix(): file for file in folder.rglob("*") if file.is_file()}
with zipfile.ZipFile(archive) as packaged:
    included = {info.filename.removeprefix("AutoShift/"): info for info in packaged.infolist() if not info.is_dir()}
    assert set(local) == set(included), "ZIP and portable directory differ"
    for name, file in local.items():
        assert hashlib.sha256(file.read_bytes()).digest() == hashlib.sha256(packaged.read(included[name])).digest(), name
def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()
old = json.loads((BASE / "dist/verification-1.0.0.json").read_text(encoding="utf-8"))
assert digest(BASE / "dist/AutoShift-1.0.0-win64.zip") == old["zip_sha256"], "Original ZIP changed"
assert digest(BASE / "dist/AutoShift-1.0.0/AutoShift.exe") == old["exe_sha256"], "Original EXE changed"
native = json.loads((BASE / ".test-data/native-results.json").read_text(encoding="utf-8"))
packaged = json.loads((BASE / ".test-data/packaged/results.json").read_text(encoding="utf-8"))
assert "error" not in packaged, packaged.get("error")
assert native.get("version") == packaged.get("version") == "1.1.0"
unit = json.loads((BASE / ".test-data/unit-results.json").read_text(encoding="utf-8"))
assert unit["success"] and not unit["failures"] and not unit["errors"]
report = {
    "version": "1.1.0", "unit_tests_passed": unit["tests_run"],
    "native_checks_passed": len(native["passed"]),
    "packaged_checks_passed": len(packaged["passed"]),
    "click_interval_seconds": 1.0, "press_duration_seconds": 0.05,
    "measured_native_intervals": native["keydown_intervals"],
    "measured_packaged_intervals": packaged["keydown_intervals"],
    "amd64": True, "windowed": True, "manifest": levels,
    "previous_1_0_0_preserved": True,
    "zip_matches_portable_directory": True, "portable_file_count": len(local),
    "exe_sha256": digest(exe), "zip_sha256": digest(archive),
    "source_sha256": {file.relative_to(BASE).as_posix(): digest(file)
                      for file in [BASE / "main.py", *sorted((BASE / "autoshift").glob("*.py"))]},
    "game_runtime_verified": False
}
(BASE / "dist/verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
(BASE / "dist/SHA256SUMS.txt").write_text(
    f"{report['zip_sha256']}  {archive.name}\n{report['exe_sha256']}  AutoShift/AutoShift.exe\n",
    encoding="ascii")
print(json.dumps(report, ensure_ascii=False, indent=2))
