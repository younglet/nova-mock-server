# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\young\\Desktop\\mock-server\\src\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\young\\Desktop\\mock-server\\src\\ui\\index.html', 'ui')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt5.sip', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtNetwork', 'PyQt5.QtWebEngine', 'PySide2', 'PySide6', 'shiboken2', 'shiboken6', 'tkinter', 'wx', 'gtk', 'cefpython3', 'cefpython3_py37'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='nova_mock_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\young\\Desktop\\mock-server\\src\\icon.ico'],
)
