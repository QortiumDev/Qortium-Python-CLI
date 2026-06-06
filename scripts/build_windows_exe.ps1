param(
  [switch]$InstallDeps
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $rootDir

if ($InstallDeps) {
  python -m pip install --upgrade pip
  python -m pip install ".[build]"
}

$null = Get-Command pyinstaller -ErrorAction Stop

pyinstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name qortium-cli `
  main.py

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $rootDir\dist\qortium-cli.exe"
