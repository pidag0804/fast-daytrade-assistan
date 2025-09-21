# fast_daytrade_assistant.spec
# 打包 PySide6 + qasync + httpx 的穩健 spec
import os
from PyInstaller.utils.hooks import collect_all

# 收集 PySide6 所需的 plugins、平台 dll 等
pyside_binaries, pyside_datas, pyside_hiddenimports = collect_all('PySide6')
httpx_binaries, httpx_datas, httpx_hiddenimports   = collect_all('httpx')

# 打包你的資源：至少把 QSS 與（若有）圖示帶上
# 如果 assets 內還有字體、圖、icon，一樣照著追加
datas = [
    ('assets/styles.qss', 'assets'),
    # ('assets/app.ico', 'assets'),  # 若有 icon 就解除註解
] + pyside_datas + httpx_datas

binaries = pyside_binaries + httpx_binaries
hiddenimports = pyside_hiddenimports + httpx_hiddenimports + [
    'qasync',
    'numpy',
    # 若還有其他隱式載入的模組，可在此追加
]

block_cipher = None

a = Analysis(
    ['app.py'],  # 你的進入點
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],  # 如有自訂 hook 可放這裡
    noarchive=False,
)

exe = EXE(
    pyz=PYZ(a.pure, a.zipped_data, cipher=block_cipher),
    scripts=a.scripts,
    exclude_binaries=True,
    name='FastDaytradeAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,             # 想看 console 日誌就改 True
    disable_windowed_traceback=False,
    argv_emulation=False,
    # icon='assets/app.ico',   # 若有 .ico 圖示就在這裡指定
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FastDaytradeAssistant'
)
