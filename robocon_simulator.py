# -*- coding: utf-8 -*-
"""女娲补天 竞技赛 简易模拟器 —— 入口文件。

代码已按职责拆分到多个模块：
  robocon_data   —— 数据/配置/常量（纯 dataclass）
  robocon_engine —— 游戏内部逻辑与状态（GameEngine，纯 Python）
  robocon_map    —— 场地地图绘制（MapWidget）
  robocon_ui     —— 前端界面（SimulatorWindow：面板/按钮/控件）

运行：python robocon_simulator.py
"""
import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont

from robocon_ui import SimulatorWindow


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("WenQuanYi Micro Hei", 9))
    win = SimulatorWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
