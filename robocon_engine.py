# -*- coding: utf-8 -*-
"""游戏内部逻辑：GameEngine 持有全部比赛状态，执行分区的移动/拿取/放置/重置。

本模块不依赖 Qt（纯 Python 逻辑），
界面(robocon_ui)与地图(robocon_map)都从它读取实时状态。
手动分区模型：
  - 每队机器人在某区域(tr_zone/br_zone)；携带清单(tr_carry/br_carry)为物品类型列表。
  - 物品类型：block=塔基/中段、top=塔顶、stone=五色石。
"""
from typing import List, Optional
import json
import os

from robocon_data import (Config, BuildSlot, TeamState,
                          TR_CARRY_LIMIT, BR_CARRY_LIMIT,
                          TR_ZONES, BR_ZONES, build_operations,
                          ITEM_LABEL)
from robocon_paths import output_dir

_SETTINGS_PATH = os.path.join(output_dir(), "robocon_settings.json")
DEFAULT_TRAVEL = 3.0

_ZONE_NAME = {
    "reset": "重置区", "storage": "储存区", "public": "公共区",
    "stone_base": "五色石基座", "transfer": "传递区",
    "l1": "L1建塔处", "l1_public": "L1公共建塔处", "l2": "L2建塔处",
    "central": "中央基座",
}

# BR 放置到建塔处的动作键（放塔基/中段 与 放塔顶 分开）
_BR_PLACE_BUILD_KEYS = {
    f"br_place_{z}_{k}" for z in ("l1", "l1_public", "l2") for k in ("block", "top")
}


