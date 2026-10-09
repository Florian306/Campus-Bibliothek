# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# Collect PySide6 modules, keeping WebEngine/Quick/Qml and filtering only truly unused bloated modules
tmp_ret = collect_all('PySide6')
filtered_datas = [d for d in tmp_ret[0] if not any(x in d[0].lower() for x in ['translations', '3d', 'designer', 'multimedia', 'bluetooth', 'sensors', 'positioning', 'charts', 'graphs', 'datavisualization'])]
filtered_binaries = [b for b in tmp_ret[1] if not any(x in b[0].lower() for x in ['3d', 'designer', 'multimedia', 'bluetooth', 'sensors', 'positioning', 'location', 'nfc', 'serialport', 'spatialaudio', 'scxml', 'charts', 'graphs', 'datavisualization', 'httpserver', 'serialbus'])]
filtered_hidden = [h for h in tmp_ret[2] if not any(x in h for x in ['Qt3D', 'QtDesigner', 'QtMultimedia', 'QtBluetooth', 'QtSensors', 'QtPositioning', 'QtLocation', 'QtNfc', 'QtSerialPort', 'QtCharts', 'QtDataVisualization', 'QtGraphs', 'QtHttpServer', 'QtSerialBus', 'QtAxContainer'])]
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
    datas += [d for d in tmp_ret[0] if 'tests' not in d[0].replace('\\', '/').split('/')]
    binaries += tmp_ret[1]
    hiddenimports += [h for h in tmp_ret[2] if 'tests' not in h]
except Exception:
    pass

try:
    tmp_ret = collect_all('curl_cffi')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass

try:
    tmp_ret = collect_all('matplotlib')
    datas += [d for d in tmp_ret[0] if 'tests' not in d[0].replace('\\', '/').split('/')]
    binaries += tmp_ret[1]
    hiddenimports += [h for h in tmp_ret[2] if not any(x in h for x in ['tests', 'testing', 'sphinxext', 'backend_gtk', 'backend_wx', 'backend_tk', 'backend_cairo', 'backend_qt5'])]
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
    # Unused PySide6 components
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
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtGraphs',
    'PySide6.QtGraphsWidgets',
    'PySide6.QtHttpServer',
    'PySide6.QtSerialBus',
    'PySide6.QtAxContainer',
    'PySide6.scripts',
    
    # Heavy scientific packages not required
    'scipy',
    'pandas',
    
    # Test suites & development modules (removes hundreds of useless files)
    'google.genai.tests',
    'matplotlib.tests',
    'matplotlib.testing',
    'matplotlib.sphinxext',
    'unittest.test',
    'test',
    'tests',
    'pytest',
    'tkinter.test',
    'PIL.tests',
    
    # Unused matplotlib backends (Campus-Bibliothek uses Agg for offscreen rendering)
    'matplotlib.backends.backend_gtk3',
    'matplotlib.backends.backend_gtk3agg',
    'matplotlib.backends.backend_gtk3cairo',
    'matplotlib.backends.backend_gtk4',
    'matplotlib.backends.backend_gtk4agg',
    'matplotlib.backends.backend_gtk4cairo',
    'matplotlib.backends.backend_macosx',
    'matplotlib.backends.backend_nbagg',
    'matplotlib.backends.backend_pgf',
    'matplotlib.backends.backend_qt5',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_qt5cairo',
    'matplotlib.backends.backend_tkagg',
    'matplotlib.backends.backend_tkcairo',
    'matplotlib.backends.backend_webagg',
    'matplotlib.backends.backend_wx',
    'matplotlib.backends.backend_wxagg',
    'matplotlib.backends.backend_wxcairo',
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
    [],
    exclude_binaries=True,
    name='Buchsortierer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
)

# Filter collected binaries and data files to eliminate test suites, cache artifacts, and unneeded docs
clean_datas = []
for dest, src, typ in a.datas:
    dest_lower = dest.lower().replace('\\', '/')
    # Drop tests, docs, sphinx and sample assets
    if any(x in dest_lower for x in [
        '/tests/', '/test/', 'google/genai/tests', 'matplotlib/tests',
        'pip/', 'setuptools/', '.dist-info/licenses',
    ]):
        continue
    clean_datas.append((dest, src, typ))

clean_binaries = []
for dest, src, typ in a.binaries:
    dest_lower = dest.lower().replace('\\', '/')
    # Drop unused dynamic libraries (e.g. database drivers for Firebird/Mimer/Oracle not used by SQLite)
    if any(x in dest_lower for x in ['qsqlibase.dll', 'qsqlmimer.dll', 'qsqloci.dll']):
        continue
    clean_binaries.append((dest, src, typ))

coll = COLLECT(
    exe,
    clean_binaries,
    clean_datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Buchsortierer',
)

