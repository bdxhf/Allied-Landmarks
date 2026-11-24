# Rebuild from the pack list written by the last game launch.
param([string]$GameDirectory = $env:WH3_GAME_DIR)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'allied_landmarks.pack'
if (-not $GameDirectory) {
    $GameDirectory = Join-Path $PSScriptRoot '..\..\common\Total War WARHAMMER III'
}
$GameDirectory = (Resolve-Path -LiteralPath $GameDirectory).Path
$env:WH3_GAME_DIR = $GameDirectory
$data = Join-Path $GameDirectory 'data'
$installed = Join-Path $data 'allied_landmarks.pack'
$previous = (Get-FileHash -LiteralPath $source).Hash
if ((Test-Path -LiteralPath $installed) -and (Get-FileHash -LiteralPath $installed).Hash -ne $previous) {
    throw 'Installed pack differs from the workspace copy. Check your local edits before replacing it.'
}
$env:PYTHONDONTWRITEBYTECODE = '1'
python (Join-Path $PSScriptRoot 'tools\wh3_build_alm.py')
if ($LASTEXITCODE -ne 0) { throw 'Build failed. The installed pack was preserved.' }
$stage = Join-Path $data ('allied_landmarks.' + [guid]::NewGuid() + '.tmp')
try {
    [IO.File]::Copy($source, $stage)
    if ([IO.File]::Exists($installed)) {
        [IO.File]::Replace($stage, $installed, [NullString]::Value)
    } else {
        [IO.File]::Move($stage, $installed)
    }
} finally {
    if ([IO.File]::Exists($stage)) { [IO.File]::Delete($stage) }
}
Write-Host "Updated $installed"
