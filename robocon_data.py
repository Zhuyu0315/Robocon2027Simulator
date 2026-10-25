# -*- coding: utf-8 -*-
"""数据与配置定义：比赛配置、常量、建塔处、队伍状态、分区操作定义。

本模块只包含纯数据（dataclass/常量），不含任何 Qt 依赖，
供「绘图(robocon_map)」「内部逻辑(robocon_engine)」「界面(robocon_ui)」共用。
手动分区模拟模型：每个机器人在某个区域，携带清单为物品类型列表。
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Config:
    match_duration: int = 180
    carry_score: int = 5
    score_L1 = {"base": 10, "mid": 20, "top": 40}
    score_L2 = {"base": 20, "mid": 40, "top": 80}
    five_color_score: int = 250


# 携带上限：TR 最多 3 个、BR 最多 2 个
TR_CARRY_LIMIT = 3
BR_CARRY_LIMIT = 2

# 区域名（机器人可停留的位置）
TR_ZONES = ["reset", "storage", "public", "stone_base", "transfer"]
BR_ZONES = ["reset", "transfer", "l1", "l1_public", "l2", "central"]

# 物品类型 -> 中文名（用于状态显示与下拉选择）
ITEM_LABEL = {"block": "塔基/中段", "top": "塔顶", "stone": "五色石"}
LABEL2ITEM = {v: k for k, v in ITEM_LABEL.items()}
# BR 从传递区拿取时可选的物品类型
BR_TAKE_ITEMS = ["塔基/中段", "塔顶", "五色石"]


@dataclass
class BuildSlot:
    id: str                 # 编号，如 "R1", "B1", "P1", "L2-1"
    team: str               # 所属："red" / "blue" / "shared"
    level: str              # "L1" / "L2"
    base: Optional[str] = None
    mid: Optional[str] = None
    top: Optional[str] = None   # 塔顶朝上的颜色

    @property
    def pos(self) -> Tuple[float, float]:
        # 在 roadmap.png 上的绝对像素坐标
        return SLOT_POSITIONS[self.id]


# 场地底图 roadmap.png 的像素尺寸（以下所有“绝对像素坐标”均以此图为基准，
# x 向右、y 向下，原点在图片左上角；区域坐标参见各自注释）
IMAGE_W = 1461
IMAGE_H = 1351

# ---------------- 建塔处（每座塔的落点）绝对像素中心 ----------------
# 坐标含义：(中心x像素, 中心y像素)
SLOT_POSITIONS = {
    # R1=红方L1专属·上方建塔处    R2=红方L1专属·下方建塔处
    "R1": (373, 296), "R2": (373, 963),
    # B1=蓝方L1专属·上方建塔处    B2=蓝方L1专属·下方建塔处
    "B1": (1088, 296), "B2": (1088, 963),
    # P1=L1公共·上方建塔处        P2=L1公共·下方建塔处
    "P1": (731, 296), "P2": (729, 963),
    # L2-1..L2-4=L2层(公共)四个角的建塔处
    "L2-1": (565, 454), "L2-2": (896, 454),
    "L2-3": (565, 765), "L2-4": (896, 765),
}

# ---------------- 基座 / 各区中心或矩形（绝对像素） ----------------
CENTRAL_BASE_POS = (731, 588)       # 中央基座（安放五色石处，在 L2 中央）
FIVE_COLOR_BASE_POS = (731, 147)    # 五色石基座（原始基座，顶部中央）
RED_STORAGE_RECT = (20, 16, 256, 100)        # 红方储存区 (x0,y0,w,h)，左下角
BLUE_STORAGE_RECT = (1188, 16, 256, 100)     # 蓝方储存区 (x0,y0,w,h)，右上角
FIRST_PUBLIC_CENTER = (715, 1170)   # 地面第一公共区·塔顶棋盘中心（底部中央）
RED_TRANSFER_RECT = (209, 724, 123, 118)     # 红方传递区 (x0,y0,w,h)，左侧中部
BLUE_TRANSFER_RECT = (1129, 703, 124, 142)   # 蓝方传递区 (x0,y0,w,h)，右侧中部


@dataclass
class TeamState:
    color: str
    name: str
    tr_zone: str = "reset"                 # TR 所在区域
    br_zone: str = "reset"                 # BR 所在区域（综合区域）
    br_at_slot: Optional[str] = None       # BR 具体所在的建塔处编号（如 B1/P1/L2-2）
    tr_busy_until: float = 0.0
    br_busy_until: float = 0.0
    tr_carry: List[str] = field(default_factory=list)     # TR 携带物品类型
    br_carry: List[str] = field(default_factory=list)     # BR 携带物品类型
    stored_blocks: int = 20                # 储存区剩余 塔基/中段（同一库存）
    public_tops: int = 12                  # 公共区剩余 塔顶
    stone_on_base: bool = True             # 五色石是否还在五色石基座上（双方共用）
    stone_placed: bool = False             # 是否已安放中央基座
    transfer_floor: List[str] = field(default_factory=list)  # 传递区地面的物品
    tr_task: Optional[str] = None
    br_task: Optional[str] = None
    carry_points: int = 0
    build_points: int = 0


class Operation:
    """一个可点的操作。robot=tr/br；kind=move/take/place/reset。"""

    def __init__(self, key, label, robot, kind, default_time,
                 zone=None, dest=None, target_options=None, section=""):
        self.key = key
        self.label = label
        self.robot = robot      # "tr" / "br"
        self.kind = kind        # "move" / "take" / "place" / "reset"
        self.default_time = default_time
        self.zone = zone        # 执行该操作所需的当前区域（move/reset 除外）
        self.dest = dest        # move 的目标区域
        self.target_options = target_options or []
        self.needs_target = bool(self.target_options)
        self.section = section  # 界面分组标题


def _op(key, label, robot, kind, sec, section, zone=None, dest=None, targets=None):
    return Operation(key, label, robot, kind, sec,
                     zone=zone, dest=dest, target_options=targets or [], section=section)


def build_operations() -> List[Operation]:
    ops = []
    # ---------- TR：移动 / 拿取 / 放置 / 重置 ----------
    ops.append(_op("tr_move_storage", "TR → 储存区", "tr", "move", 3.0, "TR 移动", dest="storage"))
    ops.append(_op("tr_move_public", "TR → 地面公共区", "tr", "move", 3.0, "TR 移动", dest="public"))
    ops.append(_op("tr_move_stone_base", "TR → 五色石基座", "tr", "move", 3.0, "TR 移动", dest="stone_base"))
    ops.append(_op("tr_move_transfer", "TR → 传递区", "tr", "move", 3.0, "TR 移动", dest="transfer"))
    ops.append(_op("tr_take_block", "TR 拿 塔基/中段", "tr", "take", 2.0, "TR 拿取", zone="storage"))
    ops.append(_op("tr_take_top", "TR 拿 塔顶", "tr", "take", 2.0, "TR 拿取", zone="public"))
    ops.append(_op("tr_take_stone", "TR 拿 五色石", "tr", "take", 4.0, "TR 拿取", zone="stone_base"))
    # TR 放置：按物品类型，分“放到传递区地面”与“直接交给 BR”
    for key, lbl, itype in (
        ("block", "塔基/中段", "block"), ("top", "塔顶", "top"), ("stone", "五色石", "stone"),
    ):
        ops.append(_op(f"tr_place_floor_{itype}", f"TR 放 {lbl} 到传递区地面", "tr", "place", 2.0,
                       "TR 放置", zone="transfer"))
        ops.append(_op(f"tr_hand_br_{itype}", f"TR 交给 BR {lbl}", "tr", "place", 2.0,
                       "TR 放置", zone="transfer"))
    ops.append(_op("tr_reset", "TR 回 重置区(清空并归还)", "tr", "reset", 4.0, "TR 重置"))
    # ---------- BR：移动 / 拿取 / 放置 / 重置 ----------
    ops.append(_op("br_move_transfer", "BR → 传递区", "br", "move", 3.0, "BR 移动", dest="transfer"))
    ops.append(_op("br_move_l1", "BR → L1建塔处", "br", "move", 3.0, "BR 移动",
                   dest="l1", targets=["R1", "R2", "B1", "B2"]))
    ops.append(_op("br_move_l1_public", "BR → L1公共建塔处", "br", "move", 3.0, "BR 移动",
                   dest="l1_public", targets=["P1", "P2"]))
    ops.append(_op("br_move_l2", "BR → L2建塔处", "br", "move", 3.0, "BR 移动",
                   dest="l2", targets=["L2-1", "L2-2", "L2-3", "L2-4"]))
    ops.append(_op("br_move_central", "BR → 中央基座", "br", "move", 3.0, "BR 移动", dest="central"))
    ops.append(_op("br_take_block", "BR 拿 塔基/中段", "br", "take", 2.0, "BR 拿取", zone="transfer"))
    ops.append(_op("br_take_top", "BR 拿 塔顶", "br", "take", 2.0, "BR 拿取", zone="transfer"))
    ops.append(_op("br_take_stone", "BR 拿 五色石", "br", "take", 2.0, "BR 拿取", zone="transfer"))
    # BR 放置：放“塔基/中段”与放“塔顶”各为一个按钮（每组建塔处）
    _br_build_zones = (
        ("l1", "L1建塔处", ["R1", "R2", "B1", "B2"]),
        ("l1_public", "L1公共建塔处", ["P1", "P2"]),
        ("l2", "L2建塔处", ["L2-1", "L2-2", "L2-3", "L2-4"]),
    )
    for zone_key, zone_lbl, targets in _br_build_zones:
        ops.append(_op(f"br_place_{zone_key}_block", f"BR 放 塔基/中段 到{zone_lbl}", "br", "place",
                       3.0, "BR 放置", zone=zone_key, targets=targets))
        ops.append(_op(f"br_place_{zone_key}_top", f"BR 放 塔顶 到{zone_lbl}", "br", "place",
                       3.0, "BR 放置", zone=zone_key, targets=targets))
    ops.append(_op("br_place_central", "BR 放 五色石 到中央基座", "br", "place", 4.0, "BR 放置", zone="central"))
    # BR 翻转塔顶：把塔顶朝上颜色翻成己方（夺取对方全塔，规则 3.5.8）
    for zone_key, zone_lbl, targets in _br_build_zones:
        ops.append(_op(f"br_flip_{zone_key}", f"BR 翻 {zone_lbl} 的塔顶", "br", "flip",
                       2.0, "BR 翻转塔顶", zone=zone_key, targets=targets))
    ops.append(_op("br_reset", "BR 回 重置区(清空并归还)", "br", "reset", 4.0, "BR 重置"))
    return ops
