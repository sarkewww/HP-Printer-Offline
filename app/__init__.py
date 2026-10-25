"""HP Offline —— 局域网 HP 打印机离线控制台（纯本地，零云端）。

本包只包含后端逻辑：
    app.server       HTTP 服务（stdlib ThreadingHTTPServer）
    app.store        SQLite 持久化
    app.hp.ipp       IPP 2.0 客户端（打印）
    app.hp.ledm      LEDM 客户端（状态 / 耗材 / 计数器 / 维护）
    app.hp.escl      eSCL 客户端（扫描）
    app.hp.discovery 设备发现（WS-D / mDNS / SNMP / 子网扫描）
    app.hp.render    页面栅格化（PDF / 图片 → baseline JPEG）
    app.hp.service   业务服务层（任务线程、缓存、事件推送）
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

__version__ = "1.0.0"

#: 应用根目录（hp-offline/）
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
DATA_DIR = os.path.join(APP_DIR, "data")
UI_DIR = os.path.join(APP_DIR, "ui")
LOG_PATH = os.path.join(DATA_DIR, "hp_offline.log")

_LOG_READY = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化日志：控制台 + 轮转文件 app/data/hp_offline.log。幂等。"""
    global _LOG_READY
    root = logging.getLogger("hp")
    if _LOG_READY:
        return root

    os.makedirs(DATA_DIR, exist_ok=True)
    root.setLevel(level)
    root.propagate = False
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    fh = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(level)
    root.addHandler(fh)

    sh = logging.StreamHandler(stream=sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(level)
    root.addHandler(sh)

    _LOG_READY = True
    return root


def get_logger(name: str) -> logging.Logger:
    """返回 hp.* 命名空间下的 logger。"""
    if not name.startswith("hp."):
        name = "hp." + name
    return logging.getLogger(name)
