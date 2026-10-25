"""HP 设备协议实现集合（IPP / LEDM / eSCL / 发现 / 渲染）。

全部基于 Python 标准库，仅渲染模块依赖 PyMuPDF 与 Pillow。
不发起任何公网请求。

异常类型集中定义在本模块，避免额外模块文件：
    HpError          协议/设备操作失败的基类（message 为中文）
    PrinterOffline   设备不可达（TCP 连接失败 / 超时）
    ProtocolError    设备返回了非预期内容
"""

from __future__ import annotations


class HpError(Exception):
    """设备交互失败基类。``message`` 面向用户，使用中文。"""

    def __init__(self, message: str, detail: str = "", code: str = "device_error"):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.code = code

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message, "detail": self.detail}


class PrinterOffline(HpError):
    """打印机不可达。"""

    def __init__(self, message: str = "打印机不在线或网络不可达", detail: str = ""):
        super().__init__(message, detail, code="printer_offline")


class ProtocolError(HpError):
    """设备响应不符合协议预期。"""

    def __init__(self, message: str = "打印机返回了无法解析的数据", detail: str = ""):
        super().__init__(message, detail, code="protocol_error")


__all__ = ["HpError", "PrinterOffline", "ProtocolError"]
