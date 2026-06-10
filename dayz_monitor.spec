# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for DayZ News Monitor Bot with Desktop GUI.
Entry point: gui_desktop.py (starts bot + desktop window).
"""

import sys
from pathlib import Path

block_cipher = None

PROJECT_DIR = Path(SPECPATH)

# All Python modules in the project
a = Analysis(
    ['gui_desktop.py'],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=[
        # Include config example so user knows the format
        ('config.example.json', '.'),
        # Include icon
        ('icon.ico', '.'),
    ],
    hiddenimports=[
        # Project modules (PyInstaller can miss local imports)
        'bot',
        'logger',
        'database',
        'ai_analyzer',
        'deduplicator',
        'publisher',
        'scheduler',
        'discord_monitor',
        'telegram_monitor',
        'vk_monitor',
        'website_monitor',
        'web_app_integration',
        'gui_desktop',
        # Third-party packages that need explicit declaration
        'aiohttp',
        'aiosqlite',
        'aiogram',
        'apscheduler',
        'telethon',
        'feedparser',
        'bs4',
        'lxml',
        'lxml._elementpath',
        'lxml.etree',
        'numpy',
        'customtkinter',
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        'discord',
        'discord.types',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        'certifi',
        'charset_normalizer',
        'h11',
        'idna',
        'sniffio',
        'pydantic',
        'pydantic_core',
        'typing_extensions',
        'aiogram.client',
        'aiogram.client.default',
        'aiogram.enums',
        'aiogram.fsm',
        'aiogram.fsm.strategy',
        'aiogram.fsm.storage',
        'aiogram.fsm.storage.memory',
        'aiogram.methods',
        'aiogram.types',
        'telethon.sync',
        'telethon.tl',
        'telethon.tl.types',
        'telethon.tl.functions',
        'apscheduler.schedulers.asyncio',
        'apscheduler.triggers.interval',
        'apscheduler.triggers.cron',
        'apscheduler.triggers.date',
        'apscheduler.executors.asyncio',
        'apscheduler.jobstores.memory',
        'uvloop',
        'multidict',
        'yarl',
        'attrdict',
        'aiofiles',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'PIL',
        'scipy',
        'pandas',
        'notebook',
        'IPython',
        'jupyter',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'tkinter.test',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DayZ Monitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DayZ Monitor',
)
