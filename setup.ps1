# One-time setup: Python environment, local models and the voice.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if (-not (Test-Path .venv)) { python -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt

ollama pull qwen2.5:7b
ollama pull qwen2.5vl:3b
ollama pull nomic-embed-text

New-Item -ItemType Directory -Force voices | Out-Null
$base = 'https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium'
foreach ($f in 'en_US-lessac-medium.onnx', 'en_US-lessac-medium.onnx.json') {
    if (-not (Test-Path "voices\$f")) { Invoke-WebRequest "$base/$f" -OutFile "voices\$f" }
}
if (-not (Test-Path config.json)) { Copy-Item config.example.json config.json; Write-Host 'Edit config.json with your details.' }
Write-Host 'Done. Start with: .venv\Scripts\pythonw.exe sahbi.py --open'
