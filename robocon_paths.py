# -*- coding: utf-8 -*-
"""运行路径辅助：区分“源码运行”与“PyInstaller 打包后的 exe”两种情况。

- 资源目录 resource_dir()：打包后指向 PyInstaller 解包目录(_MEIPASS，内含 roadmap.png)，
  源码运行时指向脚本目录。
- 可写输出目录 output_dir()：打包后指向 exe 所在目录(用于写 robocon_settings.json 与日志)，
  源码运行时指向脚本目录。
"""
import os
import sys


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> str:
    """含打包资源（如 roadmap.png）的目录。"""
    if _frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))


def output_dir() -> str:
    """可写输出目录（设置文件、日志）。"""
    if _frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
