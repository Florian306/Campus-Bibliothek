# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# Collect PySide6 modules, keeping WebEngine/Quick/Qml and filtering only truly unused bloated modules
tmp_ret = collect_all('PySide6')
filtered_datas = [d for d in tmp_ret[0] if not any(x in d[0].lower() for x in ['translations', '3d', 'designer', 'multimedia', 'bluetooth', 'sensors', 'positioning'])]
filtered_binaries = [b for b in tmp_ret[1] if not any(x in b[0].lower() for x in ['3d', 'designer', 'multimedia', 'bluetooth', 'sensors', 'positioning', 'location', 'nfc', 'serialport', 'spatialaudio', 'scxml'])]
filtered_hidden = [h for h in tmp_ret[2] if not any(x in h for x in ['Qt3D', 'QtDesigner', 'QtMultimedia', 'QtBluetooth', 'QtSensors', 'QtPositioning', 'QtLocation', 'QtNfc', 'QtSerialPort'])]
datas += filtered_datas
binaries += filtered_binaries
hiddenimports += filtered_hidden

tmp_ret = collect_all('pymupdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

try:
    tmp_ret = collect_all('pypdf')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

try:
    tmp_ret = collect_all('google.genai')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

try:
    tmp_ret = collect_all('curl_cffi')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

try:
    tmp_ret = collect_all('matplotlib')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

hiddenimports += [
    'ui.qt_app',
    'ui.qt.theme',
    'ui.qt.icons',
    'ui.qt.latex_renderer',
    'unittest',
    'pyparsing',
    'matplotlib',
    'matplotlib.figure',
    'matplotlib.backends.backend_agg',
    'matplotlib.mathtext',
    'ui.qt.splash',
    'ui.qt.main_window',
    'PySide6.QtWebEngineWidgets',
    'dateutil.rrule',
    'PySide6.QtWebEngineCore',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtQml',
    'ui.qt.views.catalog_view',
    'ui.qt.views.desk_view',
    'ui.qt.views.research_view',
    'ui.qt.views.textbook_search_view',
    'ui.qt.views.academic_web_view',
    'ui.qt.views.radar_view',
    'ui.qt.views.jarvis_view',
    'ui.qt.views.sync_view',
    'ui.qt.views.exam_studio_view',
    'ai.textbook_search',
    'core.calendar_service',
    'core.rss_news_service',
    'core.mail_service',
    'ai.jarvis_briefing',
    'ai.academic_web_search',
    'ui.qt.components.book_card',
    'ui.qt.components.category_chips',
    'ui.qt.dialogs.quick_look',
    'ui.qt.dialogs.pdf_extract_dialog',
    'ui.qt.dialogs.study_plan_dialog',
    'ui.qt.dialogs.tutor_dialog',
    'ui.qt.dialogs.pdf_reader_dialog',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'core.config',
    'core.github_sync',
    'core.update_checker',
    'core.library_db',
    'core.models',
    'core.cache_manager',
    'core.cover_manager',
    'core.file_processor',
    'core.memory',
    'core.delta_scanner',
    'core.pdf_tools',
    'core.citations',
    'core.duplicate_finder',
    'ai.book_pairing',
    'ai.tutor_engine',
    'ai.categories',
    'ai.classifier',
    'ai.curated_papers',
    'ai.doi_resolver',
    'ai.edition_checker',
    'ai.gemini_client',
    'ai.isbn_lookup',
    'ai.ollama_client',
    'ai.paper_search',
    'ai.daily_paper',
    'ai.pdf_extractor',
    'ai.pipeline',
    'ai.sanity',
    'ai.summary_generator',
    'ai.validator',
    'ai.study_planner',
    'ai.worksheet_generator',
    'reportlab',
    'reportlab.lib',
    'reportlab.lib.colors',
    'reportlab.lib.styles',
    'reportlab.lib.units',
    'reportlab.platypus',
    'reportlab.pdfgen',
]

excludes = [
    'PySide6.QtWebEngineQuick',
    'PySide6.QtQuick3D',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic',
    'PySide6.Qt3DAnimation',
    'PySide6.Qt3DExtras',
    'PySide6.QtDesigner',
    'PySide6.QtHelp',
    'PySide6.QtTest',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtBluetooth',
    'PySide6.QtSensors',
    'PySide6.QtPositioning',
    'PySide6.QtLocation',
    'PySide6.QtSerialPort',
    'PySide6.QtNfc',
    'PySide6.QtRemoteObjects',
    'PySide6.QtSpatialAudio',
    'PySide6.QtScxml',
    'PySide6.QtStateMachine',
    'scipy',
]

datas += [('app_icon.ico', '.'), ('app_icon.png', '.')]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Buchsortierer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
)
