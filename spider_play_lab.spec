# Independent one-folder Play Lab; no campaign modules or production data.
a = Analysis(['tools/play_lab.py'], pathex=['src'], binaries=[],
             datas=[('deals/4925153.txt', 'deals'),
                    ('solutions/4925153_canonical.moves', 'solutions')],
             hiddenimports=[], hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SpiderPlayLab',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SpiderPlayLab')
