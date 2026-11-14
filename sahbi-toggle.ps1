# Sahbi on/off for gaming.
#   (no argument) = toggle    -Off = game mode (frees GPU + RAM)    -On = Sahbi back
param([switch]$On, [switch]$Off)

$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = @("$here\.venv\Scripts\pythonw.exe", "$(Split-Path -Parent $here)\.venv\Scripts\pythonw.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $py) { $py = 'pythonw.exe' }
$ollama = "$env:LOCALAPPDATA\Programs\Ollama"

function Get-SahbiPid {
    Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
}

function Show-Note($title, $text) {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $n = New-Object System.Windows.Forms.NotifyIcon
    $ico = Join-Path $here 'sahbi.ico'
    $n.Icon = if (Test-Path $ico) { New-Object System.Drawing.Icon $ico } else { [System.Drawing.SystemIcons]::Information }
    $n.Visible = $true
    $n.ShowBalloonTip(4000, $title, $text, 'Info')
    Start-Sleep -Seconds 5
    $n.Dispose()
}

$running = [bool](Get-SahbiPid)
if (-not $On -and -not $Off) { if ($running) { $Off = $true } else { $On = $true } }

if ($Off) {
    # 1. stop Sahbi (mic listener + page server)
    Get-SahbiPid | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    # 2. unload the AI model from the GPU, then close Ollama completely (frees VRAM and RAM)
    if (Test-Path "$ollama\ollama.exe") { & "$ollama\ollama.exe" stop qwen2.5:7b 2>$null | Out-Null }
    Get-Process -Name 'ollama app', 'ollama' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
    $vram = (& nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>$null) -join ''
    Show-Note 'Game mode ON' "Sahbi is off - GPU free ($vram used). Double-click 'Sahbi On-Off' to bring it back."
}
else {
    # start Ollama's tray app (it starts the AI server), then Sahbi
    if (-not (Get-Process -Name 'ollama' -ErrorAction SilentlyContinue) -and (Test-Path "$ollama\ollama app.exe")) {
        Start-Process "$ollama\ollama app.exe"
        for ($i = 0; $i -lt 20; $i++) {
            try { Invoke-RestMethod http://127.0.0.1:11434 -TimeoutSec 1 | Out-Null; break } catch { Start-Sleep -Milliseconds 500 }
        }
    }
    if (-not (Get-SahbiPid)) {
        Start-Process -FilePath $py -ArgumentList "`"$here\sahbi.py`"" -WorkingDirectory $here
    }
    Show-Note 'Sahbi is ON' 'Say "Salam Sahbi" whenever you need me.'
}
