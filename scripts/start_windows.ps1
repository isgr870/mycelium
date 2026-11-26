$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (Test-Path ".env") {
  Get-Content ".env" | ForEach-Object {
    if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
      [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
    }
  }
}
if (-not $env:MYCELIUM_SECRET_KEY) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $env:MYCELIUM_SECRET_KEY = -join ($bytes | ForEach-Object { $_.ToString("x2") })
}
if (-not $env:MYCELIUM_HOST) { $env:MYCELIUM_HOST = "127.0.0.1" }
if (-not $env:MYCELIUM_PORT) { $env:MYCELIUM_PORT = "8000" }
python node.py
