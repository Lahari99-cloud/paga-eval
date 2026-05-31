param(
    [string]$Image = "paga-eval:0.4.0",
    [string]$OutputPath = "dist/paga-eval-0.4.0.spdx.json"
)

$ErrorActionPreference = "Stop"

$output = [System.IO.Path]::GetFullPath($OutputPath)
$directory = Split-Path -Parent $output
if ($directory) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

docker sbom $Image --format spdx-json --output $output
if ($LASTEXITCODE -ne 0) {
    throw "docker sbom failed"
}

$document = Get-Content -Raw -LiteralPath $output | ConvertFrom-Json
if ($document.spdxVersion -notlike "SPDX-*") {
    throw "generated SBOM is not an SPDX document"
}

Write-Output "SBOM generated: $output"
