param(
    [string]$Python = "$PSScriptRoot\.venv\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-Location -LiteralPath $PSScriptRoot
$archive = "$PSScriptRoot\dist\AutoShift-1.1.0-win64.zip"
if (Test-Path -LiteralPath $archive) { throw "发布压缩包已存在，请先保留旧版本后重新构建。" }
if (!(Test-Path -LiteralPath $Python)) { throw "请先创建虚拟环境并安装 requirements-build.txt。" }
$env:PYINSTALLER_CONFIG_DIR = "$PSScriptRoot\build\pyinstaller-cache"
if (Test-Path -LiteralPath "$PSScriptRoot\.runtime\tcl\tcl8.6\init.tcl") {
    $env:TCL_LIBRARY = "$PSScriptRoot\.runtime\tcl\tcl8.6"
    $env:TK_LIBRARY = "$PSScriptRoot\.runtime\tcl\tk8.6"
}
& $Python -m PyInstaller --onedir --windowed --uac-admin --noupx --name AutoShift --distpath dist --workpath build --specpath build main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败。" }
Copy-Item -LiteralPath "$PSScriptRoot\README.md" -Destination "$PSScriptRoot\dist\AutoShift\使用说明.md"
Compress-Archive -LiteralPath "$PSScriptRoot\dist\AutoShift" -DestinationPath $archive
Get-FileHash -LiteralPath "$PSScriptRoot\dist\AutoShift\AutoShift.exe", $archive -Algorithm SHA256
