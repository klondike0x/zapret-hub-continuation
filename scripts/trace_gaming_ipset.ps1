param(
    [string]$Label = "game",
    [int]$DurationSeconds = 120,
    [int]$IntervalMs = 750,
    [string]$OutputDir = ".\diagnostics\gaming-ipset",
    [string]$IpSetPath = ".\sample_data\default_services\gaming\lists\ipset-local-exclude.txt"
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function ConvertTo-IpUInt32 {
    param([string]$Ip)
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Ip, [ref]$parsed)) {
        return $null
    }
    $bytes = $parsed.GetAddressBytes()
    if ($bytes.Length -ne 4) {
        return $null
    }
    [Array]::Reverse($bytes)
    return [BitConverter]::ToUInt32($bytes, 0)
}

function Convert-CidrToRange {
    param([string]$Cidr)
    $parts = $Cidr.Trim().Split("/")
    if ($parts.Count -ne 2) {
        return $null
    }
    $baseIp = ConvertTo-IpUInt32 $parts[0]
    if ($null -eq $baseIp) {
        return $null
    }
    $prefix = 0
    if (-not [int]::TryParse($parts[1], [ref]$prefix) -or $prefix -lt 0 -or $prefix -gt 32) {
        return $null
    }
    $hostCount = [uint64]([math]::Pow(2, 32 - $prefix) - 1)
    $mask = [uint32]([uint64]4294967295 - $hostCount)
    $network = [uint32]($baseIp -band $mask)
    $broadcast = [uint32]([uint64]$network + $hostCount)
    [pscustomobject]@{
        Cidr = $Cidr.Trim()
        Start = $network
        End = $broadcast
    }
}

function Find-CidrMatch {
    param(
        [string]$Ip,
        [array]$Ranges
    )
    $value = ConvertTo-IpUInt32 $Ip
    if ($null -eq $value) {
        return $null
    }
    foreach ($range in $Ranges) {
        if ($value -ge $range.Start -and $value -le $range.End) {
            return $range.Cidr
        }
    }
    return $null
}

$root = Resolve-Path -LiteralPath "."
$ipset = Resolve-Path -LiteralPath $IpSetPath
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$targetDir = Join-Path $OutputDir "$stamp-$Label"
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

$ranges = Get-Content -LiteralPath $ipset |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") -and $_ -notmatch ":" } |
    ForEach-Object { Convert-CidrToRange $_ } |
    Where-Object { $null -ne $_ }

if (-not $ranges) {
    throw "Failed to read IPv4 CIDR from $ipset"
}

$tcpMatches = @{}
$tcpRawPath = Join-Path $targetDir "tcp_raw.csv"
$tcpMatchesPath = Join-Path $targetDir "tcp_matches.csv"
$pktmonText = Join-Path $targetDir "pktmon.txt"
$pktmonMatchesPath = Join-Path $targetDir "pktmon_matches.csv"
$pktmonFlowMatchesPath = Join-Path $targetDir "pktmon_flow_matches.csv"
$summaryPath = Join-Path $targetDir "summary.txt"

"time,process,pid,local,remote,state,matched_cidr" | Set-Content -LiteralPath $tcpRawPath -Encoding UTF8
"ip,matched_cidr,count,source" | Set-Content -LiteralPath $tcpMatchesPath -Encoding UTF8

$usePktmon = (Test-IsAdmin) -and [bool](Get-Command pktmon.exe -ErrorAction SilentlyContinue)
$etl = Join-Path $targetDir "capture.etl"
if ($usePktmon) {
    & pktmon filter remove | Out-Null
    & pktmon start --capture --pkt-size 0 --file-name $etl | Out-Null
    Write-Host "pktmon started. Launch the game and reproduce the voice/connectivity moment."
} else {
    Write-Host "pktmon is unavailable or the script is not elevated. Only TCP snapshots will be saved."
}

