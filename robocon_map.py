# -*- coding: utf-8 -*-
"""场地地图绘制：在 roadmap.png 底图上叠加建塔处、塔块、比赛用品与五色石。

本模块只负责“把游戏状态画出来”，通过一个外部 engine 读取实时状态
（engine.slots / engine.state / engine.stone_placed_by），
不参与游戏规则计算，也不直接操作按钮。
"""
import os

from PyQt5.QtWidgets import QFrame
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import (QPainter, QColor, QPen, QFont, QBrush,
                         QPixmap, QPainterPath)

from robocon_data import (Config, BuildSlot,
                          SLOT_POSITIONS, CENTRAL_BASE_POS, FIVE_COLOR_BASE_POS,
                          RED_STORAGE_RECT, BLUE_STORAGE_RECT, FIRST_PUBLIC_CENTER,
                          RED_TRANSFER_RECT, BLUE_TRANSFER_RECT,
                          IMAGE_W, IMAGE_H)
from robocon_paths import resource_dir

# 队色 / 用品色
C_RED = QColor(223, 34, 34)
C_BLUE = QColor(50, 0, 255)
C_GREEN = QColor(40, 100, 50)
C_GOLD = QColor(218, 165, 32)
C_BG = QColor(245, 245, 240)

# 机器人小球在各“非建塔”区域的落点（roadmap.png 绝对像素坐标）。
# 重置区拆成 TR 重置区 / BR 重置区（对应每队启动/重试区的两个方块，避免开局叠在一起）。
ROBOT_POS = {
    "tr_reset":   {"red": (70, 1310),  "blue": (1310, 1310)},   # TR 重置区（红左下/蓝右下 外侧方块）
    "br_reset":   {"red": (155, 1290), "blue": (1388, 1290)},   # BR 重置区（内侧方块）
    "storage":    {"red": (140, 120),  "blue": (1320, 120)},    # 储存区（红左上/蓝右上）
    "public":     {"red": (690, 1240), "blue": (750, 1240)},    # 地面公共区（底部中央网格附近）
    "stone_base": {"red": (700, 200),  "blue": (762, 200)},     # 五色石基座（顶部中央）
    "transfer":   {"red": (270, 790),  "blue": (1190, 790)},    # 传递区（红左/蓝右 中部）
    "central":    {"red": (700, 588),  "blue": (762, 588)},     # 中央基座（L2 中央）
}

# BR 在建塔处但未记录具体编号时的兜底地点（正常情况 br_at_slot 已赋值，不会走到）
_BR_SLOT_FALLBACK = {
    "l1":         {"red": "R1", "blue": "B1"},
    "l1_public":  {"red": "P1", "blue": "P1"},
    "l2":         {"red": "L2-1", "blue": "L2-1"},
}


