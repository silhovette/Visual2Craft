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
        # Windows COLORREF ordering is 0x00BBGGRR. Keep the native titlebar
        # black with white text while retaining the normal window frame.
        border = ctypes.c_uint(0x00000000)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 34,
                                  ctypes.byref(border), ctypes.sizeof(border))
        caption = ctypes.c_uint(0x00000000)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 35,
                                  ctypes.byref(caption), ctypes.sizeof(caption))
        text = ctypes.c_uint(0x00FFFFFF)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 36,
                                  ctypes.byref(text), ctypes.sizeof(text))
    except (AttributeError, OSError, ValueError):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description='Visual2Craft — Qt Quick desktop studio')
    parser.add_argument('--video', help='Preselect a construction video')
    parser.add_argument('--out', help='Preselect output ZIP path')
    parser.add_argument('--check-ui', action='store_true', help='Load and validate QML, then exit (no model request)')
    options = parser.parse_args(argv)

    # The Windows native style ignores custom QML background/content delegates,
    # which makes hovered/focused buttons fall back to the bright system palette.
    # Use a delegate-based style so StudioButton owns every interaction color.
    os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
    try:
        from PySide6.QtCore import QCoreApplication, QTimer, QUrl
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtQml import QQmlApplicationEngine
    except ImportError as exc:
        raise SystemExit('PySide6 is missing. Run START_WINDOWS.bat or: python -m pip install -r requirements.txt') from exc

    from core.backend_bridge import StudioBridge

    # QApplication is not needed for Qt Quick; native QFileDialog/QMessageBox use
    # QWidget-based dialogs, so use QApplication instead.
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setOrganizationName('Visual2Craft')
    QCoreApplication.setApplicationName('Visual2Craft')
    app = QApplication(sys.argv[:1])
    app.setApplicationDisplayName('Visual2Craft')
    # Set the native Qt palette before any window is created.  Without this,
    # Windows can briefly paint the hidden QQuickWindow with its default white
    # palette while the first black QML frame is being composed.
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor('#000000'))
    palette.setColor(QPalette.ColorRole.Base, QColor('#000000'))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor('#000000'))
    app.setPalette(palette)
    bridge = StudioBridge(video=options.video, output=options.out)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('studio', bridge)
    engine.rootContext().setContextProperty('blockGeometry', bridge.blockGeometry)
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
        window = engine.rootObjects()[0]
        window.setColor(QColor('#000000'))
        # Keep the native surface invisible until the compositor has produced
        # its first frame. The QML splash is already black during this handoff.
        window.setOpacity(0.0)
        _dark_windows_caption(window)
        # Maximize the normal framed window while hidden, then expose the first
        # frame once. This keeps the titlebar and avoids opening as a small window.
        window.showMaximized()
        QTimer.singleShot(50, lambda: window.setOpacity(1.0))
    if options.check_ui:
        print('Qt Quick QML loaded successfully')
        bridge.shutdown()
        engine.clearComponentCache()
        return 0
    return app.exec()


if __name__ == '__main__':
    mp.freeze_support()
    sys.exit(main())
