param(
    [Parameter(Mandatory = $true)]
    [string]$MakeCommand,
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [Parameter()]
    [string]$FailOnAny = "false",
    [Parameter()]
    [string]$DefaultConfigProfile = "context",
    [Parameter()]
    [string]$DefaultVerifyReadinessArgs = ""
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

function ConvertTo-StrictBoolean {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )
    switch ($Value.Trim().ToLowerInvariant()) {
        "true" { return $true }
        "false" { return $false }
        default { throw "pair-batch failed: FailOnAny must be 'true' or 'false'" }
    }
}

function Get-EntryValue {
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Entry,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter()]
        [object]$Default = $null
    )
    $property = $Entry.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $Default
    }
    return $property.Value
}

function Get-RequiredEntryString {
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Entry,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter()]
        [string]$Default = ""
    )
    $value = [string](Get-EntryValue -Entry $Entry -Name $Name -Default $Default)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw ("pair-batch failed: manifest entry is missing required string field '" + $Name + "'")
    }
    return $value
}

function Get-ConfigOverrideArgument {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigProfile,
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath
    )
    switch ($ConfigProfile) {
        "context" { return "CONTEXT_CONFIG_PATH=$ConfigPath" }
        "strict" { return "STRICT_CONFIG_PATH=$ConfigPath" }
        default {
            throw ("pair-batch failed: unsupported config_profile '" + $ConfigProfile + "'")
        }
    }
}

function Get-LatestRunManifestPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchiveRoot
    )
    $runsRoot = Join-Path ([System.IO.Path]::GetFullPath($ArchiveRoot)) "runs"
    if (-not (Test-Path -LiteralPath $runsRoot)) {
        throw ("pair-batch failed: runs root not found " + $runsRoot)
    }
    $candidate = Get-ChildItem -Path $runsRoot -Recurse -File -Filter "run_manifest.json" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw ("pair-batch failed: no run_manifest.json found under " + $runsRoot)
    }
    return $candidate.FullName
}

function Set-PendingStagesToSkipped {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$StageStatus
    )
    foreach ($key in @("discover_range", "e2e", "verify_readiness")) {
        if ($StageStatus[$key] -eq "pending") {
            $StageStatus[$key] = "skipped"
        }
    }
}

$failOnAnyEnabled = ConvertTo-StrictBoolean -Value $FailOnAny

$manifestPathAbsolute = [System.IO.Path]::GetFullPath($ManifestPath)
if (-not (Test-Path -LiteralPath $manifestPathAbsolute)) {
    throw ("pair-batch failed: manifest not found " + $manifestPathAbsolute)
}

$manifestPayload = Get-Content -LiteralPath $manifestPathAbsolute -Raw | ConvertFrom-Json
$pairs = @(Get-EntryValue -Entry $manifestPayload -Name "pairs" -Default @())
if ($pairs.Count -eq 0) {
    throw ("pair-batch failed: manifest '" + $manifestPathAbsolute + "' contains no pairs")
}

$results = @()
$failures = @()