$deadline = (Get-Date).AddSeconds($DurationSeconds)
try {
    while ((Get-Date) -lt $deadline) {
        $now = Get-Date -Format "o"
        $connections = Get-NetTCPConnection -ErrorAction SilentlyContinue |
            Where-Object { $_.RemoteAddress -and $_.RemoteAddress -notin @("0.0.0.0", "::", "::1", "127.0.0.1") }
        foreach ($connection in $connections) {
            $remote = [string]$connection.RemoteAddress
            $matched = Find-CidrMatch $remote $ranges
            $processName = ""
            try {
                $processName = (Get-Process -Id $connection.OwningProcess -ErrorAction Stop).ProcessName
            } catch {
                $processName = "unknown"
            }
            $matchedText = ""
            if ($matched) {
                $matchedText = $matched
            }
            $line = '"{0}","{1}",{2},"{3}:{4}","{5}:{6}","{7}","{8}"' -f `
                $now,
                $processName,
                $connection.OwningProcess,
                $connection.LocalAddress,
                $connection.LocalPort,
                $connection.RemoteAddress,
                $connection.RemotePort,
                $connection.State,
                $matchedText
            Add-Content -LiteralPath $tcpRawPath -Value $line -Encoding UTF8
            if ($matched) {
                $key = "$remote|$matched"
                $currentCount = 0
                if ($tcpMatches.ContainsKey($key)) {
                    $currentCount = [int]$tcpMatches[$key]
                }
                $tcpMatches[$key] = 1 + $currentCount
            }
        }
        Start-Sleep -Milliseconds $IntervalMs
    }
} finally {
    if ($usePktmon) {
        & pktmon stop | Out-Null
        & pktmon etl2txt $etl -o $pktmonText | Out-Null
    }
}

foreach ($entry in $tcpMatches.GetEnumerator() | Sort-Object Value -Descending) {
    $parts = $entry.Key.Split("|")
    '"{0}","{1}",{2},"tcp"' -f $parts[0], $parts[1], $entry.Value |
        Add-Content -LiteralPath $tcpMatchesPath -Encoding UTF8
}

$pktmonMatches = @{}
$pktmonFlowMatches = @{}
if (Test-Path -LiteralPath $pktmonText) {
    $ipRegex = [regex]'(?<!\d)(\d{1,3}(?:\.\d{1,3}){3})(?!\d)'
    $flowRegex = [regex]'(\d{1,3}(?:\.\d{1,3}){3})\.(\d+)\s*>\s*(\d{1,3}(?:\.\d{1,3}){3})\.(\d+):\s*(UDP|Flags)'
    foreach ($line in Get-Content -LiteralPath $pktmonText) {
        $flow = $flowRegex.Match($line)
        if ($flow.Success) {
            $srcIp = $flow.Groups[1].Value
            $srcPort = [int]$flow.Groups[2].Value
            $dstIp = $flow.Groups[3].Value
            $dstPort = [int]$flow.Groups[4].Value
            $protocol = if ($flow.Groups[5].Value -eq "Flags") { "TCP" } else { "UDP" }
            $remoteIp = $null
            $remotePort = 0
            if ($srcIp.StartsWith("192.168.") -or $srcIp -eq "127.0.0.1") {
                $remoteIp = $dstIp
                $remotePort = $dstPort
            } elseif ($dstIp.StartsWith("192.168.") -or $dstIp -eq "127.0.0.1") {
                $remoteIp = $srcIp
                $remotePort = $srcPort
            }
            if ($remoteIp) {
                $cidr = Find-CidrMatch $remoteIp $ranges
                if ($cidr) {
                    $key = "$protocol|$remoteIp|$remotePort|$cidr"
                    $currentCount = 0
                    if ($pktmonFlowMatches.ContainsKey($key)) {
                        $currentCount = [int]$pktmonFlowMatches[$key]
                    }
                    $pktmonFlowMatches[$key] = 1 + $currentCount
                }
            }
        }
        foreach ($match in $ipRegex.Matches($line)) {
            $ip = $match.Groups[1].Value
            $cidr = Find-CidrMatch $ip $ranges
            if ($cidr) {
                $key = "$ip|$cidr"
                $currentCount = 0
                if ($pktmonMatches.ContainsKey($key)) {
                    $currentCount = [int]$pktmonMatches[$key]
                }
                $pktmonMatches[$key] = 1 + $currentCount
            }
        }
    }
    "ip,matched_cidr,count,source" | Set-Content -LiteralPath $pktmonMatchesPath -Encoding UTF8
    foreach ($entry in $pktmonMatches.GetEnumerator() | Sort-Object Value -Descending) {
        $parts = $entry.Key.Split("|")
        '"{0}","{1}",{2},"pktmon"' -f $parts[0], $parts[1], $entry.Value |
            Add-Content -LiteralPath $pktmonMatchesPath -Encoding UTF8
    }
    "protocol,remote_ip,remote_port,matched_cidr,count" | Set-Content -LiteralPath $pktmonFlowMatchesPath -Encoding UTF8
    foreach ($entry in $pktmonFlowMatches.GetEnumerator() | Sort-Object Value -Descending) {
        $parts = $entry.Key.Split("|")
        '"{0}","{1}",{2},"{3}",{4}' -f $parts[0], $parts[1], $parts[2], $parts[3], $entry.Value |
            Add-Content -LiteralPath $pktmonFlowMatchesPath -Encoding UTF8
    }
}

$matchedCidrs = @()
$matchedCidrs += $tcpMatches.Keys | ForEach-Object { $_.Split("|")[1] }
$matchedCidrs += $pktmonMatches.Keys | ForEach-Object { $_.Split("|")[1] }
$matchedCidrs = $matchedCidrs | Sort-Object -Unique

@(
    "Diagnostics: $Label",
    "Folder: $targetDir",
    "IPSet: $ipset",
    "pktmon: $usePktmon",
    "",
    "Matched CIDR from ipset-local-exclude:",
    (($matchedCidrs | ForEach-Object { "- $_" }) -join [Environment]::NewLine),
    "",
    "How to test:",
    "1. Run this script as Administrator for ARK Raiders with local exclude enabled.",
    "2. In game, reproduce the moment where voice chat works.",
    "3. Then run this script with another Label for Back 4 Blood without local exclude.",
    "4. Compare pktmon_flow_matches.csv, pktmon_matches.csv and tcp_matches.csv: shared ranges are risky, unused broad ranges can be narrowed."
) | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host "Done: $targetDir"
Write-Host "Main files: summary.txt, tcp_matches.csv, pktmon_matches.csv, pktmon_flow_matches.csv"
