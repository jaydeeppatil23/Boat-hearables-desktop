"""Small native controls for the earbud utility."""

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QCheckBox, QProgressBar

ACCENT = "#E53945"
MUTED = "#A0A2AA"

THEME = """
QMainWindow, QDialog, QWidget#main, QScrollArea, QScrollArea > QWidget > QWidget { background: #16171B; }
QWidget { color: #EDEEF0; font-size: 13px; }
QLabel { background: transparent; border: none; }
QLabel#muted { color: #A0A2AA; }
QLabel#sectionTitle { color: #C6C8CF; font-size: 12px; font-weight: 600; }
QFrame#divider { background: #303137; border: none; }
QPushButton { background: #24252B; color: #EDEEF0; border: 1px solid #43454E;
              border-radius: 5px; padding: 7px 13px; }
QPushButton:hover { background: #2E3037; border-color: #676A76; }
QPushButton:pressed { background: #1C1D22; }
QPushButton:disabled { background: #1D1E23; color: #6C6E78; border-color: #303139; }
QPushButton:focus, QComboBox:focus, QListWidget:focus { border: 1px solid #AEB2BF; }
QPushButton#primary { background: #D93643; color: white; border-color: #D93643; font-weight: 600; }
QPushButton#primary:hover { background: #E54B56; border-color: #E54B56; }
QPushButton#primary:focus { border-color: #FFBAC0; }
QPushButton#primary:disabled { background: #322328; color: #927279; border-color: #423038; }
QPushButton#quiet { background: transparent; border-color: transparent; color: #C3C5CD; }
QPushButton#quiet:hover { background: #28292F; border-color: #41434C; }
QPushButton#quiet:focus { border-color: #AEB2BF; }
QPushButton#quiet:disabled { color: #676A75; }
QPushButton#danger { background: #33232A; color: #F5ACB3; border-color: #74434C; }
QPushButton#danger:disabled { color: #75636A; background: #211E23; border-color: #363037; }
QComboBox { background: #202127; border: 1px solid #454751; border-radius: 5px;
            padding: 7px 12px; min-height: 18px; }
QComboBox:disabled { color: #6C6E78; border-color: #303139; }
QComboBox::drop-down { border: none; width: 25px; }
QComboBox::down-arrow { image: url("__CHEVRON_ICON__"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: #25262D; color: #EDEEF0; border: 1px solid #5D606D;
                            selection-background-color: #3D404B; selection-color: white; padding: 4px; }
QListWidget { background: #1C1D22; border: 1px solid #373942; border-radius: 5px; outline: none; }
QListWidget::item { padding: 11px 12px; border-bottom: 1px solid #303139; }
QListWidget::item:hover { background: #282A31; }
QListWidget::item:selected { background: #383B46; color: #FFFFFF; }
QCheckBox { spacing: 8px; color: #B8BAC3; font-size: 12px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; }
QCheckBox::indicator:unchecked { background: #202127; border: 1px solid #666A77; }
QCheckBox::indicator:checked { background: #D93643; border: 1px solid #EE707A; image: url("__CHECK_ICON__"); }
QCheckBox:focus { color: #FFFFFF; }
QTextEdit { background: #1C1D22; color: #BAC0D0; border: 1px solid #41434E; border-radius: 5px; padding: 8px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #474A55; min-height: 28px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: #666A76; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #30323B; color: #F0F1F4; border: 1px solid #696D7D; padding: 6px; }
""".replace("__CHECK_ICON__", (Path(__file__).resolve().parent / "assets" / "check.svg").as_posix()).replace(
    "__CHEVRON_ICON__", (Path(__file__).resolve().parent / "assets" / "chevron.svg").as_posix())


def label(text, role=None, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        widget.setObjectName(role)
    widget.setWordWrap(wrap)
    return widget


def icon(name, color=MUTED, size=24):
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 12, size / 12)
    painter.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if name == "bluetooth":
        for a, b in [((9, 7), (16, 14)), ((16, 14), (12, 19)), ((12, 19), (12, 4)), ((12, 4), (16, 8)), ((16, 8), (9, 15))]:
            painter.drawLine(*a, *b)
    elif name == "earbuds":
        painter.drawRoundedRect(QRectF(5, 5, 5, 8), 2, 2)
        painter.drawLine(8, 13, 8, 19)
        painter.drawRoundedRect(QRectF(14, 5, 5, 8), 2, 2)
        painter.drawLine(16, 13, 16, 19)
    else:
        painter.drawArc(QRectF(5, 5, 14, 14), 35 * 16, 280 * 16)
        painter.drawLine(18, 4, 18, 9)
        painter.drawLine(18, 9, 13, 9)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


