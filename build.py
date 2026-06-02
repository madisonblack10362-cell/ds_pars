"""
DayZ News Monitor — сборка .exe для Windows
==========================================
Запустить:  build.bat  (двойной клик)
Или:        python build.py
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path

REQUIRED = [
    "aiohttp>=3.9.5",
    "aiogram>=3.4.1",
    "aiosqlite>=0.20.0",
    "telethon>=1.36.0",
    "discord.py-self>=2.0.0",
    "apscheduler>=3.10.4",
    "beautifulsoup4>=4.12.3",
    "lxml>=5.2.2",
    "feedparser>=6.0.11",
    "openai>=1.30.0",
    "numpy>=1.26.4",
    "aiofiles>=23.2.1",
    "customtkinter>=5.2.0",
    "httpx>=0.27.0",
    "pyinstaller>=6.0.0",
]

SPEC_TEMPLATE = r"""
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
block_cipher = None
PROJECT_DIR = Path(SPECPATH)

a = Analysis(
    ['bot.py'],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=[
{datas_lines}
    ],
    hiddenimports=[
        'bot', 'logger', 'database', 'ai_analyzer', 'deduplicator',
        'publisher', 'scheduler', 'discord_monitor', 'telegram_monitor',
        'vk_monitor', 'website_monitor', 'web_app_integration', 'gui_desktop',
        'aiohttp', 'aiosqlite', 'aiogram', 'apscheduler', 'telethon',
        'feedparser', 'bs4', 'lxml', 'lxml._elementpath', 'lxml.etree',
        'numpy', 'customtkinter', 'httpx', 'httpx._transports',
        'httpx._transports.default', 'discord', 'discord.types',
        'anyio', 'anyio._backends', 'anyio._backends._asyncio',
        'certifi', 'charset_normalizer', 'h11', 'idna', 'sniffio',
        'pydantic', 'pydantic_core', 'typing_extensions',
        'aiogram.client', 'aiogram.client.default', 'aiogram.enums',
        'aiogram.fsm', 'aiogram.fsm.strategy', 'aiogram.fsm.storage',
        'aiogram.fsm.storage.memory', 'aiogram.methods', 'aiogram.types',
        'telethon.sync', 'telethon.tl', 'telethon.tl.types',
        'telethon.tl.functions', 'apscheduler.schedulers.asyncio',
        'apscheduler.triggers.interval', 'apscheduler.triggers.cron',
        'apscheduler.triggers.date', 'apscheduler.executors.asyncio',
        'apscheduler.jobstores.memory', 'multidict', 'yarl', 'aiofiles',
        'uvloop',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['matplotlib', 'PIL', 'scipy', 'pandas', 'notebook',
              'IPython', 'jupyter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
              'tkinter.test'],
    noarchive=False, optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='DayZ Monitor', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=True,
    console=False,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='DayZ Monitor',
)
"""


def run(cmd, **kw):
    print(f"\n>>> {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    return subprocess.run(cmd, **kw)


def main():
    os.chdir(Path(__file__).parent)

    # 1) Установка зависимостей (build.bat уже установил, но проверим)
    print("=" * 60)
    print("  Проверка/установка зависимостей...")
    print("=" * 60)
    run([sys.executable, "-m", "pip", "install", *REQUIRED, "--quiet"])

    # 2) Собираем datas — только те файлы которые реально существуют
    datas_lines = []
    for fname in ("config.example.json", "icon.ico"):
        if Path(fname).exists():
            datas_lines.append(f"        ('{fname}', '.'),")
    datas_str = '\n'.join(datas_lines) if datas_lines else ''

    spec_content = SPEC_TEMPLATE.replace("{datas_lines}", datas_str)
    spec_path = Path("build/dayz_monitor_win.spec")
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(spec_content.strip(), encoding="utf-8")
    print(f"\n  Spec записан: {spec_path} (datas: {len(datas_lines)} файлов)")

    # 3) Сборка
    print("\n" + "=" * 60)
    print("  Сборка .exe (PyInstaller)...")
    print("=" * 60)
    result = run([
        sys.executable, "-m", "PyInstaller",
        str(spec_path),
        "--distpath", "dist",
        "--workpath", "build",
        "--clean", "-y",
    ])
    if result.returncode != 0:
        print("\n  ОШИБКА СБОРКИ!")
        sys.exit(1)

    # 4) Копируем config если нет
    dist_dir = Path("dist/DayZ Monitor")
    cfg = dist_dir / "config.json"
    if not cfg.exists():
        for src in ("config.example.json", "config.json"):
            if Path(src).exists():
                shutil.copy(src, cfg)
                print(f"\n  {src} скопирован в {dist_dir}")
                break
        else:
            print(f"\n  [!] config.json не найден — создай его вручную в {dist_dir}")

    print("\n" + "=" * 60)
    print("  ГОТОВО!")
    print("=" * 60)
    print(f"""
  .exe собран в:
    {dist_dir.absolute()}

  Для запуска:
    1. Отредактируй config.json (вставь токены)
    2. Запусти DayZ Monitor.exe

  Для распространения:
    Зипни всю папку "DayZ Monitor" из dist/
""")


if __name__ == "__main__":
    main()