class MapWidget(QFrame):
    """对外展示：以 roadmap.png 为底图，实时叠加各建塔处的塔和各类用品状态。"""

    def __init__(self, config: Config, parent=None, engine=None):
        super().__init__(parent)
        self.cfg = config
        self.engine = engine
        self.setMinimumSize(680, 640)
        self.setFrameShape(QFrame.Box)
        self.setStyleSheet("background-color: #f7f7f5;")
        self.map_pixmap = QPixmap(os.path.join(resource_dir(), "roadmap.png"))

    # ---------- 实时状态（委托给 engine，避免地图与 UI 直接耦合） ----------
    @property
    def slots(self):
        return self.engine.slots if self.engine else []

    @property
    def team_state(self):
        return self.engine.state if self.engine else None

    @property
    def stone_placed_by(self):
        return self.engine.stone_placed_by if self.engine else None

    # ---------------- 坐标换算辅助 ----------------
    def _cx(self, x_frac, rect):
        return rect.left() + x_frac * rect.width()

    def _cy(self, y_frac, rect):
        return rect.top() + y_frac * rect.height()

    def _px_x(self, px, rect):
        """把 roadmap.png 上的绝对像素 x 映射到控件绘制区域。"""
        return rect.left() + (px / IMAGE_W) * rect.width()

    def _px_y(self, py, rect):
        return rect.top() + (py / IMAGE_H) * rect.height()

    def _pw(self, px, rect):
        return (px / IMAGE_W) * rect.width()

    def _ph(self, px, rect):
        return (px / IMAGE_H) * rect.height()

    def _image_rect(self, outer):
        """把 roadmap.png 按 1:1 等比缩放并居中到控件，返回实际绘制区域。"""
        if self.map_pixmap is None or self.map_pixmap.isNull():
            return outer
        pw = self.map_pixmap.width()
        ph = self.map_pixmap.height()
        scale = min(outer.width() / pw, outer.height() / ph)
        dw = pw * scale
        dh = ph * scale
        x = outer.left() + (outer.width() - dw) / 2
        y = outer.top() + (outer.height() - dh) / 2
        return QRectF(x, y, dw, dh)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            self._do_paint(p, event)
        except Exception as e:
            p.end()
            print("MapWidget paint error:", e)

    def _do_paint(self, p, event):
        p.setRenderHint(QPainter.Antialiasing)
        outer = QRectF(0, 0, self.width(), self.height())

        if self.map_pixmap is None or self.map_pixmap.isNull():
            p.fillRect(outer, C_BG)
            p.setPen(Qt.black)
            p.drawText(outer, Qt.AlignCenter, "未找到 roadmap.png，请将其放在程序同目录。")
            return

        rect = self._image_rect(outer)
        p.drawPixmap(rect, self.map_pixmap,
                     QRectF(0, 0, self.map_pixmap.width(), self.map_pixmap.height()))

        # 各建塔处的塔
        for slot in self.slots:
            self._draw_build_zone(p, slot, rect)

        # 五色石：初始在五色石基座；被移动后安放到中央基座
        self._draw_five_color_on_base(p, rect)
        self._draw_central_stone(p, rect)

        # 比赛用品：储存区 塔基/中段 + 公共区 塔顶 + 传递区
        self._draw_pieces(p, rect)

        # 机器人位置小球（TR / BR，白色描边，随区域移动）
        self._draw_robots(p, rect)

    # ---------------- 团队颜色 ----------------
    @staticmethod
    def _team_color(team):
        if team == "red":
            return C_RED
        if team == "blue":
            return C_BLUE
        return QColor(255, 255, 255)

    # ---------------- 单个建塔处：绿色底座 + 塔块 + 三个进度格 ----------------
    def _draw_build_zone(self, p, slot, rect):
        px, py = slot.pos
        size = 0.042 * rect.width()
        gx = self._px_x(px, rect) - size / 2
        gy = self._px_y(py, rect) - size / 2
        sr = QRectF(gx, gy, size, size)
        self._draw_tower(p, slot, sr)
        self._draw_progress(p, slot, gx, gy, size, rect)

    def _draw_tower(self, p, slot, sr):
        p.setPen(QPen(Qt.black, 1))
        p.setBrush(QBrush(C_GREEN))
        p.drawRect(sr)

        bw = sr.width() * 0.80
        bh = sr.height() * 0.28
        cx = sr.center().x()
        bottom = sr.bottom()

        if slot.base:
            self._block(p, cx, bottom - bh, bw, bh, slot.base)
        if slot.mid:
            self._block(p, cx, bottom - bh * 2, bw * 0.80, bh, slot.mid)
        if slot.top:
            self._block(p, cx, bottom - bh * 3, bw * 0.62, bh, slot.top)

        p.setPen(Qt.white)
        p.setFont(QFont("", 5))
        p.drawText(sr, Qt.AlignTop | Qt.AlignHCenter, slot.id)

    def _block(self, p, cx, y, bw, bh, owner):
        p.setBrush(QBrush(self._team_color(owner)))
        p.setPen(QPen(Qt.black, 0.7))
        p.drawRect(QRectF(cx - bw / 2, y, bw, bh))

    def _draw_progress(self, p, slot, gx, gy, size, rect):
        """建塔处下方的三个白格（竖向）：自下而上=塔基/中段/塔顶；建成后变队色。"""
        ps = 0.016 * rect.width()
        gap = 0.006 * rect.width()
        cx = gx + size / 2
        y_base = gy + size + gap + 2 * (ps + gap)
        layers = [("base", y_base),
                  ("mid", y_base - (ps + gap)),
                  ("top", y_base - 2 * (ps + gap))]
        p.setPen(QPen(Qt.black, 0.8))
        for layer, y in layers:
            val = getattr(slot, layer)
            p.setBrush(QBrush(self._team_color(val) if val else QColor(255, 255, 255)))
            p.drawRect(QRectF(cx - ps / 2, y, ps, ps))

    def _draw_stone_square(self, p, x, y, size, owner=None):
        """用橙色正方形表示五色石；owner 指定时加一圈队色描边。"""
        p.setPen(QPen(Qt.black, 1))
        p.setBrush(QBrush(C_GOLD))
        p.drawRect(QRectF(x - size / 2, y - size / 2, size, size))
        if owner:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(self._team_color(owner), 1.5))
            p.drawRect(QRectF(x - size / 2 - 2, y - size / 2 - 2, size + 4, size + 4))

    def _draw_five_color_on_base(self, p, rect):
        """五色石初始放在原始基座（五色石基座）上：橙色正方形。"""
        rstate = (self.team_state or {}).get("red")
        bstate = (self.team_state or {}).get("blue")
        on_base = (rstate is None or rstate.stone_on_base) and \
                  (bstate is None or bstate.stone_on_base)
        if not on_base:
            return
        x = self._px_x(FIVE_COLOR_BASE_POS[0], rect)
        y = self._px_y(FIVE_COLOR_BASE_POS[1], rect)
        self._draw_stone_square(p, x, y, 0.030 * rect.width())

    def _draw_central_stone(self, p, rect):
        """五色石被移动/安放到中央基座：橙色正方形 + 放置队颜色描边。"""
        if not self.stone_placed_by:
            return
        x = self._px_x(CENTRAL_BASE_POS[0], rect)
        y = self._px_y(CENTRAL_BASE_POS[1], rect)
        self._draw_stone_square(p, x, y, 0.032 * rect.width(), owner=self.stone_placed_by)

    # ---------------- 比赛用品（塔基/中段、塔顶、五色石）初始摆放 ----------------
    def _draw_pieces(self, p, rect):
        rstate = (self.team_state or {}).get("red")
        bstate = (self.team_state or {}).get("blue")
        for color, state, srect, zrect in (
            ("red", rstate, RED_STORAGE_RECT, RED_TRANSFER_RECT),
            ("blue", bstate, BLUE_STORAGE_RECT, BLUE_TRANSFER_RECT),
        ):
            if state is None:
                continue
            team = C_RED if color == "red" else C_BLUE
            self._draw_stock(p, rect, srect, team, state.stored_blocks)
            self._draw_transfer(p, rect, zrect, state, team)
        n_tops = rstate.public_tops if rstate else 12
        self._draw_public_tops(p, rect, n_tops)

    def _draw_transfer(self, p, rect, zrect, state, team):
        """传递区：已送达的 塔基/中段 + 塔顶；五色石送到后画一个橙色方块。"""
        x0 = self._px_x(zrect[0], rect)
        y0 = self._px_y(zrect[1], rect)
        zw = self._pw(zrect[2], rect)
        zh = self._ph(zrect[3], rect)
        piece = 0.013 * rect.width()
        cols = 5
        gapx = zw / cols
        py = y0 + (zh - piece) / 2
        idx = 0
        p.setPen(QPen(QColor(255, 255, 255), 1.0))
        for item in state.transfer_floor:
            if idx >= cols:
                break
            px = x0 + idx * gapx + (gapx - piece) / 2
            if item == "block":
                p.setBrush(QBrush(team))
                p.drawRect(QRectF(px, py, piece, piece))
            elif item == "top":
                self._draw_top_piece(p, px, py, piece)
            elif item == "stone":
                self._draw_stone_square(p, x0 + zw * 0.5, y0 + zh * 0.72, 0.014 * rect.width())
            idx += 1

    def _draw_stock(self, p, rect, srect, color, count):
        """在储存区矩形内画 count 个方块：2 行 × 10 列，模拟每列最多堆叠 2 块。"""
        x0 = self._px_x(srect[0], rect)
        y0 = self._px_y(srect[1], rect)
        sw = self._pw(srect[2], rect)
        sh = self._ph(srect[3], rect)
        cols, rows = 10, 2
        piece = 0.013 * rect.width()
        gapx = sw / cols
        gapy = sh / rows
        p.setPen(QPen(QColor(255, 255, 255), 1.2))
        for i in range(int(count)):
            if i >= cols * rows:
                break
            r_i = i // cols
            c_i = i % cols
            px = x0 + c_i * gapx + (gapx - piece) / 2
            py = y0 + r_i * gapy + (gapy - piece) / 2
            p.setBrush(QBrush(color))
            p.drawRect(QRectF(px, py, piece, piece))
            p.setBrush(QBrush(QColor(255, 255, 255)))
            p.drawRect(QRectF(px + piece * 0.38, py + piece * 0.38, piece * 0.24, piece * 0.24))

    def _draw_public_tops(self, p, rect, n):
        """第一公共区：12 个塔顶画成整齐的小方块（按剩余数量减少，逻辑同储存区方块）。"""
        cx = self._px_x(FIRST_PUBLIC_CENTER[0], rect)
        cy = self._px_y(FIRST_PUBLIC_CENTER[1], rect)
        piece = 0.016 * rect.width()
        gap = piece * 1.45
        per_row = 6
        rows = 2
        total_w = (per_row - 1) * gap
        total_h = (rows - 1) * gap
        for idx in range(min(int(n), 12)):
            r_i = idx // per_row
            c_i = idx % per_row
            px = cx - total_w / 2 + c_i * gap
            py = cy - total_h / 2 + r_i * gap
            self._draw_top_piece(p, px, py, piece)

    def _draw_top_piece(self, p, x, y, s):
        """塔顶：一个 半红半蓝 的小方块（对三角）。"""
        p.setPen(QPen(Qt.black, 0.7))
        p.setBrush(QBrush(C_RED))
        tri1 = QPainterPath()
        tri1.moveTo(x, y)
        tri1.lineTo(x + s, y)
        tri1.lineTo(x, y + s)
        tri1.closeSubpath()
        p.drawPath(tri1)
        p.setBrush(QBrush(C_BLUE))
        tri2 = QPainterPath()
        tri2.moveTo(x + s, y)
        tri2.lineTo(x + s, y + s)
        tri2.lineTo(x, y + s)
        tri2.closeSubpath()
        p.drawPath(tri2)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x, y, s, s))

    # ---------------- 机器人位置小球（TR/BR，白色描边） ----------------
    def _draw_robots(self, p, rect):
        for color in ("red", "blue"):
            team = (self.team_state or {}).get(color)
            if team is None:
                continue
            robot_col = C_RED if color == "red" else C_BLUE
            # TR 小球：重置区用 TR 重置区位置，其它区域用对应区域位置
            tr_pos = (ROBOT_POS["tr_reset"][color] if team.tr_zone == "reset"
                      else ROBOT_POS[team.tr_zone][color])
            self._robot_ball(p, rect, tr_pos, robot_col, offset=(-10, -10), dot=False)
            # BR 小球：在“建塔处(l1/l1_public/l2)”落在具体建塔处（用 SLOT_POSITIONS）；
            # 重置区用 BR 重置区位置，其它区域用对应区域位置。
            if team.br_zone in ("l1", "l1_public", "l2"):
                sid = team.br_at_slot
                if not sid or sid not in SLOT_POSITIONS:
                    sid = _BR_SLOT_FALLBACK[team.br_zone][color]
                br_pos = SLOT_POSITIONS[sid]
            elif team.br_zone == "reset":
                br_pos = ROBOT_POS["br_reset"][color]
            else:
                br_pos = ROBOT_POS[team.br_zone][color]
            self._robot_ball(p, rect, br_pos, robot_col, offset=(12, 12), dot=True)

    def _robot_ball(self, p, rect, pos, color, offset, dot):
        x = self._px_x(pos[0] + offset[0], rect)
        y = self._px_y(pos[1] + offset[1], rect)
        r = 0.012 * rect.width()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255)))   # 白色描边
        p.drawEllipse(QPointF(x, y), r + 2.5, r + 2.5)
        p.setBrush(QBrush(color))                    # 队伍色
        p.drawEllipse(QPointF(x, y), r, r)
        if dot:                                      # BR 中心加白点以区分 TR
            p.setBrush(QBrush(QColor(255, 255, 255)))
            p.drawEllipse(QPointF(x, y), r * 0.35, r * 0.35)

