from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from installer.common import (
    app_icon,
    apply_native_window_icons,
    bring_widget_to_front,
    disable_native_window_rounding,
    is_admin,
    perform_uninstall,
    relaunch_with_elevation,
    resolve_install_dir,
    set_windows_app_id,
    tr,
    uninstaller_log,
)

THEME = """
QMainWindow, QWidget#Root {
  background: transparent;
  color: #edf1f8;
  font-size: 12px;
}
QWidget#Chrome {
  background: #14161f;
  border: 1px solid rgba(180, 154, 241, 0.10);
  border-radius: 12px;
}
QWidget#TitleBar {
  background: #171a24;
  border-bottom: none;
}
QLabel#Brand {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.02em;
}
QLabel#BrandMeta {
  color: #7a8496;
  font-size: 11px;
}
QLabel#Title {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
QLabel#Lead {
  color: #a7b0c0;
  font-size: 12px;
}
QLabel#Mute {
  color: #7a8496;
  font-size: 11px;
}
QFrame#StepDot {
  background: rgba(255,255,255,0.08);
  border-radius: 1px;
  min-height: 2px;
  max-height: 2px;
}
QFrame#StepDot[state="active"] { background: #b49af1; }
QFrame#StepDot[state="done"] { background: rgba(180, 154, 241, 0.4); }
QWidget#Footer {
  background: #171a24;
  border-top: none;
}
QPushButton {
  min-width: 96px;
  min-height: 36px;
  padding: 0 16px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: #1b1f2b;
  color: #edf1f8;
  font-weight: 600;
}
QPushButton:hover { background: #222736; }
QPushButton#primary {
  background: #b49af1;
  border: 1px solid transparent;
  color: #120f1a;
}
QPushButton#danger {
  background: rgba(229, 121, 121, 0.20);
  border: 1px solid transparent;
  color: #ffffff;
}
QPushButton#danger:hover { background: rgba(229, 121, 121, 0.30); }
QPushButton:disabled { opacity: 0.42; }
QToolButton {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 10px;
  color: #a7b0c0;
  background: transparent;
}
QToolButton:hover { background: rgba(255,255,255,0.07); color: #ffffff; }
QToolButton#close:hover { background: rgba(229, 121, 121, 0.28); color: #ffffff; }
QProgressBar {
  border: none;
  background: rgba(255,255,255,0.08);
  border-radius: 3px;
  max-height: 6px;
  min-height: 6px;
  text-align: center;
}
QProgressBar::chunk {
  background: #b49af1;
  border-radius: 3px;
}
QLabel#DoneMark {
  background: rgba(111, 208, 160, 0.12);
  border-radius: 10px;
}
QLabel#Error {
  background: rgba(229, 121, 121, 0.10);
  border: none;
  border-radius: 10px;
  color: #ffb4b4;
  padding: 10px 12px;
}
"""


