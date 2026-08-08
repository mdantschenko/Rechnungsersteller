# Copies the application to the server from Windows.
#
#   .\deploy\upload.ps1 -Server root@203.0.113.10
#
# Only the code travels. The database, the generated PDFs and the virtual
# environment stay where they are on either side.

param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$Target = "/opt/invoicing"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$staging = Join-Path ([System.IO.Path]::GetTempPath()) "invoicing-upload"

if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null

$carry = @("src", "migrations", "deploy", "main.py", "pyproject.toml", "uv.lock", "alembic.ini")
foreach ($item in $carry) {
    Copy-Item (Join-Path $root $item) -Destination $staging -Recurse -Force
}
Get-ChildItem $staging -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Write-Host "Uploading to ${Server}:${Target}"
ssh $Server "mkdir -p $Target"
scp -r "$staging/*" "${Server}:${Target}/"
ssh $Server "chmod -R a+rX $Target"
Remove-Item $staging -Recurse -Force

Write-Host ""
Write-Host "Now on the server:"
Write-Host "  cd $Target && INVOICING_DOMAIN=rechnungen.deine-domain.de bash deploy/install.sh"