class GameEngine:
    """比赛引擎：状态 + 规则 + 计时，不含任何界面/绘制代码。"""

    def __init__(self):
        self.cfg = Config()
        self.state = {"red": TeamState(color="red", name="红方"),
                      "blue": TeamState(color="blue", name="蓝方")}
        self.slots: List[BuildSlot] = self._make_slots()
        self.stone_placed_by: Optional[str] = None
        self.log: List[str] = []
        self.match_started = False
        self.match_over = False
        self.elapsed = 0.0
        # 可配置参数（可从设置文件载入/保存）
        self.match_duration = self.cfg.match_duration
        self.tr_limit = TR_CARRY_LIMIT
        self.br_limit = BR_CARRY_LIMIT
        self.op_duration = {o.key: o.default_time for o in build_operations()}
        # 地图移动时间（按“每两个地点”一对，对称，单位秒）
        self.travel = {"tr": self._default_travel(TR_ZONES),
                       "br": self._default_travel(BR_ZONES)}

    @staticmethod
    def _default_travel(zones: List[str]) -> dict:
        d = {}
        for i in range(len(zones)):
            for j in range(i + 1, len(zones)):
                d[(zones[i], zones[j])] = DEFAULT_TRAVEL
        return d

    def get_travel(self, robot: str, a: str, b: str) -> float:
        key = (a, b) if (a, b) in self.travel[robot] else (b, a)
        return self.travel[robot].get(key, DEFAULT_TRAVEL)

    def set_travel(self, robot: str, a: str, b: str, t: float):
        key = (a, b) if (a, b) in self.travel[robot] else (b, a)
        self.travel[robot][key] = t

    def travel_pairs(self, robot: str):
        return sorted(self.travel[robot].keys())

    # ------------------------------------------------------------------ 设置存取
    def load_settings(self):
        """读取 robocon_settings.json；存在则应用，否则用默认值。"""
        if not os.path.exists(_SETTINGS_PATH):
            return
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.match_duration = float(data.get("match_duration", self.cfg.match_duration))
            limits = data.get("carry_limit", {})
            self.tr_limit = int(limits.get("tr", TR_CARRY_LIMIT))
            self.br_limit = int(limits.get("br", BR_CARRY_LIMIT))
            for key, val in data.get("op_duration", {}).items():
                if key in self.op_duration:
                    self.op_duration[key] = float(val)
            travel = data.get("travel", {})
            for robot in ("tr", "br"):
                m = travel.get(robot, {})
                for key, val in m.items():
                    a, b = key.split("|")
                    self.set_travel(robot, a, b, float(val))
        except Exception:
            pass   # 读取失败就保持默认

    def save_settings(self):
        """把全部参数写回 robocon_settings.json。"""
        data = {
            "match_duration": self.match_duration,
            "carry_limit": {"tr": self.tr_limit, "br": self.br_limit},
            "op_duration": dict(self.op_duration),
            "travel": {"tr": {}, "br": {}},
        }
        for robot in ("tr", "br"):
            for (a, b), t in self.travel[robot].items():
                data["travel"][robot][f"{a}|{b}"] = t
        try:
            with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    @staticmethod
    def _make_slots() -> List[BuildSlot]:
        return [
            BuildSlot("R1", "red", "L1"), BuildSlot("R2", "red", "L1"),
            BuildSlot("B1", "blue", "L1"), BuildSlot("B2", "blue", "L1"),
            BuildSlot("P1", "shared", "L1"), BuildSlot("P2", "shared", "L1"),
            BuildSlot("L2-1", "shared", "L2"), BuildSlot("L2-2", "shared", "L2"),
            BuildSlot("L2-3", "shared", "L2"), BuildSlot("L2-4", "shared", "L2"),
        ]

    # ------------------------------------------------------------------ 计时 / 流程
    def reset(self):
        self.state["red"] = TeamState(color="red", name="红方")
        self.state["blue"] = TeamState(color="blue", name="蓝方")
        for s in self.slots:
            s.base = None
            s.mid = None
            s.top = None
        self.stone_placed_by = None
        self.log = []
        self.elapsed = 0.0

    def start_match(self):
        self.reset()
        self.match_started = True
        self.match_over = False

    def tick(self, dt: float) -> float:
        if self.match_over:
            return 0.0
        self.elapsed += dt
        remaining = max(0.0, self.match_duration - self.elapsed)
        if remaining <= 0:
            self.match_over = True
        return remaining

    def end_match_mark(self):
        self.match_over = True
        self.match_started = False

    def log_line(self, msg: str) -> str:
        line = f"[{self.elapsed:6.1f}s] {msg}"
        self.log.append(line)
        return line

    # ------------------------------------------------------------------ 忙碌状态
    def busy_until(self, color: str, robot: str) -> float:
        team = self.state[color]
        return team.tr_busy_until if robot == "tr" else team.br_busy_until

    def is_busy(self, color: str, robot: str) -> bool:
        return self.elapsed < self.busy_until(color, robot)

    def mark_busy(self, color: str, robot: str, duration: float, task: str):
        team = self.state[color]
        if robot == "tr":
            team.tr_busy_until = self.elapsed + duration
            team.tr_task = task
        else:
            team.br_busy_until = self.elapsed + duration
            team.br_task = task

    def clear_task(self, color: str, robot: str):
        team = self.state[color]
        if robot == "tr":
            team.tr_task = None
        else:
            team.br_task = None

    # ------------------------------------------------------------------ 查询
    def get_slot(self, slot_id: str) -> Optional[BuildSlot]:
        return next((s for s in self.slots if s.id == slot_id), None)

    def protection_satisfied(self, color: str) -> bool:
        full = 0
        in_public = False
        for s in self.slots:
            if s.base and s.mid and s.top == color:
                full += 1
                if s.level == "L2" or s.team == "shared":
                    in_public = True
        return full >= 2 and in_public

    # ------------------------------------------------------------------ 前置校验
    def validate(self, color: str, op, target: Optional[str]) -> Optional[str]:
        """行动开始前检查；返回 None=可执行，否则返回拒绝原因（该行动不进入计时）。"""
        team = self.state[color]
        robot = op.robot
        carry = team.tr_carry if robot == "tr" else team.br_carry
        zone = team.tr_zone if robot == "tr" else team.br_zone
        limit = self.tr_limit if robot == "tr" else self.br_limit

        if op.kind in ("move", "reset"):
            return None

        if op.zone and zone != op.zone:
            return f"{robot.upper()} 不在 {_ZONE_NAME.get(op.zone, op.zone)}"
        if op.kind == "take" and len(carry) >= limit:
            return f"{robot.upper()} 携带已满({limit})"
        if op.kind == "flip":
            slot = self.get_slot(target) if target else None
            if slot is None:
                return f"目标 {target} 无效"
            if not slot.top:
                return f"{target} 还没有塔顶可翻转"

        if op.key == "tr_take_block" and team.stored_blocks <= 0:
            return "储存区没有 塔基/中段"
        if op.key == "tr_take_top" and team.public_tops <= 0:
            return "公共区没有 塔顶"
        if op.key == "tr_take_stone":
            if not team.stone_on_base:
                return "五色石已不在基座上"
            if not self.protection_satisfied(color):
                return "未满足保护法则（≥2座全塔且≥1座在公共区）"
        if op.key.startswith("tr_place_floor_"):
            itype = op.key[len("tr_place_floor_"):]
            if itype not in carry:
                return f"TR 手里没有 {ITEM_LABEL.get(itype, itype)}"
        if op.key.startswith("tr_hand_br_"):
            itype = op.key[len("tr_hand_br_"):]
            if itype not in carry:
                return f"TR 手里没有 {ITEM_LABEL.get(itype, itype)}"
            if team.br_zone != "transfer":
                return "BR 不在传递区"
            if len(team.br_carry) >= self.br_limit:
                return f"BR 携带已满({self.br_limit})"
        if op.key in ("br_take_block", "br_take_top", "br_take_stone"):
            itype = {"br_take_block": "block", "br_take_top": "top", "br_take_stone": "stone"}[op.key]
            if itype not in team.transfer_floor:
                return f"传递区地面没有 {ITEM_LABEL[itype]}"
        if op.key in _BR_PLACE_BUILD_KEYS:
            slot = self.get_slot(target) if target else None
            if slot is None:
                return f"目标 {target} 无效"
            itype = "top" if op.key.endswith("_top") else "block"
            if itype not in carry:
                return f"BR 手里没有 {ITEM_LABEL[itype]}"
            if itype == "top":
                if not (slot.base and slot.mid):
                    return f"{target} 需先放好 塔基+中段 才能放 塔顶"
            else:
                if slot.base is not None and slot.mid is not None:
                    return f"{target} 已放满 塔基/中段"
        if op.key == "br_place_central":
            if "stone" not in carry:
                return "BR 没有携带五色石"
            if team.stone_placed:
                return "五色石已经安放下了"
            if not self.protection_satisfied(color):
                return "未满足保护法则"
        return None

    # ------------------------------------------------------------------ 执行
    def execute(self, color: str, op, target: Optional[str]) -> List[str]:
        """执行一个已完成动作的规则效果，返回新增日志行。"""
        team = self.state[color]
        lines: List[str] = []

        def _log(msg: str):
            lines.append(self.log_line(msg))

        def _robot_carry(robot: str) -> List[str]:
            return team.tr_carry if robot == "tr" else team.br_carry

        def _robot_zone(robot: str) -> str:
            return team.tr_zone if robot == "tr" else team.br_zone

        def _set_zone(robot: str, zone: str):
            if robot == "tr":
                team.tr_zone = zone
            else:
                team.br_zone = zone

        robot = op.robot
        carry = _robot_carry(robot)
        limit = self.tr_limit if robot == "tr" else self.br_limit

        # ---------- 移动 ----------
        if op.kind == "move":
            _set_zone(robot, op.dest)
            if robot == "br":
                team.br_at_slot = target if op.dest in ("l1", "l1_public", "l2") else None
            _log(f"  ✓ {team.name} {robot.upper()} 移动到 {_ZONE_NAME.get(op.dest, op.dest)}"
                 + (f"({target})" if target else ""))
            return lines

        # ---------- 重置：回重置区，随身物品放回原区 ----------
        if op.kind == "reset":
            for item in carry:
                if item == "block":
                    team.stored_blocks += 1
                elif item == "top":
                    team.public_tops += 1
                elif item == "stone":
                    team.stone_on_base = True
            carry.clear()
            _set_zone(robot, "reset")
            if robot == "tr":
                team.tr_busy_until = 0.0
            else:
                team.br_busy_until = 0.0
            _log(f"  ↺ {team.name} {robot.upper()} 回 重置区，携带物已放回原区")
            return lines

        # ---------- 拿取 / 放置 / 翻转 ----------
        # 检查当前区域
        if op.zone and _robot_zone(robot) != op.zone:
            _log(f"  ✗ {team.name} {robot.upper()} 不在 {_ZONE_NAME.get(op.zone, op.zone)}，无法执行")
            return lines

        # ---------- 翻转塔顶（夺取）----------
        if op.kind == "flip":
            slot = self.get_slot(target) if target else None
            if slot is None:
                _log(f"  ✗ {team.name} 目标 {target} 无效")
            elif not slot.top:
                _log(f"  ✗ {team.name} {target} 还没有塔顶可翻转")
            elif slot.top == color:
                _log(f"  ✓ {team.name} {target} 塔顶朝上已是己方颜色({color})，无需翻转")
            else:
                old = slot.top
                slot.top = color
                _log(f"  ↺ {team.name} 翻转 {target} 塔顶：{old} → {color}（夺取成功）")
            return lines

        def _carry_full() -> bool:
            return len(carry) >= limit

        if op.key == "tr_take_block":
            if _carry_full():
                _log(f"  ✗ {team.name} TR 携带已满({limit})")
            elif team.stored_blocks <= 0:
                _log(f"  ✗ {team.name} 储存区没有 塔基/中段")
            else:
                team.stored_blocks -= 1
                carry.append("block")
                _log(f"  ✓ {team.name} TR 拿了 塔基/中段")
        elif op.key == "tr_take_top":
            if _carry_full():
                _log(f"  ✗ {team.name} TR 携带已满({limit})")
            elif team.public_tops <= 0:
                _log(f"  ✗ {team.name} 公共区没有 塔顶")
            else:
                team.public_tops -= 1
                carry.append("top")
                _log(f"  ✓ {team.name} TR 拿了 塔顶")
        elif op.key == "tr_take_stone":
            if _carry_full():
                _log(f"  ✗ {team.name} TR 携带已满({limit})")
            elif not team.stone_on_base:
                _log(f"  ✗ {team.name} 五色石已不在基座上")
            elif not self.protection_satisfied(color):
                _log(f"  ✗ {team.name} 未满足保护法则（≥2座全塔且≥1座在公共区），不能拿五色石")
            else:
                team.stone_on_base = False
                carry.append("stone")
                _log(f"  ✓ {team.name} TR 拿了 五色石")
        elif op.key.startswith("tr_place_floor_"):
            itype = op.key[len("tr_place_floor_"):]
            if itype not in carry:
                _log(f"  ✗ {team.name} TR 手里没有 {ITEM_LABEL.get(itype, itype)}")
            else:
                carry.remove(itype)
                team.transfer_floor.append(itype)
                if itype != "stone":
                    team.carry_points += self.cfg.carry_score
                _log(f"  ✓ {team.name} TR 放 {ITEM_LABEL.get(itype, itype)} 到传递区地面" +
                     (f" +{self.cfg.carry_score}" if itype != "stone" else ""))
        elif op.key.startswith("tr_hand_br_"):
            itype = op.key[len("tr_hand_br_"):]
            if itype not in carry:
                _log(f"  ✗ {team.name} TR 手里没有 {ITEM_LABEL.get(itype, itype)}")
            elif team.br_zone != "transfer":
                _log(f"  ✗ {team.name} BR 不在传递区，无法直接交给")
            elif len(team.br_carry) >= self.br_limit:
                _log(f"  ✗ {team.name} BR 携带已满({self.br_limit})")
            else:
                carry.remove(itype)
                team.br_carry.append(itype)
                if itype != "stone":
                    team.carry_points += self.cfg.carry_score
                _log(f"  ✓ {team.name} TR 把 {ITEM_LABEL.get(itype, itype)} 交给 BR" +
                     (f" +{self.cfg.carry_score}" if itype != "stone" else ""))
        elif op.key in ("br_take_block", "br_take_top", "br_take_stone"):
            itype = {"br_take_block": "block", "br_take_top": "top", "br_take_stone": "stone"}[op.key]
            if itype in team.transfer_floor:
                team.transfer_floor.remove(itype)
                team.br_carry.append(itype)
                _log(f"  ✓ {team.name} BR 从传递区拿了 {ITEM_LABEL[itype]}")
            else:
                _log(f"  ✗ {team.name} 传递区地面没有 {ITEM_LABEL[itype]}")
        elif op.key in _BR_PLACE_BUILD_KEYS:
            slot = self.get_slot(target) if target else None
            itype = "top" if op.key.endswith("_top") else "block"
            if slot is None:
                _log(f"  ✗ {team.name} 目标 {target} 无效")
            elif itype not in carry:
                _log(f"  ✗ {team.name} BR 手里没有 {ITEM_LABEL[itype]}")
            elif itype == "top" and not (slot.base and slot.mid):
                _log(f"  ✗ {team.name} {target} 需先放好 塔基+中段 才能放 塔顶")
            elif itype == "block" and slot.base is not None and slot.mid is not None:
                _log(f"  ✗ {team.name} {target} 已放满 塔基/中段")
            else:
                if itype == "block":
                    kind = "base" if slot.base is None else "mid"
                    if kind == "base":
                        slot.base = color
                    else:
                        slot.mid = color
                    carry.remove("block")
                    sc = self._score_of(slot)[kind]
                    team.build_points += sc
                    _log(f"  ✓ {team.name} BR 在 {target} 放 塔基/中段({kind}) +{sc}")
                else:
                    slot.top = color
                    carry.remove("top")
                    sc = self._score_of(slot)["top"]
                    team.build_points += sc
                    _log(f"  ✓ {team.name} BR 在 {target} 放 塔顶(朝上={color}) +{sc}")
        elif op.key == "br_place_central":
            if "stone" not in carry:
                _log(f"  ✗ {team.name} BR 没有携带五色石")
            elif team.stone_placed:
                _log(f"  ✗ {team.name} 五色石已经安放下了")
            elif not self.protection_satisfied(color):
                _log(f"  ✗ {team.name} 未满足保护法则，不能安放五色石")
            else:
                carry.remove("stone")
                team.stone_placed = True
                self.stone_placed_by = color
                team.build_points += self.cfg.five_color_score
                _log(f"  ★ {team.name} 五色石安放到中央基座！+{self.cfg.five_color_score}")
        else:
            _log(f"  ✓ {team.name} 操作完成：{op.key}")

        return lines

    def _score_of(self, slot: BuildSlot) -> dict:
        return self.cfg.score_L2 if slot.level == "L2" else self.cfg.score_L1
