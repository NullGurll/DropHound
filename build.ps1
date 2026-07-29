$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher was not found. Install 64-bit Python 3.12 from python.org."
}

if (-not (Test-Path ".venv")) {
    py -3.12 -m venv .venv
}

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements-dev.txt
& $Python -m unittest discover -s tests -v
& $Python -m PyInstaller --noconfirm --clean CyberdropDesk.spec

$Engine = Join-Path $PSScriptRoot "dist\DropHoundEngine.exe"
$AppFolder = Join-Path $PSScriptRoot "dist\DropHound"
if (-not (Test-Path $Engine)) {
    throw "DropHoundEngine.exe was not created."
}
Copy-Item $Engine (Join-Path $AppFolder "DropHoundEngine.exe") -Force

$LicenseFolder = Join-Path $AppFolder "licenses"
New-Item -ItemType Directory -Force $LicenseFolder | Out-Null
Copy-Item "LICENSE" (Join-Path $LicenseFolder "DropHound-GPL-3.0.txt") -Force
Copy-Item "licenses\THIRD-PARTY-NOTICES.txt" $LicenseFolder -Force
Copy-Item "licenses\Cyberdrop-DL-GPL-3.0.txt" $LicenseFolder -Force

$Inno = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $Inno) {
    & $Inno installer.iss
    Write-Host "Installer created in installer-output."
} else {
    Write-Host "Inno Setup 6 not found; portable build is ready in dist\DropHound."
}
