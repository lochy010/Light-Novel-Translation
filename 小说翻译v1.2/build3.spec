# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller import log as logging
logger = logging.getLogger('PyInstaller')

# 强制包含可能遗漏的Qt插件
hiddenimports = [
    'PyQt6.QtPrintSupport',
    'PyQt6.QtNetwork',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtSvg',  # SVG图标支持
    'openai._vendor.httpx',
    'docx.oxml',    # docx子模块
    'docx.enum',     # docx枚举模块
    'docx.shared',   # docx共享模块
    'docx.templates' # docx模板支持
]

# 包含数据文件
datas = [
    ('config/*.py', 'config'),          # 配置文件
    ('icons/*', 'icons'),               # 图标资源
    ('api_key.txt', '.'),               # API密钥文件
    *collect_data_files('docx')         # python-docx模板
]

# 强制包含可能动态导入的模块
hiddenimports += collect_submodules('chardet')

# 添加Qt插件路径（解决SVG图标问题）
from PyQt6 import QtCore
binaries = [
    (QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.PluginsPath) + '/imageformats/qsvg.dll', 'PyQt6/Qt6/plugins/imageformats')
]

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False
)

# 配置打包参数
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='DocTranslator',  # 应用名称
    debug=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                 # 不显示控制台
    icon='icons/Anon.ico',         # 应用图标
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 资源文件路径修正（在运行时通过sys._MEIPASS访问）
a.datas += [
    ('config/settings.py', 'config/settings.py', 'DATA'),
    ('config/__init__.py', 'config/__init__.py', 'DATA'),
    ('gui/gui_config.py', 'gui/gui_config.py', 'DATA'),
]