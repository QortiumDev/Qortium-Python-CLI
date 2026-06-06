Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $rootDir

$paths = @(
  "endpoint.py",
  "config.py",
  "chat_settings.json",
  ".qortium-cli-data",
  "dist\.qortium-cli-data"
)

foreach ($path in $paths) {
  if (Test-Path -LiteralPath $path) {
    Remove-Item -LiteralPath $path -Recurse -Force
  }
}

Write-Host "Removed local runtime files and folders."
