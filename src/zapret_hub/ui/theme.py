from __future__ import annotations


LIGHT_THEMES = {"light", "light blue"}


def is_light_theme(theme: str) -> bool:
    return theme in LIGHT_THEMES


def build_stylesheet(theme: str, chevron_icon: str = "", check_icon: str = "") -> str:
    night = """
    QWidget {
        background: #0f1420;
        color: #d9e0f0;
        font-family: "Inter";
        font-size: 10pt;
    }
    #WindowShell {
        background: transparent;
    }
    QStackedWidget, QStackedWidget > QWidget, QWidget#PagesShell, QStackedWidget#PagesStack {
        background: transparent;
    }
    QWidget[class="pageRoot"], QWidget[class="pageCanvas"] {
        background: transparent;
    }
    QLabel {
        background: transparent;
    }
    #RootFrame {
        background: #101725;
        border: 1px solid #24304a;
        border-radius: 16px;
    }
    #TitleBar {
        background: #101726;
        border: none;
        border-top-left-radius: 16px;
        border-top-right-radius: 16px;
        font-family: "JetBrains Sans";
    }
    #Sidebar {
        background: #101726;
        border-bottom-left-radius: 16px;
    }
    #Content {
        background: transparent;
        border: none;
    }
    #ContentSurface {
        background: qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #0d1320, stop:0.62 #101827, stop:1 #172339);
        border-top: 1px solid #24304a;
        border-left: 1px solid #24304a;
        border-top-left-radius: 18px;
        border-top-right-radius: 0px;
        border-bottom-left-radius: 0px;
        border-bottom-right-radius: 16px;
    }
    QDialog#AppDialogWindow {
        background: transparent;
        border: none;
    }
    #DialogRoot {
        background: #151f33;
        border: 1px solid #243550;
        border-radius: 12px;
    }
    #DialogTitleBar {
        background: transparent;
        border: none;
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
    }
    #DialogBody {
        background: transparent;
    }
    #SettingsScroll, #SettingsCanvas, #SettingsScroll QWidget#qt_scrollarea_viewport {
        background: transparent;
        border: none;
    }
    QFrame[class="settingsSection"] {
        background: #141f32;
        border: 1px solid #243550;
        border-radius: 14px;
    }
    #LoadingOverlay {
        background: rgba(9, 13, 22, 0.42);
    }
    #LoadingCard {
        background: #141f32;
        border: 1px solid #2d456d;
        border-radius: 16px;
    }
    QFrame[class="card"] {
        background: qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #131d30, stop:0.68 #162238, stop:1 #1a2842);
        border: 1px solid #243550;
        border-radius: 16px;
    }
    QFrame[class="modHero"] {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #17253d, stop:1 #131d30);
        border: 1px solid #2a436a;
        border-radius: 16px;
    }
    QFrame[class="modCard"] {
        background: #141f32;
        border: 1px solid #284061;
        border-radius: 16px;
    }
    QFrame#NotificationsPopup {
        background: #141f32;
        border: 1px solid #304463;
        border-radius: 14px;
    }
    QFrame[class="notificationCard"] {
        background: #17233a;
        border: 1px solid #2e4269;
        border-radius: 12px;
    }
    QFrame[class="notificationCard"][read="true"] {
        background: #111821;
        border: 1px solid #263241;
    }
    QScrollArea#NotificationsScroll, QWidget#NotificationsCanvas {
        background: transparent;
        border: none;
    }
    QFrame[class="modIconWrap"] {
        background: #1b2b45;
        border: 1px solid #35527d;
        border-radius: 16px;
    }
    QLabel[class="title"] {
        font-size: 13pt;
        font-weight: 700;
        color: #f5f7fc;
    }
    #DashboardTitle {
        padding: 0px;
        margin: 0px;
    }
    #DashboardPowerBlock {
        background: transparent;
    }
    QLabel[class="muted"] {
        color: #90a1c2;
    }
    QLabel[class="modHint"] {
        color: #a9b8d8;
    }
    QLabel[class="modState"] {
        color: #f8fbff;
        background: #21324f;
        border: 1px solid #39547d;
        border-radius: 12px;
        padding: 6px 12px;
        font-weight: 600;
    }
    QLabel[class="modState"][state="enabled"] {
        background: rgba(44, 163, 93, 0.16);
        border: 1px solid #2f8f5d;
        color: #a8efc1;
    }
    QLabel[class="modState"][state="installed"] {
        background: rgba(104, 137, 186, 0.16);
        border: 1px solid #5070a4;
        color: #d6e4ff;
    }
    QLabel[class="modState"][state="not installed"] {
        background: rgba(150, 164, 192, 0.12);
        border: 1px solid #4b617f;
        color: #bcc9df;
    }
    QLabel[class="modMeta"] {
        color: #afbdd9;
        background: #18253d;
        border: 1px solid #2b446a;
        border-radius: 12px;
        padding: 6px 12px;
    }
    #ModsSummaryChip, #ModsEnabledChip {
        border-radius: 11px;
    }
    #ModStateBadge, #ModMetaChip {
        border-radius: 12px;
    }
    QLabel[class="modBody"] {
        color: #d7e1f2;
        line-height: 1.3em;
    }
    #ModsScroll, #ModsCanvas, #ComponentsScroll, #ComponentsCanvas {
        background: transparent;
        border: none;
    }
    #ComponentsScroll QScrollBar, #ComponentsCanvas QScrollBar, #ComponentsScroll QWidget#qt_scrollarea_viewport, #ComponentsCanvas QWidget#qt_scrollarea_viewport {
        background: transparent;
        border: none;
    }
    QToolButton[class="nav"] {
        min-width: 46px;
        min-height: 46px;
        max-width: 46px;
        max-height: 46px;
        border-radius: 12px;
        border: 1px solid transparent;
        background: transparent;
    }
    QToolButton[class="nav"]:hover {
        background: #1e2a43;
        border: 1px solid #35507a;
    }
    QToolButton[class="nav"]:checked {
        background: #2a3d61;
        border: 1px solid #4f73b3;
    }
    QToolButton[class="window"] {
        min-width: 26px;
        min-height: 26px;
        max-width: 26px;
        max-height: 26px;
        border-radius: 12px;
        border: none;
        background: transparent;
        padding: 0px;
        margin: 0px;
    }
    QToolButton[class="window"][role="min"],
    QToolButton[class="window"][role="close"] {
        padding: 0px 1px 2px 0px;
    }
    QToolButton[class="window"][role="close"] {
        padding: 0px 1px 1px 0px;
    }
    QToolButton[class="window"]:hover {
        background: transparent;
    }
    QToolButton[class="window"][role="close"]:hover {
        background: rgba(170, 84, 97, 0.62);
    }
    QPushButton {
        background: #243552;
        border: 1px solid #35517f;
        border-radius: 10px;
        padding: 8px 12px;
    }
    QPushButton:hover {
        background: #243552;
    }
    QToolButton[class="action"] {
        min-width: 26px;
        min-height: 26px;
        max-width: 26px;
        max-height: 26px;
        border: none;
        border-radius: 12px;
        background: transparent;
        padding: 0;
        margin: 0;
    }
    QToolButton[class="action"]:hover {
        background: transparent;
    }
    QToolButton[class="action"]::menu-indicator {
        image: none;
        width: 0px;
        height: 0px;
    }
    QFrame[class="fileModeCard"] {
        background: qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #141e31, stop:1 #1a2942);
        border: 1px solid #2e466d;
        border-radius: 14px;
    }
    QFrame[class="fileModeCard"][hovered="true"] {
        background: qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #1a2842, stop:1 #203252);
        border: 1px solid #4f73b3;
    }
    QPushButton[class="primary"] {
        background: #5865f2;
        border-color: #6773ff;
        color: #ffffff;
        font-weight: 700;
    }
    QPushButton[class="primary"]:hover {
        background: #5865f2;
    }
    QPushButton[class="danger"] {
        background: #151f33;
        border-color: #fb5e5e;
        color: #ffd9dd;
        font-weight: 700;
    }
    QPushButton[class="danger"]:hover {
        background: #151f33;
    }
    QToolButton[class="power"] {
        min-width: 132px;
        min-height: 132px;
        max-width: 132px;
        max-height: 132px;
        border-radius: 66px;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7380ff, stop:0.48 #5f6cf7, stop:1 #4551cb);
        border: 2px solid #7b87ff;
        padding: 0px;
    }
    QToolButton[class="power"][state="off"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #324a73, stop:0.55 #283b5c, stop:1 #1d2b44);
        border: 2px solid #35517f;
    }
    QToolButton[class="power"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8591ff, stop:0.48 #6d79ff, stop:1 #505ce0);
    }
    QToolButton[class="power"][state="off"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a5685, stop:0.55 #30486f, stop:1 #223451);
    }
    QLineEdit, QComboBox, QTextEdit, QTableWidget {
        background: #111a2b;
        border: 1px solid #2f4468;
        border-radius: 10px;
        padding: 6px;
        selection-background-color: #37568a;
    }
    QCheckBox {
        background: transparent;
        spacing: 8px;
        padding: 2px 0;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border-radius: 5px;
        border: 1px solid #4a628c;
        background: transparent;
    }
    QCheckBox::indicator:unchecked:hover {
        background: rgba(83, 108, 148, 0.18);
    }
    QCheckBox::indicator:checked {
        border: 1px solid #90a5ff;
        background: #5865f2;
        __CHECK_ICON__
    }
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 22px;
        border: none;
        background: transparent;
    }
    QComboBox::down-arrow {
        width: 12px;
        height: 12px;
        __COMBO_ARROW__
    }
    QListWidget {
        background: #111a2b;
        border: 1px solid #2f4468;
        border-radius: 12px;
        padding: 8px;
        outline: none;
    }
    QListWidget::item {
        background: #17233a;
        border: 1px solid #2e4269;
        border-radius: 10px;
        padding: 10px;
        margin: 2px 0;
    }
    QListWidget::item:selected {
        background: #253c62;
        border: 1px solid #5f80bc;
    }
    QListWidget::item:hover {
        background: #203352;
    }
    QHeaderView::section {
        background: #1d2940;
        color: #dbe4f5;
        border: none;
        padding: 6px;
    }
    QScrollBar:vertical {
        background: transparent;
        border: none;
        width: 0px;
        margin: 0px;
    }
    QScrollBar::groove:vertical {
        background: transparent;
        border: none;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: transparent;
        min-height: 34px;
        border-radius: 4px;
    }
    QScrollBar::handle:vertical:hover {
        background: transparent;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
    QScrollBar:horizontal {
        background: transparent;
        border: none;
        height: 0px;
        margin: 0px;
    }
    QScrollBar::groove:horizontal {
        background: transparent;
        border: none;
        margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: transparent;
        min-width: 34px;
        border-radius: 4px;
    }
    QScrollBar::handle:horizontal:hover {
        background: transparent;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: transparent;
    }
    QListWidget#FilesList, QListWidget#FilesList::viewport,
    QListWidget#ModFilesList, QListWidget#ModFilesList::viewport {
        background: transparent;
        border: none;
    }
    QListWidget#FilesList {
        padding: 0px;
    }
    QListWidget#ModFilesList {
        padding: 4px;
        border: 1px solid #2d456d;
        border-radius: 12px;
    }
    QListWidget#FilesList::item,
    QListWidget#ModFilesList::item {
        margin: 0px 0px 8px 0px;
    }
    QListWidget#FilesList::item:selected,
    QListWidget#ModFilesList::item:selected {
        color: #d9e0f0;
    }
    QListWidget#FilesList QScrollBar:vertical,
    QListWidget#ModFilesList QScrollBar:vertical,
    QTextEdit#FileEditor QScrollBar:vertical {
        background: transparent;
        border: none;
        width: 0px;
        margin: 0px;
    }
    QListWidget#FilesList QScrollBar::handle:vertical,
    QListWidget#ModFilesList QScrollBar::handle:vertical,
    QTextEdit#FileEditor QScrollBar::handle:vertical {
        background: transparent;
        min-height: 40px;
        border-radius: 4px;
    }
    QListWidget#FilesList QScrollBar:horizontal,
    QListWidget#ModFilesList QScrollBar:horizontal,
    QTextEdit#FileEditor QScrollBar:horizontal {
        background: transparent;
        border: none;
        height: 0px;
        margin: 0px;
    }
    QListWidget#FilesList QScrollBar::handle:horizontal,
    QListWidget#ModFilesList QScrollBar::handle:horizontal,
    QTextEdit#FileEditor QScrollBar::handle:horizontal {
        background: transparent;
        min-width: 40px;
        border-radius: 4px;
    }
    QListWidget#FilesList QScrollBar::add-page:vertical,
    QListWidget#FilesList QScrollBar::sub-page:vertical,
    QListWidget#ModFilesList QScrollBar::add-page:vertical,
    QListWidget#ModFilesList QScrollBar::sub-page:vertical,
    QTextEdit#FileEditor QScrollBar::add-page:vertical,
    QTextEdit#FileEditor QScrollBar::sub-page:vertical,
    QListWidget#FilesList QScrollBar::add-page:horizontal,
    QListWidget#FilesList QScrollBar::sub-page:horizontal,
    QListWidget#ModFilesList QScrollBar::add-page:horizontal,
    QListWidget#ModFilesList QScrollBar::sub-page:horizontal,
    QTextEdit#FileEditor QScrollBar::add-page:horizontal,
    QTextEdit#FileEditor QScrollBar::sub-page:horizontal {
        background: transparent;
    }
    QListWidget#FilesList QScrollBar::groove:vertical,
    QListWidget#FilesList QScrollBar::groove:horizontal,
    QListWidget#ModFilesList QScrollBar::groove:vertical,
    QListWidget#ModFilesList QScrollBar::groove:horizontal,
    QTextEdit#FileEditor QScrollBar::groove:vertical,
    QTextEdit#FileEditor QScrollBar::groove:horizontal,
    QAbstractScrollArea::corner {
        background: transparent;
        border: none;
    }
    QMenu {
        background: #141f32;
        border: 1px solid #304463;
        border-radius: 8px;
        padding: 6px;
    }
    QMenu::item {
        padding: 7px 10px;
        border-radius: 6px;
    }
    QMenu::item:selected {
        background: #2b3f63;
    }
    """

    light = """
    QWidget {
        background: #eef2f8;
        color: #1f2a3d;
        font-family: "Inter";
        font-size: 10pt;
    }
    #WindowShell {
        background: transparent;
    }
    QStackedWidget, QStackedWidget > QWidget, QWidget#PagesShell, QStackedWidget#PagesStack {
        background: transparent;
    }
    QWidget[class="pageRoot"], QWidget[class="pageCanvas"] {
        background: transparent;
    }
    QLabel {
        background: transparent;
    }
    #RootFrame {
        background: #f3f6fd;
        border: 1px solid #d2ddeb;
        border-radius: 16px;
    }
    #TitleBar {
        background: #f3f6fd;
        border: none;
        border-top-left-radius: 16px;
        border-top-right-radius: 16px;
        font-family: "JetBrains Sans";
    }
    #Sidebar {
        background: #f3f6fd;
        border-bottom-left-radius: 16px;
    }
    #Content {
        background: transparent;
        border: none;
    }
    #ContentSurface {
        background: #f4f7fc;
        border-top: 1px solid #d2ddeb;
        border-left: 1px solid #d2ddeb;
        border-top-left-radius: 18px;
        border-top-right-radius: 0px;
        border-bottom-left-radius: 0px;
        border-bottom-right-radius: 16px;
    }
    QDialog#AppDialogWindow {
        background: transparent;
        border: none;
    }
    #DialogRoot {
        background: #ffffff;
        border: 1px solid #d2ddeb;
        border-radius: 12px;
    }
    #DialogTitleBar {
        background: transparent;
        border: none;
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
    }
    #DialogBody {
        background: transparent;
    }
    #SettingsScroll, #SettingsCanvas, #SettingsScroll QWidget#qt_scrollarea_viewport {
        background: transparent;
        border: none;
    }
    QFrame[class="settingsSection"] {
        background: #ffffff;
        border: 1px solid #eef3fa;
        border-radius: 14px;
    }
    #LoadingOverlay {
        background: rgba(228, 236, 248, 0.58);
    }
    #LoadingCard {
        background: #ffffff;
        border: 1px solid #d2ddeb;
        border-radius: 16px;
    }
    QFrame[class="card"] {
        background: #ffffff;
        border: 1px solid #d2ddeb;
        border-radius: 16px;
    }
    QFrame[class="modHero"] {
        background: #ffffff;
        border: 1px solid #cad7ea;
        border-radius: 16px;
    }
    QFrame[class="modCard"] {
        background: #ffffff;
        border: 1px solid #d6e1f0;
        border-radius: 16px;
    }
    QFrame#NotificationsPopup {
        background: #ffffff;
        border: 1px solid #c9d7eb;
        border-radius: 14px;
    }
    QFrame[class="notificationCard"] {
        background: #f8fbff;
        border: 1px solid #d3e0ef;
        border-radius: 12px;
    }
    QFrame[class="notificationCard"][read="true"] {
        background: #f1f3f6;
        border: 1px solid #d7dde6;
    }
    QScrollArea#NotificationsScroll, QWidget#NotificationsCanvas {
        background: transparent;
        border: none;
    }
    QFrame[class="modIconWrap"] {
        background: #edf3ff;
        border: 1px solid #c5d6ee;
        border-radius: 16px;
    }
    QLabel[class="title"] {
        font-size: 13pt;
        font-weight: 700;
        color: #111827;
    }
    #DashboardTitle {
        padding: 0px;
        margin: 0px;
    }
    #DashboardPowerBlock {
        background: transparent;
    }
    QLabel[class="muted"] {
        color: #64748b;
    }
    QLabel[class="modHint"] {
        color: #61708c;
    }
    QLabel[class="modState"] {
        color: #24324a;
        background: #edf3ff;
        border: 1px solid #cadaf2;
        border-radius: 12px;
        padding: 6px 12px;
        font-weight: 600;
    }
    QLabel[class="modState"][state="enabled"] {
        background: #e8f8ef;
        border: 1px solid #9ed1b3;
        color: #1f6b45;
    }
    QLabel[class="modState"][state="installed"] {
        background: #edf3ff;
        border: 1px solid #bfd2f0;
        color: #2d4b7b;
    }
    QLabel[class="modState"][state="not installed"] {
        background: #f6f8fc;
        border: 1px solid #d8e0eb;
        color: #66758d;
    }
    QLabel[class="modMeta"] {
        color: #5f708d;
        background: #f5f8ff;
        border: 1px solid #d4dff0;
        border-radius: 12px;
        padding: 6px 12px;
    }
    #ModsSummaryChip, #ModsEnabledChip {
        border-radius: 11px;
    }
    #ModStateBadge, #ModMetaChip {
        border-radius: 12px;
    }
    QLabel[class="modBody"] {
        color: #2a3648;
        line-height: 1.3em;
    }
    #ModsScroll, #ModsCanvas, #ComponentsScroll, #ComponentsCanvas {
        background: transparent;
        border: none;
    }
    #ComponentsScroll QScrollBar, #ComponentsCanvas QScrollBar, #ComponentsScroll QWidget#qt_scrollarea_viewport, #ComponentsCanvas QWidget#qt_scrollarea_viewport {
        background: transparent;
        border: none;
    }
    QToolButton[class="nav"] {
        min-width: 46px;
        min-height: 46px;
        max-width: 46px;
        max-height: 46px;
        border-radius: 12px;
        border: 1px solid transparent;
        background: transparent;
    }
    QToolButton[class="nav"]:hover {
        background: #e7efff;
        border: 1px solid #bfd2f0;
    }
    QToolButton[class="nav"]:checked {
        background: #dae7ff;
        border: 1px solid #9cb7ea;
    }
    QToolButton[class="window"] {
        min-width: 26px;
        min-height: 26px;
        max-width: 26px;
        max-height: 26px;
        border-radius: 12px;
        border: none;
        background: transparent;
        padding: 0px;
        margin: 0px;
    }
    QToolButton[class="window"][role="min"],
    QToolButton[class="window"][role="close"] {
        padding: 0px 1px 2px 0px;
    }
    QToolButton[class="window"][role="close"] {
        padding: 0px 1px 1px 0px;
    }
    QToolButton[class="window"]:hover {
        background: transparent;
    }
    QToolButton[class="window"][role="close"]:hover {
        background: rgba(189, 99, 109, 0.62);
    }
    QPushButton {
        background: #edf3ff;
        border: 1px solid #bfd2f0;
        border-radius: 10px;
        padding: 8px 12px;
    }
    QPushButton:hover {
        background: #edf3ff;
    }
    QToolButton[class="action"] {
        min-width: 26px;
        min-height: 26px;
        max-width: 26px;
        max-height: 26px;
        border: none;
        border-radius: 12px;
        background: transparent;
        padding: 0;
        margin: 0;
    }
    QToolButton[class="action"]:hover {
        background: transparent;
    }
    QToolButton[class="action"]::menu-indicator {
        image: none;
        width: 0px;
        height: 0px;
    }
    QFrame[class="fileModeCard"] {
        background: #ffffff;
        border: 1px solid #cad8ee;
        border-radius: 14px;
    }
    QFrame[class="fileModeCard"][hovered="true"] {
        background: #f2f7ff;
        border: 1px solid #8ea9df;
    }
    QPushButton[class="primary"] {
        background: #5865f2;
        border-color: #6773ff;
        color: #ffffff;
        font-weight: 700;
    }
    QPushButton[class="primary"]:hover {
        background: #5865f2;
    }
    QPushButton[class="danger"] {
        background: #ffffff;
        border-color: #fb5e5e;
        color: #bc4357;
        font-weight: 700;
    }
    QPushButton[class="danger"]:hover {
        background: #ffffff;
    }
    QToolButton[class="power"] {
        min-width: 132px;
        min-height: 132px;
        max-width: 132px;
        max-height: 132px;
        border-radius: 66px;
        background: #6471f8;
        border: 2px solid #7b87ff;
        padding: 0px;
    }
    QToolButton[class="power"][state="off"] {
        background: #e6eef9;
        border: 2px solid #bfd2f0;
    }
    QToolButton[class="power"]:hover {
        background: #7480ff;
    }
    QToolButton[class="power"][state="off"]:hover {
        background: #edf3fb;
    }
    QLineEdit, QComboBox, QTextEdit, QTableWidget {
        background: #ffffff;
        border: 1px solid #cedbea;
        border-radius: 10px;
        padding: 6px;
        selection-background-color: #bfd2f0;
    }
    QCheckBox {
        background: transparent;
        spacing: 8px;
        padding: 2px 0;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border-radius: 5px;
        border: 1px solid #9bb1d2;
        background: #ffffff;
    }
    QCheckBox::indicator:unchecked:hover {
        background: #eef4ff;
    }
    QCheckBox::indicator:checked {
        border: 1px solid #7f96db;
        background: #5865f2;
        __CHECK_ICON__
    }
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 22px;
        border: none;
        background: transparent;
    }
    QComboBox::down-arrow {
        width: 12px;
        height: 12px;
        __COMBO_ARROW__
    }
    QListWidget {
        background: #ffffff;
        border: 1px solid #cedbea;
        border-radius: 12px;
        padding: 8px;
        outline: none;
    }
    QListWidget::item {
        background: #f8fbff;
        border: 1px solid #d3e0ef;
        border-radius: 10px;
        padding: 10px;
        margin: 2px 0;
    }
    QListWidget::item:selected {
        background: #deebff;
        border: 1px solid #9cb7ea;
    }
    QListWidget::item:hover {
        background: #edf4ff;
    }
    QHeaderView::section {
        background: #edf3ff;
        color: #1f2a3d;
        border: none;
        padding: 6px;
    }
    QScrollBar:vertical {
        background: transparent;
        border: none;
        width: 0px;
        margin: 0px;
    }
    QScrollBar::groove:vertical {
        background: transparent;
        border: none;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: transparent;
        min-height: 34px;
        border-radius: 4px;
    }
    QScrollBar::handle:vertical:hover {
        background: transparent;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
    QScrollBar:horizontal {
        background: transparent;
        border: none;
        height: 0px;
        margin: 0px;
    }
    QScrollBar::groove:horizontal {
        background: transparent;
        border: none;
        margin: 0px;
    }
    QScrollBar::handle:horizontal {
        background: transparent;
        min-width: 34px;
        border-radius: 4px;
    }
    QScrollBar::handle:horizontal:hover {
        background: transparent;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: transparent;
    }
    QListWidget#FilesList, QListWidget#FilesList::viewport,
    QListWidget#ModFilesList, QListWidget#ModFilesList::viewport {
        background: transparent;
        border: none;
    }
    QListWidget#FilesList {
        padding: 0px;
    }
    QListWidget#ModFilesList {
        padding: 4px;
        border: 1px solid #cedbea;
        border-radius: 12px;
    }
    QListWidget#FilesList::item,
    QListWidget#ModFilesList::item {
        margin: 0px 0px 8px 0px;
    }
    QListWidget#FilesList::item:selected,
    QListWidget#ModFilesList::item:selected {
        color: #1f2a3d;
    }
    QListWidget#FilesList QScrollBar:vertical,
    QListWidget#ModFilesList QScrollBar:vertical,
    QTextEdit#FileEditor QScrollBar:vertical {
        background: transparent;
        border: none;
        width: 0px;
        margin: 0px;
    }
    QListWidget#FilesList QScrollBar::handle:vertical,
    QListWidget#ModFilesList QScrollBar::handle:vertical,
    QTextEdit#FileEditor QScrollBar::handle:vertical {
        background: transparent;
        min-height: 40px;
        border-radius: 4px;
    }
    QListWidget#FilesList QScrollBar:horizontal,
    QListWidget#ModFilesList QScrollBar:horizontal,
    QTextEdit#FileEditor QScrollBar:horizontal {
        background: transparent;
        border: none;
        height: 0px;
        margin: 0px;
    }
    QListWidget#FilesList QScrollBar::handle:horizontal,
    QListWidget#ModFilesList QScrollBar::handle:horizontal,
    QTextEdit#FileEditor QScrollBar::handle:horizontal {
        background: transparent;
        min-width: 40px;
        border-radius: 4px;
    }
    QListWidget#FilesList QScrollBar::add-page:vertical,
    QListWidget#FilesList QScrollBar::sub-page:vertical,
    QListWidget#ModFilesList QScrollBar::add-page:vertical,
    QListWidget#ModFilesList QScrollBar::sub-page:vertical,
    QTextEdit#FileEditor QScrollBar::add-page:vertical,
    QTextEdit#FileEditor QScrollBar::sub-page:vertical,
    QListWidget#FilesList QScrollBar::add-page:horizontal,
    QListWidget#FilesList QScrollBar::sub-page:horizontal,
    QListWidget#ModFilesList QScrollBar::add-page:horizontal,
    QListWidget#ModFilesList QScrollBar::sub-page:horizontal,
    QTextEdit#FileEditor QScrollBar::add-page:horizontal,
    QTextEdit#FileEditor QScrollBar::sub-page:horizontal {
        background: transparent;
    }
    QListWidget#FilesList QScrollBar::groove:vertical,
    QListWidget#FilesList QScrollBar::groove:horizontal,
    QListWidget#ModFilesList QScrollBar::groove:vertical,
    QListWidget#ModFilesList QScrollBar::groove:horizontal,
    QTextEdit#FileEditor QScrollBar::groove:vertical,
    QTextEdit#FileEditor QScrollBar::groove:horizontal,
    QAbstractScrollArea::corner {
        background: transparent;
        border: none;
    }
    QMenu {
        background: #ffffff;
        border: 1px solid #c9d7eb;
        border-radius: 8px;
        padding: 6px;
    }
    QMenu::item {
        padding: 7px 10px;
        border-radius: 6px;
    }
    QMenu::item:selected {
        background: #e7efff;
    }
    """

    arrow_rule = "image: none;"
    if chevron_icon:
        normalized_icon = chevron_icon.replace("\\", "/")
        arrow_rule = f'image: url("{normalized_icon}");'
    check_rule = "image: none;"
    if check_icon:
        normalized_check = check_icon.replace("\\", "/")
        check_rule = f'image: url("{normalized_check}");'
    dark = (
        night
        .replace("#0f1420", "#151618")
        .replace("#101725", "#181a1d")
        .replace("#101726", "#181a1d")
        .replace("qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #0d1320, stop:0.62 #101827, stop:1 #172339)", "#15171a")
        .replace("qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #131d30, stop:0.68 #162238, stop:1 #1a2842)", "#1a1c20")
        .replace("qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #17253d, stop:1 #131d30)", "#181a1e")
        .replace("#141f32", "#181b1f")
        .replace("#151f33", "#181b1f")
        .replace("#1b2b45", "#20242a")
        .replace("#24304a", "#2e333b")
        .replace("#243550", "#31363f")
        .replace("#2a436a", "#373d46")
        .replace("#284061", "#363c45")
        .replace("#35527d", "#474d57")
        .replace("#21324f", "#23272d")
        .replace("#39547d", "#474e58")
        .replace("#2f8f5d", "#4d8b67")
        .replace("#5070a4", "#5c6777")
        .replace("#4b617f", "#515865")
        .replace("#18253d", "#1e2126")
        .replace("#2b446a", "#353a42")
        .replace("#111a2b", "#131518")
        .replace("#2f4468", "#363b45")
        .replace("#304463", "#3a4048")
        .replace("#4a628c", "#565d69")
        .replace("#5865f2", "#6366f1")
        .replace("#6773ff", "#7c85ff")
        .replace("#243552", "#272b33")
        .replace("#35517f", "#424751")
        .replace("#2d4268", "#31363f")
        .replace("#1d2940", "#202329")
        .replace("#141f32", "#181b1f")
        .replace("#2b3f63", "#2b3038")
        .replace("#1e2a43", "rgba(255, 255, 255, 0.02)")
        .replace("#2a3d61", "rgba(255, 255, 255, 0.045)")
        .replace("#4f73b3", "#5d6572")
        .replace("rgba(83, 108, 148, 0.25)", "rgba(255, 255, 255, 0.06)")
        .replace("qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #141e31, stop:1 #1a2942)", "#191c20")
        .replace("qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #1a2842, stop:1 #203252)", "#20242a")
        .replace("#2e466d", "#363b45")
        .replace("#8ea9df", "#596171")
        .replace("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #324a73, stop:0.55 #283b5c, stop:1 #1d2b44)", "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5a5f67, stop:0.55 #484d55, stop:1 #373c43)")
        .replace("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a5685, stop:0.55 #30486f, stop:1 #223451)", "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #676d76, stop:0.55 #525861, stop:1 #3e434a)")
        .replace("background: #6366f1;", "background: #1f2329;")
        .replace("border-color: #7c85ff;", "border-color: #6b7280;")
        .replace("background: #272b33;", "background: #171a1f;")
        .replace("border: 1px solid #424751;", "border: 1px solid #5f6e8a;")
        .replace("background: #31363f;", "background: #1d2127;")
    )

    oled = (
        dark
        .replace("#151618", "#0b0b0b")
        .replace("#181a1d", "#0f0f0f")
        .replace("#15171a", "#121212")
        .replace("#1a1c20", "#161616")
        .replace("#181a1e", "#141414")
        .replace("#181b1f", "#131313")
        .replace("#20242a", "#1a1a1a")
        .replace("#2e333b", "#272727")
        .replace("#31363f", "#2a2a2a")
        .replace("#373d46", "#2f2f2f")
        .replace("#363c45", "#2d2d2d")
        .replace("#474d57", "#3e3e3e")
        .replace("#131518", "#0e0e0e")
        .replace("#363b45", "#2b2b2b")
        .replace("#2b3038", "#242424")
        .replace("rgba(255, 255, 255, 0.035)", "rgba(255, 255, 255, 0.025)")
        .replace("rgba(255, 255, 255, 0.075)", "rgba(255, 255, 255, 0.055)")
        .replace("#1f2329", "#1b1b1b")
        .replace("#1d2127", "#191919")
        .replace("#6b7280", "#6b6b6b")
        .replace("#d9e0f0", "#e0e0e0")
        .replace("#f5f7fc", "#f7f7f7")
        .replace("#90a1c2", "#a0a0a0")
        .replace("#a9b8d8", "#b8b8b8")
        .replace("#f8fbff", "#fbfbfb")
        .replace("#d7e1f2", "#e0e0e0")
        .replace("#afbdd9", "#bcbcbc")
        .replace("#d6e4ff", "#e3e3e3")
        .replace("#bcc9df", "#c8c8c8")
        .replace("#37568a", "#565656")
        .replace("#4a628c", "#626262")
        .replace("#90a5ff", "#aaaaaa")
        .replace("#6366f1", "#777777")
        .replace("#7c85ff", "#919191")
        .replace("#17233a", "#232323")
        .replace("#2e4269", "#424242")
        .replace("#253c62", "#3c3c3c")
        .replace("#5f80bc", "#808080")
        .replace("#203352", "#333333")
        .replace("#1d2940", "#292929")
        .replace("#dbe4f5", "#e3e3e3")
    )

    light_blue = (
        light
        .replace("#eef2f8", "#e7f2ff")
        .replace("#f3f6fd", "#edf6ff")
        .replace("#f5f7fb", "#eaf3ff")
        .replace("#ffffff", "#fbfdff", 1)
        .replace("#ffffff", "#f9fcff", 1)
        .replace("#ffffff", "#f7fbff", 1)
        .replace("#f0f4fb", "#e3f0ff")
        .replace("background: #f4f7fc;", "background: qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #e4f0ff, stop:0.64 #f0f8ff, stop:1 #fbfdff);", 1)
        .replace("background: #ffffff;\n        border: 1px solid #d2ddeb;\n        border-radius: 16px;", "background: qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #eaf3ff, stop:0.68 #f7fbff, stop:1 #ffffff);\n        border: 1px solid #bfd4f3;\n        border-radius: 16px;", 1)
        .replace("background: #ffffff;\n        border: 1px solid #cad7ea;\n        border-radius: 16px;", "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fafdff, stop:1 #e9f4ff);\n        border: 1px solid #b9d2f4;\n        border-radius: 16px;", 1)
        .replace("background: #ffffff;\n        border: 1px solid #cad8ee;\n        border-radius: 14px;", "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #eef6ff, stop:1 #fbfdff);\n        border: 1px solid #bdd5f7;\n        border-radius: 14px;", 1)
        .replace("background: #f2f7ff;", "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #dcecff, stop:1 #fafdff);", 1)
        .replace("background: #ffffff;\n        border: 1px solid #cedbea;\n        border-radius: 10px;\n        padding: 6px;\n        selection-background-color: #bfd2f0;", "background: #f6fbff;\n        border: 1px solid #bfd6f6;\n        border-radius: 10px;\n        padding: 6px;\n        selection-background-color: #b8d6ff;")
        .replace("background: #5865f2;", "background: #5a95ff;")
        .replace("border-color: #6773ff;", "border-color: #7aaeff;")
        .replace("background: #6d79ff;", "background: #6fa7ff;")
        .replace("background: #dfe9f7;", "background: #dcecff;")
        .replace("background: #e6eef9;", "background: #dbeaff;")
        .replace("background: #edf3fb;", "background: #e7f2ff;")
        .replace("border: 2px solid #bfd2f0;", "border: 2px solid #b1ccf7;")
        .replace("#d2ddeb", "#bfd4f3")
        .replace("#bfd2f0", "#b1ccf7")
        .replace("#dae7ff", "#d3e7ff")
        .replace("#e7efff", "#e3f0ff")
        .replace("#edf3ff", "#eaf4ff")
        .replace("#f5f8ff", "#eef6ff")
        .replace("#5f6cf7", "#5a95ff")
        .replace("#7480ff", "#76a7ff")
        .replace("#6773ff", "#78aaff")
    )

    styles = {
        "night": night,
        "midnight": night,
        "dark": dark,
        "oled": oled,
        "light": light,
        "light blue": light_blue,
    }
    style = styles.get(theme, dark)
    if is_light_theme(theme):
        runtime_order_style = """
        QListWidget#RuntimeOrderList { background: rgba(31,42,61,0.035); border: 1px solid rgba(31,42,61,0.12); border-radius: 10px; padding: 3px; }
        QListWidget#RuntimeOrderList::item { color: #1f2a3d; border-radius: 7px; padding: 7px 10px; }
        QListWidget#RuntimeOrderList::item:selected, QListWidget#RuntimeOrderList::item:hover { background: rgba(31,42,61,0.08); }
        """
    else:
        runtime_order_style = """
        QListWidget#RuntimeOrderList { background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.09); border-radius: 10px; padding: 3px; }
        QListWidget#RuntimeOrderList::item { color: #e4e4e4; border-radius: 7px; padding: 7px 10px; }
        QListWidget#RuntimeOrderList::item { background: rgba(255,255,255,0.018); border: 1px solid rgba(255,255,255,0.045); color: #e4e4e4; border-radius: 7px; padding: 7px 10px; }
        QListWidget#RuntimeOrderList::item:selected, QListWidget#RuntimeOrderList::item:hover { background: rgba(255,255,255,0.055); border-color: rgba(255,255,255,0.10); }
        """
    if is_light_theme(theme):
        settings_navigation_style = """
        QWidget#SettingsTabsBar, QStackedWidget#SettingsPages, QWidget#ThemeSelector, QWidget#SettingsInlineRow { background: transparent; border: none; }
        QPushButton#SettingsTabButton { background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0px; color: #617087; padding: 9px 12px; font-weight: 600; }
        QPushButton#SettingsTabButton:hover { color: #27364d; background: rgba(31,42,61,0.045); }
        QPushButton#SettingsTabButton:checked { color: #1f2a3d; border-bottom-color: #596779; background: transparent; }
        QToolButton#ThemeChoice { background: transparent; border: 1px solid transparent; border-radius: 10px; color: #1f2a3d; padding: 6px; font-weight: 500; }
        QToolButton#ThemeChoice:hover { background: rgba(31,42,61,0.04); border-color: rgba(31,42,61,0.10); }
        QToolButton#ThemeChoice:checked { background: rgba(31,42,61,0.055); border-color: #758196; }
        QWidget#LanguageSelector { background: rgba(31,42,61,0.035); border: 1px solid rgba(31,42,61,0.10); border-radius: 11px; }
        QPushButton#LanguageChoice { background: transparent; border: none; border-radius: 8px; color: #617087; }
        QPushButton#LanguageChoice:hover { background: rgba(31,42,61,0.04); color: #27364d; }
        QPushButton#LanguageChoice:checked { background: #ffffff; color: #1f2a3d; border: 1px solid #c9d3e0; font-weight: 600; }
        """
    else:
        settings_navigation_style = """
        QWidget#SettingsTabsBar, QStackedWidget#SettingsPages, QWidget#ThemeSelector, QWidget#SettingsInlineRow { background: transparent; border: none; }
        QPushButton#SettingsTabButton { background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0px; color: rgba(235,235,235,0.58); padding: 9px 12px; font-weight: 600; }
        QPushButton#SettingsTabButton:hover { color: rgba(245,245,245,0.86); background: rgba(255,255,255,0.025); }
        QPushButton#SettingsTabButton:checked { color: #f1f1f1; border-bottom-color: #757575; background: transparent; }
        QToolButton#ThemeChoice { background: transparent; border: 1px solid transparent; border-radius: 10px; color: #e5e5e5; padding: 6px; font-weight: 500; }
        QToolButton#ThemeChoice:hover { background: rgba(255,255,255,0.025); border-color: rgba(255,255,255,0.065); }
        QToolButton#ThemeChoice:checked { background: rgba(255,255,255,0.035); border-color: #696969; }
        QWidget#LanguageSelector { background: rgba(255,255,255,0.018); border: 1px solid rgba(255,255,255,0.065); border-radius: 11px; }
        QPushButton#LanguageChoice { background: transparent; border: none; border-radius: 8px; color: rgba(235,235,235,0.60); }
        QPushButton#LanguageChoice:hover { background: rgba(255,255,255,0.025); color: rgba(245,245,245,0.88); }
        QPushButton#LanguageChoice:checked { background: rgba(255,255,255,0.075); color: #f1f1f1; border: 1px solid rgba(255,255,255,0.12); font-weight: 600; }
        """
    style += runtime_order_style
    style += settings_navigation_style
    style = style.replace("__COMBO_ARROW__", arrow_rule)
    return style.replace("__CHECK_ICON__", check_rule)
