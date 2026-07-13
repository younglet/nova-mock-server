"""
build.py — 一键打包 nova_mock_server.exe
==========================================

流程：
  1. icon.png  →  icon.ico  (多尺寸：256/128/64/48/32/16)
  2. pyinstaller --onefile --noconsole
  3. 输出 nova_mock_server.exe

用法：
  pip install -r requirements.txt
  python build.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.resolve()
SRC = ROOT / 'src'
ICON_PNG = ROOT / 'icon.png'
ICON_ICO = SRC / 'icon.ico'
ENTRY = SRC / 'main.py'
OUTPUT = ROOT / 'nova_mock_server.exe'


def log(msg):
    print(f'>>> {msg}')


def gen_ico():
    """PNG → 多尺寸 ICO。"""
    if not ICON_PNG.exists():
        sys.exit(f'找不到 {ICON_PNG}')
    try:
        from PIL import Image
    except ImportError:
        sys.exit('缺少 Pillow，先执行: pip install Pillow')

    img = Image.open(ICON_PNG)
    img.save(ICON_ICO, format='ICO', sizes=[
        (256, 256), (128, 128), (64, 64),
        (48, 48), (32, 32), (16, 16),
    ])
    log(f'已生成 {ICON_ICO.relative_to(ROOT)} (从 {ICON_PNG.name})')


def clean():
    """清理上一次的构建产物。"""
    for p in [ROOT / 'build', SRC / '__pycache__', SRC / 'nova_mock_server.spec']:
        if p.exists():
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def pyinstall():
    """调用 pyinstaller。"""
    add_data = f'{SRC / "ui" / "index.html"};ui'
    # 排除用不到的 GUI 后端与大型库（只用 edgechromium）
    excludes = [
        'PyQt5', 'PyQt5.sip', 'PyQt5.QtCore', 'PyQt5.QtGui',
        'PyQt5.QtWidgets', 'PyQt5.QtNetwork', 'PyQt5.QtWebEngine',
        'PySide2', 'PySide6', 'shiboken2', 'shiboken6',
        'tkinter', 'wx', 'gtk',
        'cefpython3', 'cefpython3_py37',
    ]
    cmd = [sys.executable, '-m', 'PyInstaller',
        '--onefile', '--noconsole',
        '--name', 'nova_mock_server',
        '--icon', str(ICON_ICO),
        '--add-data', add_data,
        '--distpath', str(SRC),
        '--workpath', str(ROOT / 'build'),
        '--specpath', str(SRC),
        '--clean',
        *[item for ex in excludes for item in ('--exclude-module', ex)],
        str(ENTRY),
    ]
    log('运行 pyinstaller …')
    r = subprocess.run(cmd, cwd=SRC)
    if r.returncode != 0:
        sys.exit(f'pyinstaller 失败 (code {r.returncode})')

    built = SRC / 'nova_mock_server.exe'
    if not built.exists():
        sys.exit(f'找不到 {built}')

    # 移动到根目录
    if OUTPUT.exists():
        OUTPUT.unlink()
    shutil.move(str(built), str(OUTPUT))
    size_kb = OUTPUT.stat().st_size // 1024
    log(f'完成: {OUTPUT.relative_to(ROOT)}  ({size_kb} KB)')


if __name__ == '__main__':
    gen_ico()
    clean()
    pyinstall()
    log('OK')