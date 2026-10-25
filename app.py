"""Visual2Craft Qt Quick launcher.

UI: PySide6 / QML. Reconstructor: original Visual2Craft 9f035bee Python core.
Never import the former Tkinter interface in the default application.
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
from pathlib import Path
import sys


def _dark_windows_caption(qt_window):
    """Request the system-native dark titlebar; no custom resize frame."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        hwnd = int(qt_window.winId())
        dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 20,
                                  ctypes.byref(on), ctypes.sizeof(on))
        # Windows COLORREF ordering is 0x00BBGGRR.
        caption = ctypes.c_uint(0x00120D08)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 35,
                                  ctypes.byref(caption), ctypes.sizeof(caption))
    except (AttributeError, OSError, ValueError):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description='Visual2Craft — Qt Quick desktop studio')
    parser.add_argument('--video', help='Preselect a construction video')
    parser.add_argument('--out', help='Preselect output ZIP path')
    parser.add_argument('--check-ui', action='store_true', help='Load and validate QML, then exit (no model request)')
    options = parser.parse_args(argv)

    try:
        from PySide6.QtCore import QCoreApplication, QUrl
        from PySide6.QtQml import QQmlApplicationEngine
    except ImportError as exc:
        raise SystemExit('PySide6 is missing. Run START_WINDOWS.bat or: python -m pip install -r requirements.txt') from exc

    from backend_bridge import StudioBridge

    # QApplication is not needed for Qt Quick; native QFileDialog/QMessageBox use
    # QWidget-based dialogs, so use QApplication instead.
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setOrganizationName('Visual2Craft')
    QCoreApplication.setApplicationName('Visual2Craft')
    app = QApplication(sys.argv[:1])
    app.setApplicationDisplayName('Visual2Craft')
    bridge = StudioBridge(video=options.video, output=options.out)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('studio', bridge)
    qml = Path(__file__).resolve().parent / 'qml' / 'Main.qml'
    errors = []
    engine.warnings.connect(lambda warnings: errors.extend(map(str, warnings)))
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        for error in errors:
            print(error, file=sys.stderr)
        raise SystemExit('Unable to initialize Qt Quick window; see QML errors above.')
    app.aboutToQuit.connect(bridge.shutdown)
    if not options.check_ui:
        _dark_windows_caption(engine.rootObjects()[0])
        if os.name == 'nt':
            engine.rootObjects()[0].showMaximized()
    if options.check_ui:
        print('Qt Quick QML loaded successfully')
        bridge.shutdown()
        engine.clearComponentCache()
        return 0
    return app.exec()


if __name__ == '__main__':
    mp.freeze_support()
    sys.exit(main())
