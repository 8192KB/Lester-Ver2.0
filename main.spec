# -*- mode: python ; coding: utf-8 -*-
#
# 빌드: pyinstaller main.spec
#
# 이 프로그램이 실제로 쓰는 OpenCV 기능은 cvtColor / matchTemplate /
# threshold / inRange / connectedComponents 뿐이다. 영상 코덱과 GUI는
# 전혀 쓰지 않으므로 통째로 빼서 용량을 줄인다.

EXCLUDE_BINARIES = (
    'opencv_videoio_ffmpeg',   # 약 28MB, 영상 입출력용 - 안 씀
)

EXCLUDE_MODULES = [
    'tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython',
    'pytest', 'setuptools', 'pip', 'sqlite3', 'unittest',
    'numpy.testing', 'numpy.f2py', 'PIL.ImageQt',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDE_MODULES,
    noarchive=False,
    # optimize=2는 docstring을 지우는데, numpy가 add_docstring에서 이를
    # 요구하므로 실행 즉시 TypeError로 죽는다. 반드시 0으로 둔다.
    optimize=0,
)

a.binaries = [b for b in a.binaries
              if not any(skip in b[0].lower() for skip in EXCLUDE_BINARIES)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Lester-Ver2.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
