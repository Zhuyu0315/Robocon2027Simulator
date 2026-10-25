# -*- coding: utf-8 -*-
"""用户界面（前端）：构建队伍面板（分区操作按钮）、计分/时钟/日志。

本模块负责“展示与交互”：把用户点击转发给 GameEngine，
并把引擎的实时状态刷新到界面控件与地图上。
"""
import os
from datetime import datetime
from typing import List, Optional
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QPushButton, QLabel, QGroupBox, QTextEdit, QDialog, QScrollArea,
    QMessageBox, QComboBox, QDoubleSpinBox, QSpinBox, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QFontMetrics

from robocon_data import (TeamState, Operation, build_operations,
                          TR_CARRY_LIMIT, BR_CARRY_LIMIT,
                          TR_ZONES, BR_ZONES, ITEM_LABEL)
from robocon_map import MapWidget
from robocon_engine import GameEngine
from robocon_paths import output_dir

_ZONE_NAME = {
    "reset": "重置区", "storage": "储存区", "public": "公共区",
    "stone_base": "五色石基座", "transfer": "传递区",
    "l1": "L1建塔处", "l1_public": "L1公共建塔处", "l2": "L2建塔处",
    "central": "中央基座",
}

# ---- 每行控件宽度（单位：像素；红蓝两队共用同一套键）----
# 每个键对应一行；btn=按钮宽度, combo=该行下拉框宽度, spin=该行时间框宽度。
# 行里没有的控件（如“移动”无时间框）可不写对应键，缺省时用下面的默认值。
ROW_WIDTH = {
    "tr_move":        {"btn": 140, "combo": 230},
    "tr_take":        {"btn": 140, "combo": 150, "spin": 80},
    "tr_place_floor": {"btn": 140, "combo": 150, "spin": 80},
    "tr_hand_br":     {"btn": 140, "combo": 150, "spin": 80},
    "br_move":        {"btn": 140, "combo": 230},
    "br_take":        {"btn": 140, "combo": 150, "spin": 80},
    "br_place_block": {"btn": 140, "combo": 150,  "spin": 80},
    "br_place_top":   {"btn": 140, "combo": 150,  "spin": 80},
    "br_place_central": {"btn": 295, "spin": 80},
    "br_flip":        {"btn": 140, "combo": 150,  "spin": 80},
    "tr_reset":       {"btn": 295, "spin": 80},
    "br_reset":       {"btn": 295, "spin": 80},
}
# 缺省宽（某行未写对应字段时用）
_DEF_BTN = 120
_DEF_COMBO = 100
_DEF_SPIN = 80



def _zone_of_slot(sid: str) -> str:
    """由建塔处编号得到 BR 所在综合区域。"""
    if sid in ("P1", "P2"):
        return "l1_public"
    if sid.startswith("L2"):
        return "l2"
    return "l1"


class SimulatorWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.engine = GameEngine()
        self.engine.load_settings()   # 读取保存的设置（移动时间），无则用默认值
        self.time_scale = 1.0
        self.operations = build_operations()
        self.op_map = {o.key: o for o in self.operations}
        self.action_buttons: dict = {"red": [], "blue": []}   # 供启用/禁用
        self.reset_buttons: dict = {"red": [], "blue": []}    # 重置按钮（自身等宽）
        self.setting_rows: dict = {"red": [], "blue": []}     # 供“保存设置”收集各行耗时
        self.status_labels: dict = {"red": {}, "blue": {}}
        self._build_ui()
        self._refresh_scoreboard()
        self._refresh_robot_status()
        self.tick_timer = QTimer(self)
        self.tick_timer.setInterval(100)
        self.tick_timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------ 布局
    def _build_ui(self):
        self.setWindowTitle("女娲补天 竞技赛 手动模拟器 (Robocon 2027)")
        self.resize(1340, 920)
        root = QHBoxLayout(self)
        root.addWidget(self._build_team_panel("red"))
        root.addWidget(self._build_center())
        root.addWidget(self._build_team_panel("blue"))

    def _build_team_panel(self, color: str) -> QGroupBox:
        box = QGroupBox(("红方 操作面板" if color == "red" else "蓝方 操作面板"))
        box.setStyleSheet(
            f"QGroupBox {{ color: {'red' if color=='red' else 'blue'}; font-weight: bold; }}")
        v = QVBoxLayout(box)
        v.setSpacing(5)

        # ---- 顶部：机器人状态 + 携带数 ----
        status_box = QGroupBox("机器人状态")
        status_box.setStyleSheet("font-weight: bold;")
        sv = QVBoxLayout(status_box)
        sv.setContentsMargins(6, 4, 6, 4)
        sv.setSpacing(4)
        st_font = QFont()
        st_font.setPointSize(11)
        st_font.setBold(True)
        self.status_labels[color] = {
            k: QLabel(t) for k, t in (
                ("tr", "TR：空闲"),
                ("tr_carry", f"TR 携带：0/{self.engine.tr_limit}"),
                ("br", "BR：空闲"),
                ("br_carry", f"BR 携带：0/{self.engine.br_limit}"),
            )
        }
        for lbl in self.status_labels[color].values():
            lbl.setFont(st_font)
            sv.addWidget(lbl)
        sp = status_box.sizePolicy()
        sp.setVerticalPolicy(QSizePolicy.Fixed)
        status_box.setSizePolicy(sp)
        v.addWidget(status_box)

        # ---- 紧凑的操作区：同一类动作收进下拉框（不改规则逻辑）----
        t_font = QFont()
        t_font.setPointSize(10)
        fm = QFontMetrics(t_font)
        hh = int(fm.height() * 2.0)      # 按钮高度 = 字体高度的 2 倍
        own_l1 = ["R1", "R2"] if color == "red" else ["B1", "B2"]
        l2s = ["L2-1", "L2-2", "L2-3", "L2-4"]
        place_slots = own_l1 + ["P1", "P2"] + l2s
        item_lbl = ["塔基/中段", "塔顶", "五色石"]
        item_map = {"塔基/中段": "block", "塔顶": "top", "五色石": "stone"}
        tr_dest = ["储存区", "公共区", "五色石基座", "传递区"]
        tr_zone = {"储存区": "storage", "公共区": "public",
                   "五色石基座": "stone_base", "传递区": "transfer"}

        def header(text):
            h = QLabel(text)
            h.setFont(st_font)
            v.addWidget(h)

        def mk_combo(items, key=None, width=None):
            cb = QComboBox()
            cb.addItems(list(items))
            cb.setFont(t_font)
            w = width if width is not None else ROW_WIDTH.get(key, {}).get("combo", _DEF_COMBO)
            cb.setFixedWidth(w)
            cb.setFixedHeight(hh)
            return cb

        def mk_spin(default, key=None, fixed=True, width=None):
            s = QDoubleSpinBox()
            s.setRange(0.5, 60.0)
            s.setValue(default)
            s.setSingleStep(0.5)
            if fixed:
                w = width if width is not None else ROW_WIDTH.get(key, {}).get("spin", _DEF_SPIN)
                s.setFixedWidth(w)
            s.setFixedHeight(hh)
            s.setSuffix("s")
            s.setFont(t_font)
            s.setAlignment(Qt.AlignCenter)   # 数字居中
            return s

        def add_row(label, widgets, key):
            row = QHBoxLayout()
            btn = QPushButton(label)
            btn.setFont(t_font)
            btn.setFixedWidth(ROW_WIDTH.get(key, {}).get("btn", _DEF_BTN))   # 每行按钮单独宽度
            btn.setFixedHeight(hh)
            btn.setStyleSheet("padding:2px;")            # 默认正中，不靠右
            row.addWidget(btn)
            for w in widgets:
                row.addWidget(w)
            v.addLayout(row)
            self.action_buttons[color].append(btn)
            return btn

        def add_setting_row(ops, spin):
            self.setting_rows[color].append({"ops": list(ops), "time": spin})

        # ===== TR =====
        header("TR 搬运（地面区）")
        # TR 移动
        cb_dst = mk_combo(tr_dest, key="tr_move")
        add_setting_row([f"tr_move_{z}" for z in tr_zone.values()], None)
        add_row("移动", [cb_dst], "tr_move").clicked.connect(
            lambda: self._go(color, f"tr_move_{tr_zone[cb_dst.currentText()]}", None, None))
        # TR 拿取
        cb_item = mk_combo(item_lbl, key="tr_take")
        sp = mk_spin(self.engine.op_duration.get("tr_take_block", 2.0), key="tr_take")
        add_setting_row(["tr_take_block", "tr_take_top", "tr_take_stone"], sp)
        add_row("拿取", [cb_item, sp], "tr_take").clicked.connect(
            lambda: self._go(color, f"tr_take_{item_map[cb_item.currentText()]}", None, sp.value()))
        # TR 放到传递区地面 / 直接交给 BR
        for label, prefix, bkey in (("放到地面", "tr_place_floor_", "tr_place_floor"),
                                    ("交给BR", "tr_hand_br_", "tr_hand_br")):
            cb = mk_combo(item_lbl, key=bkey)
            s2 = mk_spin(self.engine.op_duration.get(f"{prefix}block", 2.0), key=bkey)
            add_setting_row([f"{prefix}{x}" for x in ("block", "top", "stone")], s2)
            add_row(label, [cb, s2], bkey).clicked.connect(
                lambda _, p=prefix, c=cb, s=s2: self._go(color, f"{p}{item_map[c.currentText()]}", None, s.value()))

        # ===== BR =====
        header("BR 建筑（传递区/L1/L2/中央）")
        # BR 移动（目的地含具体建塔处）
        br_move_opts = []
        for sid in place_slots:
            if sid in own_l1:
                br_move_opts.append((sid, "br_move_l1", sid))
            elif sid in ("P1", "P2"):
                br_move_opts.append((sid, "br_move_l1_public", sid))
            else:
                br_move_opts.append((sid, "br_move_l2", sid))
        br_move_opts = [("传递区", "br_move_transfer", None),
                        ("中央基座", "br_move_central", None)] + br_move_opts
        cb_dst2 = mk_combo([o[0] for o in br_move_opts], key="br_move")
        add_setting_row([o[1] for o in br_move_opts], None)
        def br_move():
            for disp, key, tgt in br_move_opts:
                if disp == cb_dst2.currentText():
                    self._go(color, key, tgt, None)
                    return
        add_row("移动", [cb_dst2], "br_move").clicked.connect(br_move)
        # BR 拿取
        cb_bt = mk_combo(item_lbl, key="br_take")
        sp_b = mk_spin(self.engine.op_duration.get("br_take_block", 2.0), key="br_take")
        add_setting_row(["br_take_block", "br_take_top", "br_take_stone"], sp_b)
        add_row("拿取", [cb_bt, sp_b], "br_take").clicked.connect(
            lambda: self._go(color, f"br_take_{item_map[cb_bt.currentText()]}", None, sp_b.value()))
        # BR 放置（参照 TR：一行一个目标下拉 + 耗时，按“塔基/中段”和“塔顶”分开）
        def add_place(label, typ, ops, bkey):
            cb_slot = mk_combo(place_slots, key=bkey)
            sp = mk_spin(self.engine.op_duration.get(ops[0], 3.0), key=bkey)
            add_setting_row(ops, sp)
            def run():
                sid = cb_slot.currentText()
                self._go(color, f"br_place_{_zone_of_slot(sid)}_{typ}", sid, sp.value())
            add_row(label, [cb_slot, sp], bkey).clicked.connect(run)
        add_place("放塔基/中段", "block", [f"br_place_{z}_block" for z in ("l1", "l1_public", "l2")], "br_place_block")
        add_place("放塔顶", "top", [f"br_place_{z}_top" for z in ("l1", "l1_public", "l2")], "br_place_top")
        # BR 放五色石到中央基座
        sp_c = mk_spin(self.engine.op_duration.get("br_place_central", 4.0), key="br_place_central")
        add_setting_row(["br_place_central"], sp_c)
        add_row("放五色石", [sp_c], "br_place_central").clicked.connect(
            lambda: self._go(color, "br_place_central", None, sp_c.value()))
        # BR 翻转塔顶
        cb_fslot = mk_combo(place_slots, key="br_flip")
        sp_f = mk_spin(self.engine.op_duration.get("br_flip_l1", 2.0), key="br_flip")
        add_setting_row([f"br_flip_{z}" for z in ("l1", "l1_public", "l2")], sp_f)
        def br_flip():
            sid = cb_fslot.currentText()
            self._go(color, f"br_flip_{_zone_of_slot(sid)}", sid, sp_f.value())
        add_row("翻转塔顶", [cb_fslot, sp_f], "br_flip").clicked.connect(br_flip)

        # 重置：按钮与时间框宽度均写死（不再按比例伸展）
        header("重置")
        def add_reset_row(label, key):
            sp = mk_spin(self.engine.op_duration.get(key, 4.0), key=key)
            add_setting_row([key], sp)
            row = QHBoxLayout()
            btn = QPushButton(label)
            btn.setFont(t_font)
            btn.setFixedWidth(ROW_WIDTH.get(key, {}).get("btn", _DEF_BTN))
            btn.setFixedHeight(hh)
            btn.setStyleSheet("padding:2px;")   # 默认正中
            row.addWidget(btn)
            row.addWidget(sp)
            v.addLayout(row)
            self.reset_buttons[color].append(btn)
            btn.clicked.connect(lambda: self._go(color, key, None, sp.value()))
        add_reset_row("TR 回重置区", "tr_reset")
        add_reset_row("BR 回重置区", "br_reset")
        return box

    def _build_center(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        # 比分行：固定一行高度，不参与抢多余空间
        self.score_label = QLabel()
        self.score_label.setAlignment(Qt.AlignCenter)
        self.score_label.setFont(QFont("", 14, QFont.Bold))
        sp = self.score_label.sizePolicy()
        sp.setVerticalPolicy(QSizePolicy.Fixed)
        self.score_label.setSizePolicy(sp)
        self._refresh_scoreboard()
        v.addWidget(self.score_label, 0)

        # 地图：占主要面积（1:1 不拉伸）
        self.map_widget = MapWidget(self.engine.cfg, self, engine=self.engine)
        v.addWidget(self.map_widget, 1)

        ctrl = QHBoxLayout()
        self.start_btn = QPushButton("▶ 开始比赛 (3分钟)")
        self.start_btn.setFont(QFont("", 12, QFont.Bold))
        self.start_btn.clicked.connect(self._start_match)
        self.time_label = QLabel("剩余时间: 03:00")
        self.time_label.setFont(QFont("", 13))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["1x", "2x", "5x", "10x"])
        self.speed_combo.currentTextChanged.connect(self._change_speed)
        ctrl.addWidget(self.start_btn)
        ctrl.addStretch(1)
        ctrl.addWidget(QLabel("倍速:"))
        ctrl.addWidget(self.speed_combo)
        ctrl.addStretch(1)
        ctrl.addWidget(self.time_label)
        ctrl.addSpacing(10)
        self.setting_btn = QPushButton("⚙ 移动时间设置")
        self.setting_btn.setFont(QFont("", 11))
        self.setting_btn.clicked.connect(self._open_settings)
        ctrl.addWidget(self.setting_btn)
        self.save_btn = QPushButton("💾 保存设置")
        self.save_btn.setFont(QFont("", 11))
        self.save_btn.clicked.connect(self._save_settings)
        ctrl.addWidget(self.save_btn)
        v.addLayout(ctrl)

        # 日志：放开高度上限，多出来的空间主要给日志（stretch=2）
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(90)
        v.addWidget(self.log_view, 2)
        return w

    # ------------------------------------------------------------------ 交互
    def _change_speed(self, text: str):
        self.time_scale = float(text.replace("x", ""))

    def _save_settings(self):
        # 收集每一行（一行对应一类动作）的耗时，写入各底层动作的默认耗时
        for row in self.setting_rows.get("red", []):
            if row["time"] is not None:
                for k in row["ops"]:
                    self.engine.op_duration[k] = row["time"].value()
        if self.engine.save_settings():
            QMessageBox.information(self, "保存设置", "设置已保存到 robocon_settings.json，下次启动会自动读取。")
        else:
            QMessageBox.warning(self, "保存设置", "保存失败。")

    def _open_settings(self):
        """参数设置：比赛时长、携带上限、地图移动时间。改动实时写入引擎。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("移动时间设置")
        root = QVBoxLayout(dlg)
        from PyQt5.QtWidgets import QScrollArea
        area = QScrollArea()
        area.setWidgetResizable(True)
        content = QWidget()
        v = QVBoxLayout(content)
        v.setSpacing(8)

        # ---- 比赛时长 / 携带上限 ----
        gb = QGroupBox("比赛参数")
        gl = QGridLayout(gb)
        gl.setSpacing(4)
        md_lab = QLabel("比赛时长(秒):")
        md_lab.setFont(QFont("", 11))
        md_sp = QDoubleSpinBox()
        md_sp.setRange(60, 600)
        md_sp.setValue(self.engine.match_duration)
        md_sp.setSingleStep(10)
        md_sp.valueChanged.connect(lambda val: setattr(self.engine, "match_duration", val))
        tr_lab = QLabel("TR 携带上限:")
        tr_lab.setFont(QFont("", 11))
        tr_sp = QSpinBox()
        tr_sp.setRange(1, 5)
        tr_sp.setValue(self.engine.tr_limit)
        tr_sp.valueChanged.connect(lambda val: setattr(self.engine, "tr_limit", val))
        br_lab = QLabel("BR 携带上限:")
        br_lab.setFont(QFont("", 11))
        br_sp = QSpinBox()
        br_sp.setRange(1, 5)
        br_sp.setValue(self.engine.br_limit)
        br_sp.valueChanged.connect(lambda val: setattr(self.engine, "br_limit", val))
        gl.addWidget(md_lab, 0, 0); gl.addWidget(md_sp, 0, 1)
        gl.addWidget(tr_lab, 1, 0); gl.addWidget(tr_sp, 1, 1)
        gl.addWidget(br_lab, 2, 0); gl.addWidget(br_sp, 2, 1)
        v.addWidget(gb)

        # ---- 移动时间（地点对，左右并排以节省纵向空间）----
        travel_row = QHBoxLayout()
        travel_row.setSpacing(8)
        for robot, title in (("tr", "TR 移动时间 (秒)"), ("br", "BR 移动时间 (秒)")):
            tgb = QGroupBox(title)
            tgrid = QGridLayout(tgb)
            tgrid.setSpacing(4)
            for r, (a, b) in enumerate(self.engine.travel_pairs(robot)):
                lab = QLabel(f"{_ZONE_NAME.get(a, a)} → {_ZONE_NAME.get(b, b)}")
                lab.setFont(QFont("", 11))
                sp = QDoubleSpinBox()
                sp.setRange(0.5, 60.0)
                sp.setSingleStep(0.5)
                sp.setValue(self.engine.get_travel(robot, a, b))
                sp.setSuffix(" s")
                sp.setFixedWidth(70)
                sp.valueChanged.connect(
                    lambda val, rr=robot, aa=a, bb=b: self.engine.set_travel(rr, aa, bb, val))
                tgrid.addWidget(lab, r, 0)
                tgrid.addWidget(sp, r, 1)
            travel_row.addWidget(tgb, 1)
        v.addLayout(travel_row)

        tip = QLabel("改完直接生效；点主界面「保存设置」可持久化，下次启动自动读取。")
        tip.setFont(QFont("", 10))
        v.addWidget(tip)
        area.setWidget(content)
        root.addWidget(area)
        dlg.resize(760, 900)
        dlg.exec_()

    def _set_inputs_enabled(self, enabled: bool):
        for color in ("red", "blue"):
            for btn in self.action_buttons[color]:
                btn.setEnabled(enabled)
            for btn in self.reset_buttons[color]:
                btn.setEnabled(enabled)

    # ------------------------------------------------------------------ 比赛流程
    def _start_match(self):
        if self.engine.match_started:
            return
        self.engine.start_match()
        self.log_view.clear()
        self.start_btn.setEnabled(False)
        self._set_inputs_enabled(True)
        self._log("==== 比赛开始 ====")
        self._refresh_scoreboard()
        self._refresh_robot_status()
        self.map_widget.update()
        self.tick_timer.start()

    def _on_tick(self):
        if self.engine.match_over:
            return
        remaining = self.engine.tick(0.1 * self.time_scale)
        self._refresh_scoreboard()
        self._refresh_robot_status()
        mins = int(remaining) // 60
        secs = int(remaining) % 60
        self.time_label.setText(f"剩余时间: {mins:02d}:{secs:02d}")
        if remaining <= 0:
            self._end_match()

    # ------------------------------------------------------------------ 操作
    def _go(self, color: str, op_key: str, target: Optional[str], duration: Optional[float]):
        """由下拉/按钮解析出的具体动作（键 + 目标 + 耗时）派发。"""
        op = self.op_map[op_key]
        if not self.engine.match_started or self.engine.match_over:
            return
        team = self.engine.state[color]
        robot = op.robot
        if self.engine.is_busy(color, robot) and op.kind != "reset":
            self._log(f"[{team.name}] {op.label} 被拒绝："
                      f"{'TR' if robot=='tr' else 'BR'} 正在执行其他操作")
            return
        if op.kind == "move":   # 移动耗时 = 起点→终点 的地点对时间
            src = team.tr_zone if robot == "tr" else team.br_zone
            duration = self.engine.get_travel(robot, src, op.dest)
        elif duration is None:
            duration = op.default_time
        # 前置校验：不合格直接拒绝，不进入计时
        err = self.engine.validate(color, op, target)
        if err:
            self._log(f"[{team.name}] {op.label} 被拒绝：{err}")
            return
        self._log(f"[{team.name}] 开始：{op.label}"
                  + (f"（目标:{target}）" if target else "")
                  + f"  预计 {duration:.1f}s")
        self.engine.mark_busy(color, robot, duration, op.label)
        self._refresh_robot_status()
        real_delay_ms = int(duration / self.time_scale * 1000)
        QTimer.singleShot(real_delay_ms, lambda: self._complete_op(color, op, target))

    def _complete_op(self, color: str, op, target: Optional[str]):
        if self.engine.match_over:
            return
        self.engine.clear_task(color, op.robot)
        for line in self.engine.execute(color, op, target):
            self.log_view.append(line)
        self._scroll_log()
        self._refresh_scoreboard()
        self._refresh_robot_status()
        self.map_widget.update()

    # ------------------------------------------------------------------ 显示刷新
    def _refresh_robot_status(self):
        for color in ("red", "blue"):
            team = self.engine.state[color]
            labels = self.status_labels.get(color, {})
            if not labels:
                continue
            labels["tr"].setText("TR：" + self._robot_status_text(team, "tr"))
            labels["tr_carry"].setText(f"TR 携带：{self._carry_text(team.tr_carry)}（{len(team.tr_carry)}/{self.engine.tr_limit}）")
            labels["br"].setText("BR：" + self._robot_status_text(team, "br"))
            labels["br_carry"].setText(f"BR 携带：{self._carry_text(team.br_carry)}（{len(team.br_carry)}/{self.engine.br_limit}）")

    def _carry_text(self, carry) -> str:
        """把携带清单转成中文描述，如 塔基/中段×2、塔顶×1。"""
        counts = {t: carry.count(t) for t in ("block", "top", "stone")}
        parts = [f"{ITEM_LABEL[t]}×{c}" for t, c in counts.items() if c]
        return "、".join(parts) if parts else "空"

    def _robot_status_text(self, team: TeamState, which: str) -> str:
        zone = team.tr_zone if which == "tr" else team.br_zone
        zone_name = _ZONE_NAME.get(zone, zone)
        if which == "tr":
            busy_until = team.tr_busy_until
            task = team.tr_task
        else:
            busy_until = team.br_busy_until
            task = team.br_task
        if self.engine.elapsed < busy_until:
            rem = max(0.0, busy_until - self.engine.elapsed)
            return f"{task or '执行中'}(剩{rem:.1f}s)@{zone_name}"
        return f"空闲@{zone_name}"

    def _refresh_scoreboard(self):
        r, b = self.engine.state["red"], self.engine.state["blue"]
        rs = r.carry_points + r.build_points
        bs = b.carry_points + b.build_points
        self.score_label.setTextFormat(Qt.RichText)
        self.score_label.setText(
            f"<span style='color:red'>红方 {rs} 分</span>"
            f"&nbsp;&nbsp;VS&nbsp;&nbsp;"
            f"<span style='color:blue'>蓝方 {bs} 分</span>")

    def _log(self, msg: str):
        line = self.engine.log_line(msg)
        self.log_view.append(line)
        self._scroll_log()

    def _scroll_log(self):
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------ 结束
    def _end_match(self):
        self.engine.end_match_mark()
        self.tick_timer.stop()
        self._set_inputs_enabled(False)
        self.start_btn.setEnabled(True)
        r, b = self.engine.state["red"], self.engine.state["blue"]
        rs = r.carry_points + r.build_points
        bs = b.carry_points + b.build_points
        if rs == bs:
            if r.stone_placed and not b.stone_placed:
                winner = "红方"
            elif b.stone_placed and not r.stone_placed:
                winner = "蓝方"
            else:
                winner = "平局(由裁判组裁定)"
        else:
            winner = "红方" if rs > bs else "蓝方"
        self._log("==== 比赛结束 ====")
        self._log(f"最终得分 — 红方: {rs}   蓝方: {bs}")
        self._log(f"五色石 — 红方: {'已安放' if r.stone_placed else '未'}   "
                  f"蓝方: {'已安放' if b.stone_placed else '未'}")
        self._log(f"获胜方: 【{winner}】")
        QMessageBox.information(
            self, "比赛结束",
            f"红方 {rs} : {bs} 蓝方\n\n获胜方：【{winner}】\n\n（详细操作日志见界面下方）")
        self._export_log(winner, rs, bs)

    def _export_log(self, winner: str, rs: int, bs: int):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(output_dir(), f"match_log_{ts}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("女娲补天竞技赛 模拟器 操作日志\n")
                f.write(f"时间: {datetime.now()}\n")
                f.write(f"总时长: {self.engine.match_duration}s\n")
                f.write("=" * 50 + "\n")
                for line in self.engine.log:
                    f.write(line + "\n")
                f.write("=" * 50 + "\n")
                f.write(f"红方总分: {rs}\n蓝方总分: {bs}\n")
                f.write(f"获胜方: {winner}\n")
            self._log(f"(日志已导出: {path})")
        except Exception as e:
            self._log(f"(日志导出失败: {e})")
