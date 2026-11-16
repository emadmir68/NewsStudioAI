# Rebuild the News Studio AI source archive from the repository payload parts.
$ErrorActionPreference = "Stop"

$partsDir = Join-Path $PSScriptRoot "source_archive_parts"
$parts = Get-ChildItem -Path $partsDir -Filter "part*.b64" -File | Sort-Object Name

if ($parts.Count -ne 9) {
    throw "Expected 9 archive parts; found $($parts.Count). Make sure the repository download is complete."
}

$base64 = (($parts | ForEach-Object { (Get-Content -LiteralPath $_.FullName -Raw).Trim() }) -join "")
if ($base64.Length -ne 35000) {
    throw "Archive payload length check failed. Expected 35000 base64 characters, got $($base64.Length)."
}

$archive = Join-Path $PSScriptRoot "NewsStudioAI_v0.2.0_Windows_Source.tar.xz"
[System.IO.File]::WriteAllBytes($archive, [Convert]::FromBase64String($base64))

Write-Host ""
Write-Host "Source archive created:" -ForegroundColor Green
Write-Host $archive
Write-Host ""
Write-Host "Extract the .tar.xz file with 7-Zip, or run:"
Write-Host "tar -xf `"$archive`" -C `"$PSScriptRoot`""