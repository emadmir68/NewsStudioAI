$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " News Studio AI - Free Animation AI Setup" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "This installs local open-source models. No paid API key is used."
Write-Host ""

function Find-Ollama {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:ProgramFiles\Ollama\ollama.exe"
    )
    foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
    return $null
}

$ollama = Find-Ollama
if (-not $ollama) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Ollama پیدا نشد. ابتدا از https://ollama.com/download نسخه Windows را نصب کنید، سپس این فایل را دوباره اجرا کنید."
    }
    Write-Host "Installing Ollama..." -ForegroundColor Yellow
    winget install --id Ollama.Ollama --exact --silent --accept-package-agreements --accept-source-agreements
    $ollama = Find-Ollama
    if (-not $ollama) {
        Write-Host "Ollama نصب شد. PowerShell را ببندید و این فایل را دوباره اجرا کنید." -ForegroundColor Yellow
        exit 0
    }
}

$ollamaProcess = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaProcess) {
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

Write-Host "Downloading visual model qwen3-vl:2b (about 2 GB)..." -ForegroundColor Yellow
& $ollama pull qwen3-vl:2b
if ($LASTEXITCODE -ne 0) { throw "دریافت مدل بینایی ناموفق بود." }

$py = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    $pythonExe = $py.Source
    $pythonArgs = @("-3.11")
} elseif ($python) {
    $pythonExe = $python.Source
    $pythonArgs = @()
} else {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { throw "برای نصب موتور صدای فارسی، Python 3.11 لازم است. آن را از python.org نصب کنید." }
    Write-Host "Installing Python 3.11..." -ForegroundColor Yellow
    winget install --id Python.Python.3.11 --exact --silent --accept-package-agreements --accept-source-agreements
    Write-Host "Python نصب شد. PowerShell را ببندید و فایل نصب مدل‌ها را دوباره اجرا کنید." -ForegroundColor Yellow
    exit 0
}

$root = Join-Path $env:LOCALAPPDATA "NewsStudioAI\animation-ai"
New-Item -ItemType Directory -Force -Path $root | Out-Null
$venv = Join-Path $root "venv"
$repo = Join-Path $root "MOSS-TTS-Nano"

if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Write-Host "Creating isolated Python environment..." -ForegroundColor Yellow
    & $pythonExe @pythonArgs -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "ساخت محیط پایتون ناموفق بود." }
}

$venvPython = Join-Path $venv "Scripts\python.exe"
Write-Host "Preparing MOSS Persian TTS runtime..." -ForegroundColor Yellow
if (-not (Test-Path (Join-Path $repo "app.py"))) {
    $zip = Join-Path $root "moss-tts-nano.zip"
    $extract = Join-Path $root "moss-extract"
    Invoke-WebRequest -Uri "https://github.com/OpenMOSS/MOSS-TTS-Nano/archive/refs/heads/main.zip" -OutFile $zip
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    $source = Get-ChildItem $extract -Directory | Select-Object -First 1
    if (-not $source) { throw "دریافت سورس MOSS-TTS-Nano ناموفق بود." }
    if (Test-Path $repo) { Remove-Item $repo -Recurse -Force }
    Move-Item $source.FullName $repo
    Remove-Item $extract -Recurse -Force
    Remove-Item $zip -Force
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "به‌روزرسانی pip ناموفق بود." }

# CPU-only PyTorch: no CUDA/GPU package is downloaded.
& $venvPython -m pip install torch==2.7.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw "نصب نسخه CPU کتابخانه PyTorch ناموفق بود." }

& $venvPython -m pip install -r (Join-Path $repo "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "نصب وابستگی‌های موتور صدای فارسی ناموفق بود." }

& $venvPython -m pip install -e $repo
if ($LASTEXITCODE -ne 0) { throw "نصب MOSS-TTS-Nano ناموفق بود." }

Write-Host ""
Write-Host "Checking visual model..." -ForegroundColor Yellow
$visionReady = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
        $visionReady = @($tags.models | Where-Object { $_.name -like "qwen3-vl:2b*" }).Count -gt 0
        if ($visionReady) { break }
    } catch {}
    Start-Sleep -Seconds 2
}
Write-Host ""
if ($visionReady) { Write-Host "Visual analysis model: READY" -ForegroundColor Green } else { Write-Host "Visual analysis model: check Ollama" -ForegroundColor Yellow }
Write-Host "Persian TTS runtime installed. It will start automatically when you click 'تولید صدای شخصیت‌ها'." -ForegroundColor Green
Write-Host "The Persian speech model downloads on first use. First model downloads require internet; processing is local after setup."
Write-Host "Setup finished. Open News Studio AI and press 'بررسی موتورهای هوشمند'." -ForegroundColor Cyan
