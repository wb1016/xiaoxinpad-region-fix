param(
    # Point $Expdb at a 128 MB expdb dump read out of the device (see
    # configs/read_calibration.xml + docs/02-diagnosis.md).
    [string]$Expdb = 'expdb.bin',
    [string]$Out   = 'lk_boot_log.txt'
)
$ErrorActionPreference='Continue'
$enc=[System.Text.Encoding]::GetEncoding(28591)
$rx=[regex]'[\x20-\x7e]{5,}'
$b=[System.IO.File]::ReadAllBytes($Expdb)
if ($b.Length -lt 0x8000000) { Write-Output ("WARNING: {0} is only {1} bytes; expdb is expected to be 128 MB" -f $Expdb, $b.Length) }
$start=0x7E00000; $end=[Math]::Min(0x8000000, $b.Length)
$txt=$enc.GetString($b,$start,$end-$start)
$sb=New-Object System.Text.StringBuilder
foreach($m in $rx.Matches($txt)){ [void]$sb.AppendLine($m.Value) }
[System.IO.File]::WriteAllText($Out,$sb.ToString())
Write-Output "wrote $Out : $((Get-Item $Out).Length) bytes, $((Get-Content $Out).Count) lines"
Write-Output ''
Write-Output '=== [Check_Region] lines (the decision trace: 1427 = flag gate, 1437 = region compare) ==='
Select-String -Path $Out -Pattern 'Check_Region' -ErrorAction SilentlyContinue | ForEach-Object { "  " + $_.Line } | Out-String -Width 240
Write-Output '=== AVB / ASSERT failures (the other power-off mode) ==='
Select-String -Path $Out -Pattern 'avb_slot_verify|invalid pubk|ASSERT FAILED|HALT:' -ErrorAction SilentlyContinue | Select-Object -Last 20 | ForEach-Object { "  " + $_.Line } | Out-String -Width 240
Write-Output '=== lines matching key diagnostics ==='
Select-String -Path $Out -Pattern '(?i)(not compatib|compatib|incompatib|hardware|power off|sku|pcba|hwboardid|PRODUCT_MODEL|denied|reject|version check|arb|rollback)' -ErrorAction SilentlyContinue | Select-Object -First 50 | ForEach-Object { "  " + $_.Line } | Out-String -Width 240
Write-Output '=== LAST 60 lines of the log ==='
Get-Content $Out | Select-Object -Last 60 | Out-String -Width 240