foreach ($entry in $pairs) {
    $pairId = Get-RequiredEntryString -Entry $entry -Name "id"
    $enabled = [bool](Get-EntryValue -Entry $entry -Name "enabled" -Default $true)
    $stageStatus = [ordered]@{
        discover_range = "pending"
        e2e = "pending"
        verify_readiness = "pending"
    }
    $result = [ordered]@{
        id = $pairId
        enabled = $enabled
        status = "pending"
        config_profile = $null
        config_path = $null
        archive_root = $null
        readiness_root = $null
        run_manifest = $null
        analysis_start = $null
        analysis_end = $null
        discover_range_output = $null
        readiness_acceptance_output = $null
        verify_readiness_args = $null
        failure_stage = $null
        failure_message = $null
        stages = $stageStatus
    }

    if (-not $enabled) {
        $stageStatus["discover_range"] = "skipped"
        $stageStatus["e2e"] = "skipped"
        $stageStatus["verify_readiness"] = "skipped"
        $result.status = "skipped"
        $results += [PSCustomObject]$result
        Write-Output ("pair-batch: skipped id=" + $pairId)
        continue
    }

    $currentStage = "discover_range"
    try {
        $configProfile = [string](Get-EntryValue -Entry $entry -Name "config_profile" -Default $DefaultConfigProfile)
        if ([string]::IsNullOrWhiteSpace($configProfile)) {
            $configProfile = $DefaultConfigProfile
        }
        $configPath = Get-RequiredEntryString -Entry $entry -Name "config_path"
        $archiveRoot = Get-RequiredEntryString -Entry $entry -Name "archive_root"
        $readinessRoot = Get-RequiredEntryString -Entry $entry -Name "readiness_root"
        $discoverSymbols = Get-RequiredEntryString -Entry $entry -Name "discover_symbols"
        $discoverTimeframes = Get-RequiredEntryString -Entry $entry -Name "discover_timeframes"
        $e2eProfile = [string](Get-EntryValue -Entry $entry -Name "e2e_profile" -Default "max_common")
        $e2eStages = [string](Get-EntryValue -Entry $entry -Name "e2e_stages" -Default "validate-config,backfill,replay,report")
        $e2eSymbols = Get-RequiredEntryString -Entry $entry -Name "e2e_symbols"
        $e2eTimeframes = Get-RequiredEntryString -Entry $entry -Name "e2e_timeframes"
        $backfillSymbols = Get-RequiredEntryString -Entry $entry -Name "backfill_symbols"
        $backfillTimeframes = Get-RequiredEntryString -Entry $entry -Name "backfill_timeframes"
        $replaySymbols = Get-RequiredEntryString -Entry $entry -Name "replay_symbols"
        $replayTimeframes = Get-RequiredEntryString -Entry $entry -Name "replay_timeframes"
        $verifySymbols = Get-RequiredEntryString -Entry $entry -Name "verify_symbols"
        $verifyTimeframes = Get-RequiredEntryString -Entry $entry -Name "verify_timeframes"
        $verifyReadinessArgs = [string](Get-EntryValue -Entry $entry -Name "verify_readiness_args" -Default $DefaultVerifyReadinessArgs)
        if ([string]::IsNullOrWhiteSpace($verifyReadinessArgs)) {
            $verifyReadinessArgs = "--require-academic-validation"
        }
        $discoverStart = [string](Get-EntryValue -Entry $entry -Name "discover_start" -Default "")
        $readinessEnd = [string](Get-EntryValue -Entry $entry -Name "readiness_end" -Default "")
        $customStart = [string](Get-EntryValue -Entry $entry -Name "start" -Default "")
        $customEnd = [string](Get-EntryValue -Entry $entry -Name "end" -Default "")
        $warmupDays = [string](Get-EntryValue -Entry $entry -Name "warmup_days" -Default "")

        $result.config_profile = $configProfile
        $result.config_path = $configPath
        $result.archive_root = $archiveRoot
        $result.readiness_root = $readinessRoot
        $result.verify_readiness_args = $verifyReadinessArgs
        $result.discover_range_output = (Join-Path $readinessRoot "discovered_range_manifest.json")
        $result.readiness_acceptance_output = (Join-Path $readinessRoot "readiness_acceptance.json")

        $configOverrideArgument = Get-ConfigOverrideArgument -ConfigProfile $configProfile -ConfigPath $configPath

        Write-Output ("pair-batch: start id=" + $pairId)
        $discoverArgs = @(
            "run",
            "ACTION=discover-range",
            "CONFIG_PROFILE=$configProfile",
            $configOverrideArgument,
            "SYMBOLS=$discoverSymbols",
            "TIMEFRAMES=$discoverTimeframes",
            "READINESS_ROOT=$readinessRoot"
        )
        if (-not [string]::IsNullOrWhiteSpace($discoverStart)) {
            $discoverArgs += "DISCOVER_START=$discoverStart"
        }
        if (-not [string]::IsNullOrWhiteSpace($readinessEnd)) {
            $discoverArgs += "READINESS_END=$readinessEnd"
        }
        & $MakeCommand @discoverArgs
        if ($LASTEXITCODE -ne 0) {
            throw ("make run ACTION=discover-range failed exit_code=" + $LASTEXITCODE)
        }
        $stageStatus["discover_range"] = "completed"

        $currentStage = "e2e"
        $e2eArgs = @(
            "run",
            "ACTION=e2e",
            "CONFIG_PROFILE=$configProfile",
            $configOverrideArgument,
            "PROFILE=$e2eProfile",
            "STAGES=$e2eStages",
            "SYMBOLS=$e2eSymbols",
            "TIMEFRAMES=$e2eTimeframes",
            "BACKFILL_SYMBOLS=$backfillSymbols",
            "BACKFILL_TIMEFRAMES=$backfillTimeframes",
            "REPLAY_SYMBOLS=$replaySymbols",
            "REPLAY_TIMEFRAMES=$replayTimeframes",
            "READINESS_ROOT=$readinessRoot"
        )
        if (-not [string]::IsNullOrWhiteSpace($customStart)) {
            $e2eArgs += "START=$customStart"
        }
        if (-not [string]::IsNullOrWhiteSpace($customEnd)) {
            $e2eArgs += "END=$customEnd"
        }
        if (-not [string]::IsNullOrWhiteSpace($warmupDays)) {
            $e2eArgs += "WARMUP_DAYS=$warmupDays"
        }
        & $MakeCommand @e2eArgs
        if ($LASTEXITCODE -ne 0) {
            throw ("make run ACTION=e2e failed exit_code=" + $LASTEXITCODE)
        }
        $stageStatus["e2e"] = "completed"

        $runManifestPath = Get-LatestRunManifestPath -ArchiveRoot $archiveRoot
        $result.run_manifest = $runManifestPath
        $runManifest = Get-Content -LiteralPath $runManifestPath -Raw | ConvertFrom-Json
        $analysisStart = [string](Get-EntryValue -Entry $runManifest.resolved_windows -Name "analysis_start" -Default "")
        $analysisEnd = [string](Get-EntryValue -Entry $runManifest.resolved_windows -Name "analysis_end" -Default "")
        if ([string]::IsNullOrWhiteSpace($analysisStart) -or [string]::IsNullOrWhiteSpace($analysisEnd)) {
            throw ("pair-batch failed: missing analysis window in run manifest " + $runManifestPath)
        }
        $result.analysis_start = $analysisStart
        $result.analysis_end = $analysisEnd

        $currentStage = "verify_readiness"
        $verifyArgs = @(
            "run",
            "ACTION=verify-readiness",
            "CONFIG_PROFILE=$configProfile",
            $configOverrideArgument,
            "SYMBOLS=$verifySymbols",
            "TIMEFRAMES=$verifyTimeframes",
            "START=$analysisStart",
            "END=$analysisEnd",
            "READINESS_ROOT=$readinessRoot",
            "VERIFY_READINESS_ARGS=$verifyReadinessArgs"
        )
        & $MakeCommand @verifyArgs
        if ($LASTEXITCODE -ne 0) {
            throw ("make run ACTION=verify-readiness failed exit_code=" + $LASTEXITCODE)
        }
        $stageStatus["verify_readiness"] = "completed"
        $result.status = "ok"
        Write-Output ("pair-batch: completed id=" + $pairId)
    }
    catch {
        $stageStatus[$currentStage] = "failed"
        Set-PendingStagesToSkipped -StageStatus $stageStatus
        $result.status = "failed"
        $result.failure_stage = $currentStage
        $result.failure_message = $_.Exception.Message
        $failures += ("pair=" + $pairId + " stage=" + $currentStage + " error=" + $_.Exception.Message)
        Write-Output ("pair-batch: failed id=" + $pairId + " stage=" + $currentStage + " error=" + $_.Exception.Message)
    }

    $results += [PSCustomObject]$result
}

$summaryStatus = if ($failures.Count -eq 0) { "ok" } else { "completed_with_failures" }
$summary = [ordered]@{
    status = $summaryStatus
    checked_at = (Get-Date).ToUniversalTime().ToString("o")
    command = "make run ACTION=pair-batch"
    manifest_path = $manifestPathAbsolute
    output_path = [System.IO.Path]::GetFullPath($OutputPath)
    fail_on_any = $failOnAnyEnabled
    default_config_profile = $DefaultConfigProfile
    default_verify_readiness_args = $DefaultVerifyReadinessArgs
    pair_count = $pairs.Count
    success_count = @($results | Where-Object { $_.status -eq "ok" }).Count
    failure_count = @($results | Where-Object { $_.status -eq "failed" }).Count
    skipped_count = @($results | Where-Object { $_.status -eq "skipped" }).Count
    failures = $failures
    runs = $results
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

Write-Output ("pair-batch summary_path=" + $outputPathAbsolute)
Write-Output ("pair-batch summary_sha256=" + $summaryDigest)
Write-Output ("pair-batch summary_hash_path=" + $summaryHashPath)
if ($failures.Count -gt 0 -and $failOnAnyEnabled) {
    throw ("pair-batch acceptance failed: " + ($failures -join " | "))
}
