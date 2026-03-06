param(
    [Parameter(Mandatory = $true)]
    [string]$MakeCommand,
    [Parameter(Mandatory = $true)]
    [string]$Profile,
    [Parameter(Mandatory = $true)]
    [string]$Start,
    [Parameter(Mandatory = $true)]
    [string]$End,
    [Parameter(Mandatory = $true)]
    [string]$Symbols,
    [Parameter(Mandatory = $true)]
    [string]$Timeframes,
    [Parameter(Mandatory = $true)]
    [string]$Stages,
    [Parameter()]
    [string]$VerifyReadinessArgs = "",
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputLabel,
    [Parameter(Mandatory = $true)]
    [string]$ArchiveRoot
)

$ErrorActionPreference = "Stop"

function Get-Sha256Hex {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $hashBytes = $sha256.ComputeHash($stream)
        }
        finally {
            $stream.Dispose()
        }
    }
    finally {
        $sha256.Dispose()
    }
    return ([System.BitConverter]::ToString($hashBytes)).Replace("-", "").ToLowerInvariant()
}

$profiles = @("strict", "context")
$passes = @("iso1", "iso2")
$results = @()

$archiveRootPath = [System.IO.Path]::GetFullPath($ArchiveRoot)
$archiveRunId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$archiveRunRoot = Join-Path $archiveRootPath $archiveRunId
New-Item -ItemType Directory -Force -Path $archiveRunRoot | Out-Null

foreach ($pass in $passes) {
    foreach ($profileName in $profiles) {
        Write-Output ("phase1-close: start profile=" + $profileName + " pass=" + $pass)

        & $MakeCommand clean
        if ($LASTEXITCODE -ne 0) {
            throw ("phase1-close failed: make clean profile=" + $profileName + " pass=" + $pass)
        }

        $e2eArgs = @(
            "run",
            "ACTION=e2e",
            "CONFIG_PROFILE=$profileName",
            "PROFILE=$Profile",
            "START=$Start",
            "END=$End",
            "SYMBOLS=$Symbols",
            "TIMEFRAMES=$Timeframes",
            "STAGES=$Stages"
        )
        & $MakeCommand @e2eArgs
        if ($LASTEXITCODE -ne 0) {
            throw ("phase1-close failed: make run ACTION=e2e profile=" + $profileName + " pass=" + $pass)
        }

        $manifestPath = "artifacts/readiness/readiness_acceptance_${profileName}_${OutputLabel}_${pass}.json"
        $verifyArgs = @(
            "run",
            "ACTION=verify-readiness",
            "CONFIG_PROFILE=$profileName",
            "PROFILE=$Profile",
            "START=$Start",
            "END=$End",
            "SYMBOLS=$Symbols",
            "TIMEFRAMES=$Timeframes",
            "READINESS_ACCEPTANCE_OUTPUT=$manifestPath"
        )
        if (-not [string]::IsNullOrWhiteSpace($VerifyReadinessArgs)) {
            $verifyArgs += "VERIFY_READINESS_ARGS=$VerifyReadinessArgs"
        }
        & $MakeCommand @verifyArgs
        if ($LASTEXITCODE -ne 0) {
            throw ("phase1-close failed: make run ACTION=verify-readiness profile=" + $profileName + " pass=" + $pass)
        }

        $payload = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $manifestHashPath = $manifestPath + ".sha256"
        if (-not (Test-Path -LiteralPath $manifestHashPath)) {
            throw ("phase1-close failed: missing manifest hash file " + $manifestHashPath)
        }

        # Archive each per-pass manifest outside artifacts so clean does not erase audit evidence.
        $archiveManifestPath = Join-Path $archiveRunRoot ([System.IO.Path]::GetFileName($manifestPath))
        $archiveManifestHashPath = $archiveManifestPath + ".sha256"
        Copy-Item -LiteralPath $manifestPath -Destination $archiveManifestPath -Force
        Copy-Item -LiteralPath $manifestHashPath -Destination $archiveManifestHashPath -Force

        $eventHashes = @{}
        foreach ($prop in $payload.artifact_hashes.PSObject.Properties) {
            if ($prop.Name -match "events[\\/](positions|signals|strikes)\.jsonl$") {
                $eventHashes[$prop.Name] = [string]$prop.Value
            }
        }
        if ($eventHashes.Count -lt 3) {
            throw ("phase1-close failed: expected event hashes in " + $manifestPath)
        }

        $results += [PSCustomObject]@{
            profile                     = [string]$profileName
            pass                        = [string]$pass
            manifest                    = [string]$manifestPath
            manifest_sha256_path        = [string]$manifestHashPath
            archived_manifest           = [string]$archiveManifestPath
            archived_manifest_sha256    = [string]$archiveManifestHashPath
            status                      = [string]$payload.status
            ready                       = [bool]$payload.academic_validation.ready
            blocking_reasons            = @($payload.academic_validation.blocking_reasons)
            max_q_value                 = [double]$payload.academic_validation.fdr_summary.max_q_value
            min_fold_trade_count        = [int]$payload.academic_validation.min_fold_trade_count
            boundary_failures_count     = [int]$payload.boundary_failures_count
            gap_quality_failures_count  = [int]$payload.gap_quality_failures_count
            closed_positions            = [int]$payload.summary_snapshot.closed_positions
            total_signals               = [int]$payload.summary_snapshot.total_signals
            total_strikes               = [int]$payload.summary_snapshot.total_strikes
            event_hashes                = $eventHashes
        }
    }
}

