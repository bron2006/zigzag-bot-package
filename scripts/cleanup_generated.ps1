param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$prefix = $projectRoot + '\'
$envPath = Join-Path $projectRoot '.venv_test'
$items = @(Get-ChildItem -LiteralPath $projectRoot -Directory -Recurse -Force |
    Where-Object { $_.Name -in @('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache') -and
        -not $_.FullName.StartsWith($envPath + '\', [StringComparison]::OrdinalIgnoreCase) -and
        -not $_.FullName.StartsWith((Join-Path $projectRoot '.git') + '\', [StringComparison]::OrdinalIgnoreCase) })
foreach ($name in @('.venv_test', '.hypothesis')) {
    $candidate = Join-Path $projectRoot $name
    if (Test-Path -LiteralPath $candidate) { $items += Get-Item -LiteralPath $candidate -Force }
}
$processes = @(Get-CimInstance Win32_Process)
$records = foreach ($item in $items) {
    $resolved = [IO.Path]::GetFullPath($item.FullName)
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Outside project: $resolved"
    }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked target: $resolved" }
    $children = @(Get-ChildItem -LiteralPath $resolved -Recurse -Force)
    if ($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
        throw "Linked descendant: $resolved"
    }
    $relative = $resolved.Substring($prefix.Length).Replace('\', '/')
    $tracked = @(git -C $projectRoot ls-files -- $relative)
    if ($LASTEXITCODE -ne 0 -or $tracked.Count) { throw "Tracked or unverified target: $resolved" }
    if ($processes | Where-Object { ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($resolved + '\', [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($resolved, [StringComparison]::OrdinalIgnoreCase) -ge 0) }) {
        throw "Target in use by a process: $resolved"
    }
    $files = @($children | Where-Object { -not $_.PSIsContainer })
    [pscustomobject]@{ Path=$resolved; Files=$files.Count; Bytes=($files | Measure-Object Length -Sum).Sum }
}
$records | Format-Table Path, Files, Bytes
if (-not $Apply) { Write-Output 'Dry run only; nothing deleted.'; return }
$auditDir = Join-Path $projectRoot ('logs\cleanup_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $auditDir | Out-Null
$manifest = [pscustomobject]@{ At=[DateTimeOffset]::Now.ToString('o'); Root=$projectRoot; Targets=@($records) }
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $auditDir 'manifest.json') -Encoding utf8
if (Test-Path -LiteralPath $envPath) {
    $freeze = & (Join-Path $envPath 'Scripts\python.exe') -m pip freeze
    if ($LASTEXITCODE -ne 0) { throw 'Cannot preserve environment package versions; nothing deleted.' }
    $freeze | Set-Content -LiteralPath (Join-Path $auditDir 'venv_test_packages.txt') -Encoding utf8
    Copy-Item -LiteralPath (Join-Path $envPath 'pyvenv.cfg') -Destination $auditDir
}
foreach ($record in $records) {
    # Targets were resolved, allowlisted by directory name, checked for tracked
    # files, links, and running processes above. No shell delegation for removal.
    Remove-Item -LiteralPath $record.Path -Recurse -Force
}
Write-Output ('Deleted generated files: ' + (($records | Measure-Object Files -Sum).Sum))
Write-Output ('Freed MiB: ' + [math]::Round((($records | Measure-Object Bytes -Sum).Sum / 1MB), 2))
Write-Output ('Audit and environment reconstruction versions: ' + $auditDir)
