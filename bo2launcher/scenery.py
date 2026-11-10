"""Painted depth effects for real game photographs; no continuous render loop."""
from PySide6.QtCore import Qt, QPointF, QRectF, QSize, QEvent, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPixmap, QPainterPath, QLinearGradient, QPen, QTransform
from PySide6.QtWidgets import QWidget, QPushButton
from . import artwork


class PointerDepth:
    """A short, interruptible response to input. Idle, hidden and reduced motion are still."""
    def init_depth(self):
        self.offset = QPointF()
        self.motion_enabled = True
        self.setMouseTracking(True)
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(180)
        self.motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.motion.valueChanged.connect(self._move_depth)

    def _move_depth(self, value):
        self.offset = value
        self.update()

    def set_motion_enabled(self, enabled):
        self.motion_enabled = bool(enabled)
        if not enabled:
            self.motion.stop()
            self._move_depth(QPointF())

    def move_depth(self, pos):
        if not self.motion_enabled or not self.isVisible():
            return
        self.motion.stop()
        self.motion.setStartValue(self.offset)
        self.motion.setEndValue(pos)
        self.motion.start()

    def mouseMoveEvent(self, event):
        self.move_depth(QPointF(event.position().x() / max(1, self.width()) * 2 - 1,
                               event.position().y() / max(1, self.height()) * 2 - 1))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.move_depth(QPointF())
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.motion.stop()
        self._move_depth(QPointF())
        super().hideEvent(event)


class HomeBackdrop(PointerDepth, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_depth()
        self.pix = QPixmap()
        self.scaled = QPixmap()
        self.setMinimumHeight(300)
        self.load(artwork.home_image())

    def load(self, path):
        self.pix = QPixmap(str(path)) if path else QPixmap()
        self._cache_image()
        self.update()

    def _cache_image(self):
        # Scale only on image/size changes, never on pointer frames.
        self.scaled = self.pix.scaled((self.size() + QSize(32, 32)) * self.devicePixelRatioF(),
                                     Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation) if not self.pix.isNull() else QPixmap()
        self.scaled.setDevicePixelRatio(self.devicePixelRatioF())

    def resizeEvent(self, event):
        self._cache_image()
        super().resizeEvent(event)

    def watch_content(self):
        for child in self.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove:
            pos = watched.mapTo(self, event.position().toPoint())
            self.move_depth(QPointF(pos.x() / max(1, self.width()) * 2 - 1,
                                   pos.y() / max(1, self.height()) * 2 - 1))
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        full = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(full, 16, 16)
        p.setClipPath(clip)
        p.fillRect(full, QColor('#15232f'))
        if not self.scaled.isNull():
            size = self.scaled.deviceIndependentSize()
            p.drawPixmap(QPointF((self.width() - size.width()) / 2 - self.offset.x() * 7,
                                 (self.height() - size.height()) / 2 - self.offset.y() * 7), self.scaled)
        scrim = QLinearGradient(0, 0, self.width(), 0)
        for at, alpha in ((0, 235), (.33, 175), (.62, 35), (1, 0)):
            scrim.setColorAt(at, QColor(9, 15, 22, alpha))
        p.fillRect(full, scrim)
        bottom = QLinearGradient(0, self.height() * .55, 0, self.height())
        bottom.setColorAt(0, QColor(9, 15, 22, 0))
        bottom.setColorAt(1, QColor(9, 15, 22, 235))
        p.fillRect(full, bottom)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 35), 1))
        p.drawRoundedRect(full.adjusted(.5, .5, -.5, -.5), 16, 16)


class SceneTile(PointerDepth, QPushButton):
    """Keyboard accessible photo with a real perspective transform on hover."""
    def __init__(self, scene, parent=None):
        super().__init__(scene.title, parent)
        self.scene = scene
        self.init_depth()
        self.pix = QPixmap(str(scene.path))
        self.setCheckable(True)
        self.setMinimumSize(150, 98)
        self.setMaximumHeight(154)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('Usar ambiente ' + scene.title)
        self.setToolTip(scene.title + ' · Cambiar el fondo del launcher')
        self.toggled.connect(self.update)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        transform = QTransform()
        transform.translate(self.width() / 2, self.height() / 2)
        transform.rotate(self.offset.y() * -5, Qt.Axis.XAxis)
        transform.rotate(self.offset.x() * 7, Qt.Axis.YAxis)
        transform.translate(-self.width() / 2, -self.height() / 2)
        p.setTransform(transform)
        full = QRectF(self.rect()).adjusted(5, 5, -5, -5)
        clip = QPainterPath()
        clip.addRoundedRect(full, 10, 10)
        p.setClipPath(clip)
        p.fillRect(full, QColor('#15232f'))
        if not self.pix.isNull():
            ratio = max(full.width() / self.pix.width(), full.height() / self.pix.height())
            source = QRectF(0, 0, full.width() / ratio, full.height() / ratio)
            source.moveCenter(QPointF(self.pix.width() / 2, self.pix.height() / 2))
            p.drawPixmap(full, self.pix, source)
        shade = QLinearGradient(0, full.top(), 0, full.bottom())
        shade.setColorAt(0, QColor(9, 15, 22, 0))
        shade.setColorAt(.35, QColor(9, 15, 22, 25))
        shade.setColorAt(1, QColor(9, 15, 22, 235))
        p.fillRect(full, shade)
        font = self.font()
        font.setPixelSize(15)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor('#ffffff'))
        p.drawText(full.adjusted(14, 0, -14, -12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, self.scene.title)
        if self.isChecked():
            p.setBrush(QColor('#f5a34d'))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(full.right() - 15, full.top() + 15), 4, 4)
        p.setClipping(False)
        tone = '#ffffff' if self.hasFocus() else '#f5a34d' if self.isChecked() else '#56616d'
        p.setPen(QPen(QColor(tone), 2 if self.hasFocus() or self.isChecked() else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(full, 10, 10)
