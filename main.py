"""Rob-Run Resolution Tool — entry point."""
from __future__ import annotations

import ctypes
import logging
import sys
from logging.handlers import RotatingFileHandler

if sys.platform != "win32":
    sys.exit("This tool only runs on Windows.")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

import config
from config import APP_ID, APP_NAME, APP_VERSION, ConfigStore
from ui import theme
from ui.controller import Controller
from ui.main_window import MainWindow, QtLogBridge
from ui.widgets import app_icon

INSTANCE_KEY = f"{APP_ID}-single-instance"


def setup_logging(bridge: QtLogBridge) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(config.LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(fh)
    root.addHandler(bridge.handler)
    if sys.stderr:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(sh)

    def excepthook(kind, value, tb):
        logging.getLogger("crash").critical("Unhandled exception", exc_info=(kind, value, tb))

    sys.excepthook = excepthook


def already_running() -> bool:
    """If another instance is up, ask it to show itself and return True."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main() -> int:
    # Own taskbar identity, so Windows shows our icon instead of python.exe's when run from source.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())

    if already_running():
        return 0

    bridge = QtLogBridge()
    setup_logging(bridge)
    log = logging.getLogger("main")
    log.info("%s %s starting", APP_NAME, APP_VERSION)

    font = QFont(theme.BODY_FAMILY)
    font.setPixelSize(13)
    app.setFont(font)
    app.setStyleSheet(theme.STYLESHEET)

    store = ConfigStore()
    controller = Controller(store)
    controller.startup_recovery()
    window = MainWindow(controller, bridge)

    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_KEY)
    server.listen(INSTANCE_KEY)

    def on_connection():
        conn = server.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(300)
            window.bring_to_front()
            conn.close()

    server.newConnection.connect(on_connection)
    app.aboutToQuit.connect(window.quit)

    if "--minimized" not in sys.argv:
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
