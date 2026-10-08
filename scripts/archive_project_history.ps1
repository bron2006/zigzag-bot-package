param(
    [switch]$IncludeRetiredDatasets,
    [int]$KeepLogDays = 14,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
if ($KeepLogDays -lt 7) { throw 'Keep at least seven days of logs.' }
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
$expectedRoot = 'C:\Users\Work\Desktop\zigzag_bot'
if ($projectRoot -ne $expectedRoot) { throw 'Unexpected project root; nothing archived.' }
$archiveBase = 'C:\Users\Work\Desktop\zigzag_archives'
$archiveRoot = [IO.Path]::GetFullPath((Join-Path $archiveBase (Get-Date -Format 'yyyy-MM-dd')))
if (-not $archiveRoot.StartsWith($archiveBase + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unsafe archive destination.'
}
$cutoffUtc = (Get-Date).ToUniversalTime().AddDays(-$KeepLogDays)
$candidates = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'logs') -File -Filter '*.log' |
    Where-Object { $_.LastWriteTimeUtc -lt $cutoffUtc -and $_.Name -ne 'vwap_executor_supervisor.log' })
if ($IncludeRetiredDatasets) {
    # Retired experiments only; training history and all VWAP journals stay.
    foreach ($name in @('dataset_structural_full.csv', 'dataset_triple_barrier_full.csv',
        'tick_minute_features_EURUSD.csv', 'tick_sample_EURUSD_ask.csv', 'tick_sample_EURUSD_bid.csv')) {
        $candidate = Get-Item -LiteralPath (Join-Path (Join-Path $projectRoot 'data') $name) -ErrorAction SilentlyContinue
        if ($candidate) { $candidates += $candidate }
    }
}
$moved = 0
$bytes = [long]0
$skipped = 0
foreach ($file in $candidates) {
    $source = [IO.Path]::GetFullPath($file.FullName)
    if (-not $source.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Source outside workspace.'
    }
    $relative = $source.Substring($projectRoot.Length + 1)
    $destination = [IO.Path]::GetFullPath((Join-Path $archiveRoot $relative))
    if (-not $destination.StartsWith($archiveRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Destination outside dated archive.'
    }
    # A running executor's redirected log cannot be opened exclusively.
    $probe = $null
    try {
        $probe = [IO.File]::Open($source, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
    } catch { $skipped++; continue }
    finally { if ($probe) { $probe.Dispose() } }
    if ($DryRun) { $moved++; $bytes += $file.Length; continue }
    $before = Get-FileHash -LiteralPath $source -Algorithm SHA256
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    if (Test-Path -LiteralPath $destination) {
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $before.Hash) {
            throw "Archive collision; source preserved: $relative"
        }
    } else {
        Copy-Item -LiteralPath $source -Destination $destination
    }
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $before.Hash) {
        throw "Archive verification failed; source preserved: $relative"
    }
    $current = Get-Item -LiteralPath $source
    if ($current.Length -ne $file.Length -or $current.LastWriteTimeUtc -ne $file.LastWriteTimeUtc -or
        (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $before.Hash) {
        throw "Source changed during copy; original preserved: $relative"
    }
    # Write recoverability record BEFORE removing the verified original.
    [pscustomobject]@{ source=$source; archive=$destination; sha256=$before.Hash;
        bytes=$file.Length; archivedUtc=(Get-Date).ToUniversalTime().ToString('o') } |
        ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $archiveRoot 'manifest.jsonl') -Encoding UTF8
    Remove-Item -LiteralPath $source
    $moved++
    $bytes += $file.Length
}
[pscustomobject]@{ dryRun=[bool]$DryRun; files=$moved; megabytes=[math]::Round($bytes/1MB,2);
    lockedSkipped=$skipped; archive=$archiveRoot } | ConvertTo-Json -Compress
