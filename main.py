"""Stash — every app, game and tool on your PC in one fast, beautiful library.

Run:  python main.py            (normal)
      python main.py --rescan   (force a full rescan on start)
"""
from __future__ import annotations

import logging
import os
import sys

# Make "core" / "ui" importable no matter where we're launched from (also inside a frozen exe).
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

INSTANCE_KEY = "stash-single-instance-v1"


def _dark_palette() -> QPalette:
    from ui import theme
    pal = QPalette()
    roles = {
        QPalette.Window: theme.BG, QPalette.WindowText: theme.TEXT, QPalette.Base: theme.BG,
        QPalette.AlternateBase: theme.ROW_ALT, QPalette.Text: theme.TEXT, QPalette.Button: theme.CARD,
        QPalette.ButtonText: theme.TEXT, QPalette.Highlight: theme.ACCENT, QPalette.HighlightedText: "#FFFFFF",
        QPalette.ToolTipBase: theme.CARD, QPalette.ToolTipText: theme.TEXT, QPalette.PlaceholderText: theme.TEXT2,
        QPalette.Link: theme.ACCENT,
    }
    for role, col in roles.items():
        pal.setColor(role, QColor(col))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#5A5A5E"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5A5A5E"))
    return pal


def _already_running() -> bool:
    """If another Stash is running, ask it to come to the front and exit."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(250):
        sock.write(b"show")
        sock.waitForBytesWritten(250)
        sock.disconnectFromServer()
        return True
    return False


def main() -> int:
    logging.basicConfig(level=os.environ.get("STASH_LOG", "WARNING"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QCoreApplication.setOrganizationName("Stash")
    QCoreApplication.setApplicationName("Stash")

    from ui import platform_win
    platform_win.set_app_id()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)  # tray keeps us alive; MainWindow quits explicitly
    if _already_running():
        return 0

    from ui import theme
    from ui.icons import draw_logo
    from ui.window import MainWindow

    app.setPalette(_dark_palette())
    app.setFont(theme.font(13))
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(QIcon(draw_logo(256)))

    win = MainWindow()

    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_KEY)
    server.listen(INSTANCE_KEY)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), win.show_and_raise()))

    # --minimized (used by the "Start on login" entry): start quietly in the tray when one exists.
    if not ("--minimized" in sys.argv and getattr(win, "tray", None) is not None):
        win.show()
    win.load_initial()
    if "--rescan" in sys.argv and win.model.total():
        win.rescan()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