$failures = @()
foreach ($row in $results) {
    if ($row.status -ne "ok") {
        $failures += ("status_not_ok profile=" + $row.profile + " pass=" + $row.pass + " value=" + $row.status)
    }
    if (-not $row.ready) {
        $failures += ("academic_not_ready profile=" + $row.profile + " pass=" + $row.pass)
    }
    if (@($row.blocking_reasons).Count -gt 0) {
        $failures += ("blocking_reasons_present profile=" + $row.profile + " pass=" + $row.pass + " reasons=" + (@($row.blocking_reasons) -join ","))
    }
    if ($row.max_q_value -gt 0.05) {
        $failures += ("max_q_value_gt_0.05 profile=" + $row.profile + " pass=" + $row.pass + " value=" + $row.max_q_value)
    }
    if ($row.min_fold_trade_count -lt 14) {
        $failures += ("min_fold_trade_count_lt_14 profile=" + $row.profile + " pass=" + $row.pass + " value=" + $row.min_fold_trade_count)
    }
    if ($row.boundary_failures_count -ne 0) {
        $failures += ("boundary_failures_nonzero profile=" + $row.profile + " pass=" + $row.pass + " value=" + $row.boundary_failures_count)
    }
    if ($row.gap_quality_failures_count -ne 0) {
        $failures += ("gap_quality_failures_nonzero profile=" + $row.profile + " pass=" + $row.pass + " value=" + $row.gap_quality_failures_count)
    }
}

$determinism = @()
foreach ($profileName in $profiles) {
    $iso1 = @($results | Where-Object { $_.profile -eq $profileName -and $_.pass -eq "iso1" })
    $iso2 = @($results | Where-Object { $_.profile -eq $profileName -and $_.pass -eq "iso2" })
    if ($iso1.Count -ne 1 -or $iso2.Count -ne 1) {
        $failures += ("missing_iso_pair profile=" + $profileName)
        continue
    }
    $a = $iso1[0]
    $b = $iso2[0]
    $profileFailures = @()
    if ($a.closed_positions -ne $b.closed_positions) {
        $profileFailures += ("closed_positions_mismatch:" + $a.closed_positions + "!=" + $b.closed_positions)
    }
    if ($a.total_signals -ne $b.total_signals) {
        $profileFailures += ("total_signals_mismatch:" + $a.total_signals + "!=" + $b.total_signals)
    }
    if ($a.total_strikes -ne $b.total_strikes) {
        $profileFailures += ("total_strikes_mismatch:" + $a.total_strikes + "!=" + $b.total_strikes)
    }
    $keys = @($a.event_hashes.Keys) + @($b.event_hashes.Keys) | Sort-Object -Unique
    foreach ($key in $keys) {
        $hashA = if ($a.event_hashes.ContainsKey($key)) { [string]$a.event_hashes[$key] } else { "" }
        $hashB = if ($b.event_hashes.ContainsKey($key)) { [string]$b.event_hashes[$key] } else { "" }
        if ($hashA -ne $hashB) {
            $profileFailures += ("event_hash_mismatch key=" + $key)
        }
    }
    if ($profileFailures.Count -gt 0) {
        $failures += ("determinism_failed profile=" + $profileName + " details=" + ($profileFailures -join ","))
    }
    $determinism += [PSCustomObject]@{
        profile = [string]$profileName
        stable  = ($profileFailures.Count -eq 0)
        details = $profileFailures
    }
}

$status = if ($failures.Count -eq 0) { "ok" } else { "failed" }
$summary = [ordered]@{
    status                = $status
    checked_at            = (Get-Date).ToUniversalTime().ToString("o")
    command               = "make run ACTION=phase1-close"
    profile               = $Profile
    start                 = $Start
    end                   = $End
    symbols               = $Symbols
    timeframes            = $Timeframes
    stages                = $Stages
    verify_readiness_args = $VerifyReadinessArgs
    output_label          = $OutputLabel
    archive_root          = $archiveRootPath
    archive_run_root      = $archiveRunRoot
    runs                  = $results
    determinism           = $determinism
    failures              = $failures
}

$outputPathAbsolute = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = [System.IO.Path]::GetDirectoryName($outputPathAbsolute)
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}
$summaryJson = $summary | ConvertTo-Json -Depth 16
Set-Content -LiteralPath $outputPathAbsolute -Value $summaryJson -Encoding utf8
$summaryDigest = Get-Sha256Hex -Path $outputPathAbsolute
$summaryHashPath = $outputPathAbsolute + ".sha256"
$summaryHashLine = $summaryDigest + "  " + [System.IO.Path]::GetFileName($outputPathAbsolute)
Set-Content -LiteralPath $summaryHashPath -Value $summaryHashLine -Encoding utf8

Write-Output ("phase1-close archive_run_root=" + $archiveRunRoot)
Write-Output ("phase1-close summary_path=" + $outputPathAbsolute)
Write-Output ("phase1-close summary_sha256=" + $summaryDigest)
Write-Output ("phase1-close summary_hash_path=" + $summaryHashPath)
if ($failures.Count -gt 0) {
    throw ("phase1-close acceptance failed: " + ($failures -join " | "))
}
