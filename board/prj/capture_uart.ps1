param(
    [ValidatePattern('^COM[0-9]+$')][string]$Port = 'COM4',
    [ValidateRange(1, 3600)][int]$Seconds = 120,
    [string]$Output = ''
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (!$Output) {
    $Output = Join-Path $repo ("data/captures/m01_uart_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
}
$Output = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Force -Path (Split-Path $Output -Parent) | Out-Null
$uart = [IO.Ports.SerialPort]::new($Port, 115200, 'None', 8, 'One')
$uart.DtrEnable = $false
$uart.RtsEnable = $false
$uart.ReadBufferSize = 65536
$writer = $null
try {
    $writer = [IO.StreamWriter]::new([IO.FileStream]::new($Output, 'CreateNew', 'Write', 'Read'))
    $writer.AutoFlush = $true
    $uart.Open()
    Write-Host "UART_CAPTURE_OPEN $Port 115200/8N1 $Output"
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt $Seconds) {
        $chunk = $uart.ReadExisting()
        if ($chunk) { $writer.Write($chunk); Write-Host -NoNewline $chunk }
        Start-Sleep -Milliseconds 100
    }
    $writer.Write($uart.ReadExisting())
} finally {
    $uart.Dispose()
    if ($writer) { $writer.Dispose() }
}
Write-Host "UART_CAPTURE_DONE $Output"
