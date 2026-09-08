# Build on Windows: python -m PyInstaller --noconfirm --clean ScrollFerry.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
datas, binaries, hiddenimports = [], [], []
for package in ('playwright', 'pypdfium2', 'pypdfium2_raw'):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
datas += [(str(root/'scrollferry'/'assets'/'logo.png'), 'scrollferry/assets')]
a = Analysis([str(root/'packaging'/'entry.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ScrollFerry',
          console=False, icon=str(root/'build'/'logo.ico'))
coll = COLLECT(exe, a.binaries, a.datas, name='ScrollFerry')