def _done_check_pixmap(size: int = 20) -> QPixmap:
    """Vector-style checkmark (no text glyph) for the completion badge."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor("#6fd0a0"))
    pen.setWidthF(max(2.0, size * 0.12))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    # Proportions match ui_assets/icons/check.svg viewBox 0..16
    s = size / 16.0
    painter.drawPolyline(
        [
            QPointF(3.2 * s, 8.6 * s),
            QPointF(5.6 * s, 11.1 * s),
            QPointF(12.8 * s, 4.9 * s),
        ]
    )
    painter.end()
    return pm


class UninstallWorker(QThread):
    progress = Signal(int, str)
    done = Signal(bool, str)

    def __init__(self, install_dir: Path) -> None:
        super().__init__()
        self.install_dir = install_dir
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            if self._cancel:
                self.done.emit(False, tr("Удаление отменено.", "Uninstall cancelled."))
                return
            perform_uninstall(
                self.install_dir,
                progress_cb=lambda value, status="": self.progress.emit(int(value), status),
            )
            if self._cancel:
                self.done.emit(False, tr("Удаление отменено.", "Uninstall cancelled."))
                return
            self.done.emit(True, "")
        except Exception as error:
            uninstaller_log("uninstall_failed", error=str(error))
            self.done.emit(False, str(error))


class TitleBar(QWidget):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(44)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 6, 0)
        row.setSpacing(8)

        icon = QLabel()
        icon.setFixedSize(18, 18)
        icon.setPixmap(app_icon().pixmap(18, 18))
        row.addWidget(icon)

        brand = QLabel("Zapret Hub")
        brand.setObjectName("Brand")
        row.addWidget(brand)
        meta = QLabel(tr("Удаление", "Uninstall"))
        meta.setObjectName("BrandMeta")
        row.addWidget(meta)
        row.addStretch(1)

        minimize = QToolButton()
        minimize.setText("–")
        minimize.clicked.connect(window.showMinimized)
        row.addWidget(minimize)
        close_btn = QToolButton()
        close_btn.setObjectName("close")
        close_btn.setText("✕")
        close_btn.clicked.connect(window.close)
        row.addWidget(close_btn)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mousePressEvent(event)


class UninstallerWindow(QMainWindow):
    def __init__(self, install_dir: Path) -> None:
        super().__init__()
        self.install_dir = install_dir
        self.worker: UninstallWorker | None = None
        self.setWindowTitle(tr("Zapret Hub — Удаление", "Zapret Hub — Uninstall"))
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(560, 420)
        self.setWindowIcon(app_icon())
        self.setStyleSheet(THEME)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)

        chrome = QWidget()
        chrome.setObjectName("Chrome")
        outer.addWidget(chrome)
        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)
        chrome_layout.addWidget(TitleBar(self))

        self.stack = QStackedWidget()
        chrome_layout.addWidget(self.stack, 1)

        self.page_confirm = self._build_confirm_page()
        self.page_progress = self._build_progress_page()
        self.page_done = self._build_done_page()
        self.stack.addWidget(self.page_confirm)
        self.stack.addWidget(self.page_progress)
        self.stack.addWidget(self.page_done)
        self._set_steps(0)

    def _steps_bar(self) -> tuple[QWidget, list[QFrame]]:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        dots: list[QFrame] = []
        for _ in range(3):
            dot = QFrame()
            dot.setObjectName("StepDot")
            dot.setProperty("state", "")
            dots.append(dot)
            row.addWidget(dot, 1)
        return wrap, dots

    def _set_steps(self, active: int) -> None:
        for index, dot in enumerate(self._all_dots):
            state = "done" if index < active else "active" if index == active else ""
            dot.setProperty("state", state)
            dot.style().unpolish(dot)
            dot.style().polish(dot)

    def _footer(self, *buttons: QPushButton) -> QWidget:
        footer = QWidget()
        footer.setObjectName("Footer")
        footer.setFixedHeight(56)
        row = QHBoxLayout(footer)
        row.setContentsMargins(14, 0, 14, 0)
        row.addStretch(1)
        for button in buttons:
            row.addWidget(button)
        return footer

    def _build_confirm_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        # Tight frameless panel — avoid large horizontal gutters.
        layout.setContentsMargins(14, 14, 14, 0)
        layout.setSpacing(12)
        steps, dots = self._steps_bar()
        layout.addWidget(steps)
        title = QLabel(tr("Удалить Zapret Hub?", "Remove Zapret Hub?"))
        title.setObjectName("Title")
        layout.addWidget(title)
        lead = QLabel(
            tr(
                "Приложение, данные и ярлыки будут удалены. Отменить нельзя.",
                "The app, data, and shortcuts will be removed. This cannot be undone.",
            )
        )
        lead.setObjectName("Lead")
        lead.setWordWrap(True)
        layout.addWidget(lead)
        path = QLabel(str(self.install_dir))
        path.setObjectName("Mute")
        path.setWordWrap(True)
        layout.addWidget(path)
        self.error_label = QLabel("")
        self.error_label.setObjectName("Error")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        layout.addStretch(1)
        cancel = QPushButton(tr("Отмена", "Cancel"))
        cancel.clicked.connect(self.close)
        remove = QPushButton(tr("Удалить", "Remove"))
        remove.setObjectName("danger")
        remove.clicked.connect(self._start)
        layout.addWidget(self._footer(cancel, remove))
        self._confirm_dots = dots
        return page

    def _build_progress_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 0)
        layout.setSpacing(12)
        steps, dots = self._steps_bar()
        layout.addWidget(steps)
        title = QLabel(tr("Удаление…", "Removing…"))
        title.setObjectName("Title")
        layout.addWidget(title)
        lead = QLabel(tr("Подождите немного.", "Please wait a moment."))
        lead.setObjectName("Lead")
        lead.setWordWrap(True)
        layout.addWidget(lead)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        meta = QHBoxLayout()
        self.status_label = QLabel(tr("Подготовка…", "Preparing…"))
        self.status_label.setObjectName("Lead")
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("Mute")
        meta.addWidget(self.status_label, 1)
        meta.addWidget(self.percent_label)
        layout.addLayout(meta)
        layout.addStretch(1)
        waiting = QPushButton(tr("Удаление…", "Removing…"))
        waiting.setEnabled(False)
        layout.addWidget(self._footer(waiting))
        self._progress_dots = dots
        return page

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 0)
        layout.setSpacing(12)
        steps, dots = self._steps_bar()
        layout.addWidget(steps)
        mark = QLabel()
        mark.setObjectName("DoneMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(40, 40)
        mark.setPixmap(_done_check_pixmap(20))
        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignLeft)
        title = QLabel(tr("Zapret Hub удалён", "Zapret Hub removed"))
        title.setObjectName("Title")
        layout.addWidget(title)
        lead = QLabel(
            tr(
                "Приложение удалено с этого компьютера.",
                "The app has been removed from this computer.",
            )
        )
        lead.setObjectName("Lead")
        lead.setWordWrap(True)
        layout.addWidget(lead)
        layout.addStretch(1)
        close_btn = QPushButton(tr("Закрыть", "Close"))
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(self.close)
        layout.addWidget(self._footer(close_btn))
        self._done_dots = dots
        return page

    @property
    def _all_dots(self) -> list[QFrame]:
        if self.stack.currentWidget() is self.page_progress:
            return self._progress_dots
        if self.stack.currentWidget() is self.page_done:
            return self._done_dots
        return self._confirm_dots

    def _start(self) -> None:
        self.error_label.hide()
        self.stack.setCurrentWidget(self.page_progress)
        self._set_steps(1)
        self.worker = UninstallWorker(self.install_dir)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_progress(self, value: int, status: str) -> None:
        self.progress.setValue(max(0, min(100, int(value))))
        self.percent_label.setText(f"{int(value)}%")
        if status:
            self.status_label.setText(status)

    def _on_done(self, ok: bool, error: str) -> None:
        if not ok:
            if error and ("отменен" in error.lower() or "cancelled" in error.lower()):
                self.close()
                return
            self.error_label.setText(error)
            self.error_label.show()
            self.stack.setCurrentWidget(self.page_confirm)
            self._set_steps(0)
            return
        self.stack.setCurrentWidget(self.page_done)
        self._set_steps(2)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        disable_native_window_rounding(int(self.winId()))
        apply_native_window_icons(self)
        bring_widget_to_front(self)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        worker = self.worker
        if worker is not None:
            try:
                worker.request_cancel()
            except Exception:
                pass
            if worker.isRunning():
                if not worker.wait(2000):
                    worker.terminate()
                    worker.wait(1000)
            self.worker = None
        super().closeEvent(event)


def _parse_install_dir(argv: list[str]) -> Path | None:
    if "--install-dir" not in argv:
        return None
    try:
        return Path(argv[argv.index("--install-dir") + 1])
    except Exception:
        return None


def main() -> int:
    set_windows_app_id("goshkow.ZapretHub.Uninstaller.3.0.2")
    args = [arg for arg in sys.argv[1:] if arg != "--uninstall"]
    if not is_admin():
        relaunch_with_elevation(args or ["--elevated-ui"])
        return 0

    install_dir = resolve_install_dir(_parse_install_dir(sys.argv))
    if "--silent" in sys.argv:
        perform_uninstall(install_dir)
        return 0

    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    font = QFont("Segoe UI")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    window = UninstallerWindow(install_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
