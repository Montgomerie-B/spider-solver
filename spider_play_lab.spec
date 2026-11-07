# Independent one-folder Play Lab. Bundle the deal, accepted routes, and manifest.
# Mutable campaigns stay in per-user application data, not in this folder.
datas = [
    ('deals/4925153.txt', 'deals'),
    ('solutions/4925153_canonical.moves', 'solutions'),
    ('resources/play_lab_manifest.json', 'resources'),
    ('docs/research/autonomous_solve_campaign/4925153_cold_164.moves', 'docs/research/autonomous_solve_campaign'),
    ('docs/research/autonomous_solve_campaign/4925153_cold_162.moves', 'docs/research/autonomous_solve_campaign'),
    ('docs/research/autonomous_solve_campaign/4925153_cold_160.moves', 'docs/research/autonomous_solve_campaign'),
    ('docs/research/autonomous_solve_campaign/4925153_cold_158.moves', 'docs/research/autonomous_solve_campaign'),
    ('docs/research/incumbent_suffix_optimisation/4925153_assisted_157.moves', 'docs/research/incumbent_suffix_optimisation'),
    ('docs/research/pre120_optimisation/4925153_assisted_140.moves', 'docs/research/pre120_optimisation'),
    ('src/spider/incumbent_suffix.py', 'src/spider'),
    ('src/spider/packed_heap.py', 'src/spider'),
    ('src/spider/search_kernel.py', 'src/spider'),
    ('src/spider/global_search_experiment.py', 'src/spider'),
    ('src/spider/search_memory_profile.py', 'src/spider'),
    ('tools/pre120_optimisation.py', 'tools'),
]
a = Analysis(['tools/play_lab.py'], pathex=['src'], binaries=[], datas=datas,
             hiddenimports=[
                 'spider.unattended_optimiser',
                 'spider.packaged_runtime',
                 'spider.play_optimise_panel',
                 'spider.incumbent_suffix',
                 'spider.global_search_experiment',
                 'spider.search_kernel',
             ],
             hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SpiderPlayLab',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SpiderPlayLab')
