$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Windows executable builds must run on Windows.'
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
}

Push-Location $PSScriptRoot
try {
    uv sync --locked --all-groups
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    uv run --locked ruff check src tests
    if ($LASTEXITCODE -ne 0) { throw 'Code checks failed.' }
    uv run --locked pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    uv run --locked --group build pyinstaller --clean --noconfirm Powerlog.spec
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
    Write-Host 'Ready: dist\Powerlog\Powerlog.exe (keep the entire Powerlog folder).'
}
finally {
    Pop-Location
}
