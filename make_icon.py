"""Draws icon.png (256x256): a gold d20 on a dark rounded tile."""
import os, math, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QColor, QPen, QBrush, QPolygonF, QPainterPath
from PyQt6.QtCore import QPointF, QRectF, Qt

app = QGuiApplication(sys.argv)
S = 256
img = QImage(S, S, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)

bg = QPainterPath()
bg.addRoundedRect(QRectF(8, 8, S - 16, S - 16), 48, 48)
p.fillPath(bg, QBrush(QColor("#1d1916")))
p.setPen(QPen(QColor("#3a322b"), 4))
p.drawPath(bg)

cx, cy, r = S / 2, S / 2 + 4, 92
hexagon = [QPointF(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 270, 60)]
p.setBrush(QBrush(QColor("#d9a441")))
p.setPen(QPen(QColor("#f2cf7d"), 5, join=Qt.PenJoinStyle.RoundJoin))
p.drawPolygon(QPolygonF(hexagon))

ir = r * 0.55
tri = [QPointF(cx + ir * math.cos(math.radians(a)), cy + ir * math.sin(math.radians(a))) for a in (-90, 30, 150)]
p.setBrush(QBrush(QColor("#b9852c")))
p.setPen(QPen(QColor("#1d1916"), 5, join=Qt.PenJoinStyle.RoundJoin))
p.drawPolygon(QPolygonF(tri))
pen = QPen(QColor("#1d1916"), 4)
p.setPen(pen)
for i, h in enumerate(hexagon):              # facet lines from the outer corners to the inner triangle
    p.drawLine(h, tri[[0, 0, 1, 1, 2, 2][i]])
p.drawLine(hexagon[1], tri[1]); p.drawLine(hexagon[3], tri[2]); p.drawLine(hexagon[5], tri[0])

f = p.font()
f.setPixelSize(40)
f.setBold(True)
p.setFont(f)
p.setPen(QColor("#1d1916"))
p.drawText(QRectF(cx - 40, cy - 22, 80, 44), Qt.AlignmentFlag.AlignCenter, "20")
p.end()
img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png"))
print("icon.png written")