class BatteryReadout(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setMinimumWidth(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(label(title, "muted"))
        self.val_lbl = label("—")
        self.val_lbl.setStyleSheet("font-size: 28px; font-weight: 600;")
        layout.addWidget(self.val_lbl)
        self.pbar = QProgressBar()
        self.pbar.setTextVisible(False)
        self.pbar.setFixedHeight(3)
        layout.addWidget(self.pbar)
        self.chg_lbl = label("", "muted")
        self.chg_lbl.setStyleSheet("font-size: 11px;")
        self.chg_lbl.setMinimumHeight(16)
        layout.addWidget(self.chg_lbl)
        self.set_offline()
        self.setAccessibleName(title + " battery")

    def set_level(self, level, is_charging):
        if not 0 <= level <= 100:
            self.set_offline("Unavailable")
            return
        self.val_lbl.setText(f"{level}%")
        self.pbar.setValue(level)
        self.chg_lbl.setText("Charging" if is_charging else ("Low battery" if level <= 20 else ""))
        color = "#89B7A5" if is_charging else (ACCENT if level <= 20 else "#969CA9")
        self._bar_color(color)
        self.setAccessibleDescription(f"{level} percent" + (", charging" if is_charging else ""))

    def _bar_color(self, color):
        self.pbar.setStyleSheet(f"QProgressBar {{ background: #353740; border: none; border-radius: 1px; }}"
                               f"QProgressBar::chunk {{ background: {color}; border-radius: 1px; }}")

    def set_offline(self, text=""):
        self.val_lbl.setText("—")
        self.pbar.setValue(0)
        self.chg_lbl.setText(text)
        self._bar_color("#555966")
        self.setAccessibleDescription(text or "Unavailable")


class ToggleSwitch(QCheckBox):
    """Use native checkbox semantics and keyboard behavior with a switch drawing."""

    def __init__(self, title):
        super().__init__()
        self.setAccessibleName(title)
        self.setTristate(True)
        self.setFixedSize(46, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        state = self.checkState()
        enabled = self.isEnabled()
        track = ACCENT if state == Qt.CheckState.Checked else "#515561"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(track if enabled else "#33363F"))
        painter.drawRoundedRect(QRectF(3, 4, 40, 20), 10, 10)
        x = 25 if state == Qt.CheckState.Checked else (15 if state == Qt.CheckState.PartiallyChecked else 5)
        painter.setBrush(QColor("#F5F5F7" if enabled else "#787D8A"))
        painter.drawEllipse(QRectF(x, 6, 16, 16))
        if state == Qt.CheckState.PartiallyChecked:
            painter.setPen(QPen(QColor("#515561"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(20, 14, 26, 14)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#B9BECC"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, 45, 27), 5, 5)


class ModeControl(QFrame):
    toggled = pyqtSignal(bool)
    confirmation_failed = pyqtSignal(str)

    def __init__(self, title, description):
        super().__init__()
        self.is_active = None
        self.pending = None
        self._title = title
        self._online = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(6000)
        self._timer.timeout.connect(self._timed_out)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 9, 0, 9)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(label(title))
        self.sub_l = label(description, "muted")
        self.sub_l.setStyleSheet("font-size: 12px;")
        text.addWidget(self.sub_l)
        layout.addLayout(text, 1)
        self.state_lbl = label("", "muted")
        self.state_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.state_lbl)
        self.btn = ToggleSwitch(title)
        self.btn.clicked.connect(self._on_clicked)
        layout.addWidget(self.btn)
        self.set_online(False)

    def _on_clicked(self):
        self.pending = not bool(self.is_active)
        self._set_switch_state()
        self.btn.setEnabled(False)
        self.state_lbl.setText("Updating…")
        self.state_lbl.show()
        self._timer.start()
        self.toggled.emit(self.pending)

    def _set_switch_state(self):
        if self.is_active is None:
            self.btn.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self.btn.setCheckState(Qt.CheckState.Checked if self.is_active else Qt.CheckState.Unchecked)

    def set_online(self, online):
        self._online = online
        self._timer.stop()
        self.pending = None
        self.is_active = None
        self._render()

    def set_state(self, active):
        self.is_active = bool(active)
        if self.pending is not None and self.pending != self.is_active:
            return
        self.pending = None
        self._timer.stop()
        self._render()

    def _render(self):
        self._set_switch_state()
        self.btn.setEnabled(self._online and self.pending is None)
        unknown = self._online and self.is_active is None
        self.state_lbl.setText("State unavailable" if unknown else "")
        self.state_lbl.setVisible(unknown)
        self.btn.setToolTip("State unavailable. Click to enable." if unknown else self.sub_l.text())
        self.btn.setAccessibleDescription("State unavailable" if self.is_active is None else
                                          ("On" if self.is_active else "Off"))

    def fail_pending(self):
        self._timer.stop()
        self.pending = None
        self._render()

    def _timed_out(self):
        self.fail_pending()
        self.state_lbl.setText("No response")
        self.state_lbl.show()
        self.confirmation_failed.emit(f"{self._title}: no state update received. Try again.")
