"""Relay's small visual vocabulary, built on the desktop's Qt palette."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette


def palette_for(mode: str, system: QPalette) -> QPalette:
    if mode == "system":
        return QPalette(system)
    dark = mode == "dark"
    colors = {
        "Window": "#222b32" if dark else "#f3f5f7",
        "WindowText": "#e7eef2" if dark else "#24313c",
        "Base": "#1d252c" if dark else "#ffffff",
        "AlternateBase": "#2b353e" if dark else "#eaf0f4",
        "Text": "#e7eef2" if dark else "#24313c",
        "Button": "#2b353e" if dark else "#ffffff",
        "ButtonText": "#e7eef2" if dark else "#24313c",
        "Highlight": "#82bccf" if dark else "#326c87",
        "HighlightedText": "#17232c" if dark else "#ffffff",
        "Link": "#82bccf" if dark else "#326c87",
        "PlaceholderText": "#a5b3bf" if dark else "#586977",
        "ToolTipBase": "#2b353e" if dark else "#ffffff",
        "ToolTipText": "#e7eef2" if dark else "#24313c",
        "Mid": "#4b5b67" if dark else "#ced8df",
    }
    palette = QPalette(system)
    for name, value in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, name), QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#82929e" if dark else "#77858f"))
    return palette


def stylesheet(palette: QPalette) -> str:
    def color(role):
        return palette.color(getattr(QPalette.ColorRole, role)).name()
    window, text = color("Window"), color("WindowText")
    surface, base = color("Button"), color("Base")
    accent, on_accent = color("Highlight"), color("HighlightedText")
    muted = color("PlaceholderText")
    border = color("Mid")
    return f"""
    QMainWindow, QWidget#root, QWidget#page {{ background: {window}; color: {text}; }}
    QLabel {{ background: transparent; color: {text}; }}
    QLabel#brand {{ font-size: 24px; font-weight: 700; }}
    QLabel#heading {{ font-size: 28px; font-weight: 700; }}
    QLabel#heroTitle {{ font-size: 52px; font-weight: 800; }}
    QLabel#gameSubtitle {{ font-size: 21px; font-weight: 600; }}
    QLabel#heroNote {{ font-size: 14px; color: {muted}; }}
    QLabel#caption, QLabel#hint {{ font-size: 12px; color: {muted}; }}
    QLabel#rowTitle {{ font-size: 15px; font-weight: 600; }}
    QLabel#platform {{ font-size: 11px; color: {muted}; padding: 5px 10px;
                       border: 1px solid {border}; border-radius: 11px; }}
    QFrame#divider {{ background: {border}; min-height: 1px; max-height: 1px; }}
    QFrame#setting {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
    QFrame#homeStatus {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
    QPushButton {{ color: {text}; background: {surface}; border: 1px solid {border};
                  border-radius: 6px; padding: 10px 14px; font-size: 13px; font-weight: 500; }}
    QPushButton:hover {{ border-color: {accent}; background: {base}; }}
    QPushButton:pressed {{ background: {window}; }}
    QPushButton:focus {{ border: 2px solid {accent}; padding: 9px 13px; }}
    QPushButton:disabled {{ color: {muted}; background: {window}; }}
    QPushButton#play {{ background: {accent}; color: {on_accent}; border: 2px solid {accent};
                       font-size: 15px; font-weight: 700; padding: 13px 22px; border-radius: 8px; }}
    QPushButton#play:hover, QPushButton#play:focus {{ border-color: {text}; }}
    QPushButton#play:disabled {{ background: {window}; color: {muted}; border-color: {border}; }}
    QPushButton#link {{ background: transparent; border-color: transparent; color: {muted}; padding: 7px 8px; }}
    QPushButton#link:hover, QPushButton#link:focus {{ color: {text}; border-color: {accent}; }}
    QPushButton#tab, QPushButton#tabActive {{ background: transparent; border: 2px solid transparent;
        border-radius: 5px; padding: 9px 10px; color: {muted}; }}
    QPushButton#tabActive {{ color: {text}; background: {surface}; border-bottom-color: {accent}; }}
    QPushButton#tab:hover, QPushButton#tab:focus, QPushButton#tabActive:focus {{ border-color: {accent}; }}
    QLineEdit, QComboBox {{ color: {text}; background: {base}; border: 1px solid {border};
                          border-radius: 6px; padding: 10px; min-height: 18px; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {accent}; }}
    QPlainTextEdit {{ color: {text}; background: {base}; border: 1px solid {border};
                     border-radius: 6px; padding: 10px; }}
    QCheckBox {{ color: {text}; spacing: 9px; padding: 3px 0; }}
    QCheckBox:focus {{ outline: 1px solid {accent}; }}
    QProgressBar {{ background: {window}; border: none; border-radius: 2px; max-height: 5px; }}
    QProgressBar::chunk {{ background: {accent}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QTableWidget {{ background: {base}; color: {text}; border: 1px solid {border};
        gridline-color: {border}; selection-background-color: {accent}; selection-color: {on_accent}; }}
    QHeaderView::section {{ background: {surface}; color: {text}; border: none; padding: 10px 6px; }}
    QToolTip {{ color: {text}; background: {surface}; border: 1px solid {border}; padding: 6px; }}
    """


class ThemeManager(QObject):
    changed = Signal()

    def __init__(self, app, mode="system"):
        super().__init__(app)
        self.app = app
        self.system_palette = QPalette(app.palette())
        self.mode = mode if mode in ("system", "light", "dark") else "system"
        self.applying = False
        app.paletteChanged.connect(self.system_changed)
        self.apply(self.mode)

    def system_changed(self, palette):
        if self.applying:
            return
        self.system_palette = QPalette(palette)
        self.apply(self.mode)

    def apply(self, mode):
        self.mode = mode if mode in ("system", "light", "dark") else "system"
        self.applying = True
        try:
            palette = palette_for(self.mode, self.system_palette)
            self.app.setPalette(palette)
            self.app.setStyleSheet(stylesheet(palette))
        finally:
            self.applying = False
        self.changed.emit()
