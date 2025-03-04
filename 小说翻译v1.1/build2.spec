# -*- mode: python -*-
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# PyQt6相关依赖处理
hiddenimports = [
    'PyQt6.QtPrintSupport',
    'PyQt6.QtNetwork',
    'PyQt6.QtCore',
    'PyQt6.QtGui'
]

datas = [
    ('icons/*', 'icons'),  # 包含图标文件
    ('api_key.txt', '.'),  # 包含配置文件
    ('requirements.txt', '.'),  # 包含 requirements.txt 文件
    ('LICENSE', '.'),  # 包含 LICENSE 文件
    *collect_data_files('docx')  # 包含python-docx模板
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DocTranslator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    icon='icons/Anon.ico',  # 设置应用图标
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)