$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force build | Out-Null
python -c "from PIL import Image; Image.open('scrollferry/assets/logo.png').save('build/logo.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if ($LASTEXITCODE -ne 0) { throw 'Logo conversion failed' }
python -m PyInstaller --noconfirm --clean ScrollFerry.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
$innoCompiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (-not (Test-Path $innoCompiler)) {
    throw 'Install Inno Setup 6 before building the installer.'
}
& $innoCompiler packaging/installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
