"""LEDM 客户端：状态 / 告警 / 耗材 / 计数器 / 纸张 / 配置 / 维护动作。

LEDM 是 HP 在 80 端口暴露的一堆 XML 资源（EWS 后端）。本模块只做 GET/POST，
全部为设备本地地址，不涉及任何云端服务。

已验证端点（见 docs/protocol.md）：
    /DevMgmt/ProductStatusDyn.xml     状态 + 告警表
    /DevMgmt/ConsumableConfigDyn.xml  墨盒 / 墨量
    /DevMgmt/ProductConfigDyn.xml     型号 / 序列号 / 固件 / UUID
    /DevMgmt/ProductUsageDyn.xml      打印 / 扫描计数器
    /DevMgmt/MediaHandlingDyn.xml     纸盒 / 就绪纸张
    /DevMgmt/NetAppsDyn.xml           主机名（mDNS 域名）
    /DevMgmt/InternalPrintDyn.xml     维护动作（POST，JobType=cleaningPage…）
    /Calibration/CalibrationManifest.xml 校准会话

⚠️ 端口必须是 **80**；3911 返回 500。
"""

from __future__ import annotations

import gzip
import http.client
import socket
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from .. import get_logger
from . import HpError, PrinterOffline, ProtocolError

log = get_logger("hp.ledm")

LEDM_PORT = 80

PATH_STATUS = "/DevMgmt/ProductStatusDyn.xml"
PATH_CONSUMABLE = "/DevMgmt/ConsumableConfigDyn.xml"
PATH_CONFIG = "/DevMgmt/ProductConfigDyn.xml"
PATH_USAGE = "/DevMgmt/ProductUsageDyn.xml"
PATH_MEDIA = "/DevMgmt/MediaHandlingDyn.xml"
PATH_NETAPPS = "/DevMgmt/NetAppsDyn.xml"
PATH_INTERNAL_PRINT = "/DevMgmt/InternalPrintDyn.xml"
PATH_INTERNAL_PRINT_CAP = "/DevMgmt/InternalPrintCap.xml"
PATH_CALIBRATION_STATE = "/Calibration/State"
PATH_CALIBRATION_SESSION = "/Calibration/Session"

#: 状态分类 → (应用状态, 中文说明)
STATUS_CATEGORY_MAP: Dict[str, Tuple[str, str]] = {
    "ready": ("idle", "就绪"),
    "inPowerSave": ("idle", "就绪（电源节省）"),
    "genuineHP": ("idle", "就绪"),
    "antiTheftEnabledSupplyDetected": ("idle", "就绪"),
    "processing": ("processing", "正在处理"),
    "copying": ("processing", "正在复印"),
    "scanProcessing": ("processing", "正在扫描"),
    "calibrating": ("processing", "正在校准"),
    "initializing": ("processing", "正在初始化"),
    "inkSystemInitializing": ("processing", "墨水系统初始化中"),
    "shuttingDown": ("processing", "正在关机"),
    "cancelJob": ("processing", "正在取消任务"),
    "jamInPrinter": ("stopped", "卡纸：请打开检修门取出纸张"),
    "carriageJam": ("stopped", "墨车卡纸：请清除障碍物"),
    "closeDoorOrCover": ("stopped", "请关闭打印机盖门"),
    "cartridgeMissing": ("stopped", "墨盒缺失"),
    "cartridgeFailure": ("stopped", "墨盒故障"),
    "cartridgeAltered": ("stopped", "检测到墨盒被改动"),
    "cartridgeInWrongOrder": ("stopped", "墨盒安装顺序错误"),
    "cartridgeLow": ("idle", "墨水量低"),
    "cartridgeVeryLow": ("idle", "墨水量严重不足"),
    "nonHPSupplyDetected": ("stopped", "检测到非原装耗材"),
    "incompatibleConsumable": ("stopped", "耗材不兼容"),
    "usedConsumable": ("stopped", "检测到已使用过的耗材"),
    "printerError": ("stopped", "打印机错误"),
    "scannerError": ("stopped", "扫描仪错误"),
    "calibrationRequired": ("stopped", "需要校准"),
    "sizeMismatchInTray": ("stopped", "纸张尺寸与设置不匹配"),
    "trayEmptyOrOpen": ("stopped", "纸盒缺纸或未关闭"),
    "trayOpen": ("stopped", "纸盒未关闭"),
    "trayClosed": ("stopped", "纸盒已关闭"),
    "outputBinClosed": ("stopped", "出纸盒已关闭"),
    "removeMedia": ("stopped", "请取走出纸盒中的纸张"),
    "improperShutdown": ("idle", "上次异常关机"),
    "sharedAddressError": ("stopped", "IP 地址冲突"),
    "BBCMediaDetected": ("idle", "检测到特殊纸张"),
    "cartridgeSubsystemMaintenanceNeeded": ("stopped", "墨盒系统需要维护"),
}

#: 告警 ID → (API 分类, 中文消息)
ALERT_MAP: Dict[str, Tuple[str, str]] = {
    "cartridgeLow": ("supplyLow", "墨水量低"),
    "cartridgeVeryLow": ("supplyLow", "墨水量严重不足"),
    "cartridgeMissing": ("supplyEmpty", "墨盒缺失"),
    "cartridgeFailure": ("error", "墨盒故障"),
    "incompatibleConsumable": ("error", "耗材不兼容"),
    "nonHPSupplyDetected": ("info", "检测到非原装耗材"),
    "usedConsumable": ("info", "检测到已使用过的耗材"),
    "cartridgeAltered": ("error", "墨盒被改动"),
    "cartridgeInWrongOrder": ("error", "墨盒顺序错误"),
    "jamInPrinter": ("jam", "打印机内部卡纸"),
    "carriageJam": ("jam", "墨车卡纸"),
    "closeDoorOrCover": ("doorOpen", "盖门未关闭"),
    "trayEmptyOrOpen": ("mediaEmpty", "纸盒缺纸或未关闭"),
    "trayOpen": ("mediaEmpty", "纸盒未关闭"),
    "sizeMismatchInTray": ("mediaMismatch", "纸张尺寸不匹配"),
    "calibrationRequired": ("calibration", "需要校准"),
    "improperShutdown": ("info", "上次异常关机"),
    "printerError": ("error", "打印机错误"),
    "scannerError": ("error", "扫描仪错误"),
    "sharedAddressError": ("error", "IP 地址冲突"),
    "cartridgeSubsystemMaintenanceNeeded": ("error", "墨盒系统需要维护"),
    "removeMedia": ("mediaMismatch", "请取走出纸盒中的纸张"),
    "outputBinClosed": ("error", "出纸盒已关闭"),
}

#: 耗材标签代码 → (key, 中文名, 默认颜色)
CONSUMABLE_LABEL_MAP: Dict[str, Tuple[str, str, str]] = {
    "K": ("black", "黑色墨水", "#000000"),
    "CMY": ("color", "三色墨水", "#00A0E9"),
}

#: 维护动作 → InternalPrintDyn JobType
MAINTENANCE_JOB_TYPES: Dict[str, str] = {
    "clean": "cleaningPage",
    "deep_clean": "cleaningPageLevel2",
    "align": "cleaningVerificationPage",
    "calibrate": "cleaningVerificationPage",
    "report": "configurationPage",
    "network": "networkSummary",
}

MAINTENANCE_LABELS: Dict[str, str] = {
    "clean": "打印头清洗",
    "deep_clean": "深度清洗",
    "align": "打印头对齐",
    "calibrate": "颜色校准",
    "report": "打印配置页",
    "network": "打印网络摘要",
}

#: InternalPrintDyn 的 15 种 JobType 中文名（本机 InternalPrintCap 实测）
INTERNAL_PRINT_LABELS: Dict[str, str] = {
    "cleaningPage": "打印头清洗",
    "cleaningPageLevel2": "深度清洗",
    "cleaningVerificationPage": "清洗验证页",
    "configurationPage": "配置页",
    "extendedConfigurationPage": "扩展配置页",
    "demoPage": "演示页",
    "diagnosticsPage": "诊断页",
    "pqDiagnosticsPage": "打印质量诊断页",
    "networkSummary": "网络摘要",
    "networkDiagnosticPage": "网络诊断页",
    "wirelessNetworkPage": "无线网络报告",
    "paperFeedCleaningPage": "进纸清洁页",
    "ribSmearCleaningPage": "墨迹拖尾清洁页",
    "eventLogReport": "事件日志报告",
    "webAccessReport": "网页访问报告",
}

#: 分组，供 UI 分栏展示
INTERNAL_PRINT_GROUPS: Dict[str, str] = {
    "cleaningPage": "clean",
    "cleaningPageLevel2": "clean",
    "cleaningVerificationPage": "clean",
    "paperFeedCleaningPage": "clean",
    "ribSmearCleaningPage": "clean",
    "configurationPage": "report",
    "extendedConfigurationPage": "report",
    "demoPage": "report",
    "diagnosticsPage": "report",
    "pqDiagnosticsPage": "report",
    "eventLogReport": "report",
    "webAccessReport": "report",
    "networkSummary": "network",
    "networkDiagnosticPage": "network",
    "wirelessNetworkPage": "network",
}


# ---------------------------------------------------------------------------
# XML 工具（忽略命名空间，按 local-name 查找）
# ---------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_all(elem: ET.Element, local_name: str) -> List[ET.Element]:
    return [node for node in elem.iter() if _local(node.tag) == local_name]


def _first(elem: Optional[ET.Element], local_name: str) -> Optional[ET.Element]:
    if elem is None:
        return None
    for node in elem.iter():
        if _local(node.tag) == local_name:
            return node
    return None


def _text(elem: Optional[ET.Element], local_name: str, default: Optional[str] = None) -> Optional[str]:
    node = _first(elem, local_name)
    if node is None or node.text is None:
        return default
    value = node.text.strip()
    return value if value else default


def _texts(elem: Optional[ET.Element], local_name: str) -> List[str]:
    out: List[str] = []
    if elem is None:
        return out
    for node in elem.iter():
        if _local(node.tag) == local_name and node.text is not None:
            value = node.text.strip()
            if value:
                out.append(value)
    return out


def _child(elem: Optional[ET.Element], local_name: str) -> Optional[ET.Element]:
    if elem is None:
        return None
    for node in list(elem):
        if _local(node.tag) == local_name:
            return node
    return None


def _children(elem: Optional[ET.Element], local_name: str) -> List[ET.Element]:
    if elem is None:
        return []
    return [node for node in list(elem) if _local(node.tag) == local_name]


def _int_or(value: Optional[str], default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _rgb_hex(elem: Optional[ET.Element]) -> Optional[str]:
    """从 ``dd:FillColor`` 结构取 ``#RRGGBB``。"""
    node = _first(elem, "FillColor")
    if node is None:
        return None
    red = _int_or(_text(node, "Red"), -1)
    green = _int_or(_text(node, "Green"), -1)
    blue = _int_or(_text(node, "Blue"), -1)
    if min(red, green, blue) < 0:
        return None
    return "#%02X%02X%02X" % (red, green, blue)


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class LedmClient:
    """80 端口 LEDM 资源客户端。"""

    def __init__(self, host: str, port: int = LEDM_PORT, timeout: float = 6.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._xml_cache: Dict[str, Tuple[float, ET.Element]] = {}

    # -- 传输 -------------------------------------------------------------
    def get(self, path: str, timeout: Optional[float] = None) -> bytes:
        """GET 原始字节（自动解 gzip）。"""
        timeout = timeout if timeout is not None else self.timeout
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            conn.request("GET", path, headers={"Accept-Encoding": "gzip", "Connection": "close"})
            resp = conn.getresponse()
            data = resp.read()
            if resp.status != 200:
                raise HpError(
                    "读取设备资源失败：%s（HTTP %d）" % (path, resp.status),
                    detail=data[:200].decode("utf-8", "replace"),
                    code="ledm_http_error",
                )
            encoding = (resp.getheader("Content-Encoding") or "").lower()
            if "gzip" in encoding:
                try:
                    data = gzip.decompress(data)
                except OSError as exc:
                    raise ProtocolError("设备返回的 gzip 数据无法解压", detail=str(exc))
            return data
        except (socket.timeout, TimeoutError) as exc:
            raise PrinterOffline("读取设备状态超时（%s）" % self.host, str(exc))
        except (ConnectionError, OSError) as exc:
            raise PrinterOffline(
                "无法连接打印机（%s:%d）" % (self.host, self.port),
                "%s: %s" % (type(exc).__name__, exc),
            )
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass

    def get_xml(self, path: str, cache_seconds: float = 0.0,
                timeout: Optional[float] = None) -> ET.Element:
        """GET 并解析 XML（可选短期缓存）。"""
        if cache_seconds > 0:
            cached = self._xml_cache.get(path)
            if cached and time.time() - cached[0] < cache_seconds:
                return cached[1]
        raw = self.get(path, timeout=timeout)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ProtocolError(
                "无法解析设备返回的 XML：%s" % path,
                detail="%s | %s" % (exc, raw[:120].decode("utf-8", "replace")),
            )
        if cache_seconds > 0:
            self._xml_cache[path] = (time.time(), root)
        return root

    def post_xml(self, path: str, body: str, content_type: str = "text/xml",
                 timeout: Optional[float] = None) -> Tuple[int, bytes]:
        """POST XML（维护动作）。返回 (status, body)。"""
        timeout = timeout if timeout is not None else self.timeout
        payload = body.encode("utf-8")
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            conn.request(
                "POST",
                path,
                body=payload,
                headers={"Content-Type": content_type, "Content-Length": str(len(payload))},
            )
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, data
        except (socket.timeout, TimeoutError) as exc:
            raise PrinterOffline("维护指令超时（%s）" % self.host, str(exc))
        except (ConnectionError, OSError) as exc:
            raise PrinterOffline(
                "无法连接打印机（%s:%d）" % (self.host, self.port),
                "%s: %s" % (type(exc).__name__, exc),
            )
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass

    # -- 各资源 -----------------------------------------------------------
    def product_status(self) -> Dict[str, Any]:
        """解析 ProductStatusDyn：状态 + 告警。"""
        root = self.get_xml(PATH_STATUS, cache_seconds=1.0)
        status_node = _first(root, "Status")
        category = _text(status_node, "StatusCategory", "unknown")
        string_id = _text(status_node, "StringId")

        state, message = STATUS_CATEGORY_MAP.get(category, ("unknown", "状态未知"))

        alerts: List[Dict[str, str]] = []
        alert_table = _first(root, "AlertTable")
        for entry in _children(alert_table, "AlertEntry"):
            alert_id = (
                _text(entry, "ProductStatusAlertID")
                or _text(entry, "StatusCategory")
                or _text(entry, "AlertID")
                or ""
            )
            severity = _text(entry, "Severity") or _text(entry, "AlertSeverity") or ""
            details: List[str] = []
            for node in entry.iter():
                name = _local(node.tag)
                if name in ("ProductStatusAlertID", "StatusCategory", "SequenceNumber",
                            "Severity", "AlertSeverity", "StringId", "AlertDetails"):
                    continue
                if node.text and node.text.strip():
                    details.append("%s=%s" % (name, node.text.strip()))
            if not alert_id and not details:
                continue
            category_out, default_message = ALERT_MAP.get(
                alert_id, ("info", "设备提示：%s" % (alert_id or "未知告警"))
            )
            if "error" in severity.lower() and category_out == "info":
                category_out = "error"
            alerts.append(
                {
                    "category": category_out,
                    "message": default_message,
                    "id": alert_id,
                    "severity": severity,
                    "detail": "; ".join(details),
                }
            )
        return {
            "state": state,
            "state_category": category,
            "state_message": message,
            "state_string_id": string_id,
            "alerts": alerts,
        }

    def consumables(self) -> List[Dict[str, Any]]:
        """解析 ConsumableConfigDyn → supplies 列表。

        墨仓机型 ``ConsumablePercentageLevelRemaining`` 恒为 0（设备不提供百分比），
        按契约映射为 ``level: -1``（前端显示「未知」）。
        """
        root = self.get_xml(PATH_CONSUMABLE, cache_seconds=5.0)
        supplies: List[Dict[str, Any]] = []
        for info in _find_all(root, "ConsumableInfo"):
            code = (_text(info, "ConsumableLabelCode") or "").strip().upper()
            key, label, default_color = CONSUMABLE_LABEL_MAP.get(
                code, (code.lower() or "supply", "耗材", "#888888")
            )
            icon = _first(info, "ConsumableIcon")
            color = _rgb_hex(icon) or default_color
            # 纯白填充色对墨水没有意义（三色墨盒图标 FillColor 为 255,255,255）
            if color.upper() == "#FFFFFF":
                color = default_color

            raw_level = _text(info, "ConsumablePercentageLevelRemaining")
            level = _int_or(raw_level, 0)
            if level <= 0:
                level = -1  # 设备不提供百分比

            life_state = _first(info, "ConsumableLifeState")
            consumable_state = (_text(life_state, "ConsumableState") or "").strip()
            measured = (_text(life_state, "MeasuredQuantityState") or "").strip()

            state = "ok"
            lowered = consumable_state.lower()
            if "verylow" in lowered or "empty" in lowered or "depleted" in lowered:
                state = "empty"
            elif "low" in lowered:
                state = "low"
            elif level >= 0:
                if level <= 5:
                    state = "empty"
                elif level <= 15:
                    state = "low"

            supplies.append(
                {
                    "key": key,
                    "label": label,
                    "color": color,
                    "level": level,
                    "state": state,
                    "kind": "ink",
                    "code": code,
                    "consumable_state": consumable_state,
                    "measured_state": measured,
                }
            )
        # 黑色放前面更符合直觉
        supplies.sort(key=lambda s: 0 if s["key"] == "black" else 1)
        return supplies

    def usage(self) -> Dict[str, int]:
        """解析 ProductUsageDyn → 计数器。"""
        root = self.get_xml(PATH_USAGE, cache_seconds=10.0)
        printer_subunit = _first(root, "PrinterSubunit")
        scanner_subunit = _first(root, "ScannerEngineSubunit")
        total_pages = _int_or(_text(printer_subunit, "TotalImpressions"), 0)
        jam_events = _int_or(_text(printer_subunit, "JamEvents"), 0)
        scan_pages = _int_or(_text(scanner_subunit, "ScanImages"), 0)
        if scan_pages == 0:
            scan_pages = _int_or(_text(scanner_subunit, "FlatbedImages"), 0)
        return {
            "total_pages": total_pages,
            "scan_pages": scan_pages,
            "jam_events": jam_events,
        }

    def media(self) -> Dict[str, Any]:
        """解析 MediaHandlingDyn → 就绪纸张 / 纸盒。"""
        root = self.get_xml(PATH_MEDIA, cache_seconds=10.0)
        trays = _find_all(root, "InputTray")
        ready = None
        tray_name = None
        media_type = None
        for tray in trays:
            tray_state = (_text(tray, "TrayState") or "").lower()
            if tray_state and tray_state not in ("installed", "ok", "ready"):
                continue
            size = _text(tray, "MediaSizeName")
            if size:
                ready = size
                tray_name = _text(tray, "InputBin") or _text(tray, "InputTrayName")
                media_type = _text(tray, "MediaType")
                break
        return {"ready": ready, "tray": tray_name, "type": media_type}

    def product_config(self) -> Dict[str, Any]:
        """解析 ProductConfigDyn → 型号 / 序列号 / 固件 / UUID。"""
        root = self.get_xml(PATH_CONFIG, cache_seconds=60.0)
        info = _first(root, "ProductInformation")
        model = _text(info, "MakeAndModel") or _text(info, "MakeAndModelBase")
        version_node = _child(info, "Version")
        firmware = _text(version_node, "Revision")
        config = {
            "model": model,
            "serial": _text(info, "SerialNumber"),
            "uuid": _text(info, "UUID"),
            "firmware": firmware,
            "product_number": _text(info, "ProductNumber"),
            "name": None,
            "hostname": None,
        }
        try:
            net = self.get_xml(PATH_NETAPPS, cache_seconds=120.0)
            config["hostname"] = _text(net, "DomainName")
            config["name"] = _text(net, "ApplicationServiceName")
        except HpError as exc:
            log.debug("读取 NetAppsDyn 失败（可忽略）: %s", exc)
        return config

    def calibration_state(self) -> Optional[str]:
        try:
            root = self.get_xml(PATH_CALIBRATION_STATE, timeout=4.0)
        except HpError as exc:
            log.debug("读取校准状态失败: %s", exc)
            return None
        return (root.text or "").strip() or None

    # -- 组合 -------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        """一次性取状态 + 耗材 + 计数器 + 纸张（并行度靠调用方决定）。"""
        result: Dict[str, Any] = {"online": True}
        errors: List[str] = []
        try:
            result.update(self.product_status())
        except HpError as exc:
            errors.append("状态：%s" % exc.message)
            raise
        try:
            result["supplies"] = self.consumables()
        except HpError as exc:
            errors.append("耗材：%s" % exc.message)
            result["supplies"] = []
        try:
            result["counters"] = self.usage()
        except HpError as exc:
            errors.append("计数器：%s" % exc.message)
            result["counters"] = {"total_pages": 0, "scan_pages": 0, "jam_events": 0}
        try:
            result["media"] = self.media()
        except HpError as exc:
            errors.append("纸张：%s" % exc.message)
            result["media"] = {"ready": None, "tray": None, "type": None}
        if errors:
            log.warning("部分 LEDM 资源读取失败（%s）: %s", self.host, "；".join(errors))
            result["partial_errors"] = errors
        return result

    # -- 维护 -------------------------------------------------------------
    def reports(self) -> Dict[str, Any]:
        """读取 /DevMgmt/InternalPrintCap.xml，返回本机真实支持的报告/维护作业类型。

        注意：本机 /Copy/Jobs 实测挂死无响应（45s 超时），因此不提供原生复印；
        复印由 service 层用「扫描 → 打印」流水线实现。
        """
        try:
            root = self.get_xml(PATH_INTERNAL_PRINT_CAP, cache_seconds=300)
        except HpError as exc:
            log.warning("读取 InternalPrintCap 失败: %s", exc)
            return {"job_types": [], "items": []}
        types: List[str] = []
        for el in root.iter():
            if el.tag.split("}")[-1] == "JobType" and el.text:
                value = el.text.strip()
                if value and value not in types:
                    types.append(value)
        items = [
            {
                "job_type": t,
                "label": INTERNAL_PRINT_LABELS.get(t, t),
                "group": INTERNAL_PRINT_GROUPS.get(t, "other"),
            }
            for t in types
        ]
        return {"job_types": types, "items": items}

    def maintenance(self, action: str) -> Dict[str, Any]:
        """执行维护动作。

        ``clean``/``deep_clean``/``report``/``network`` → POST InternalPrintDyn.xml
        ``align``/``calibrate`` → 优先 POST /Calibration/Session，失败回退内部打印页
        """
        action = (action or "").strip().lower()
        if action not in MAINTENANCE_JOB_TYPES:
            raise HpError(
                "不支持的维护动作：%s" % action,
                detail="可选：clean, deep_clean, align, calibrate, report, network",
                code="bad_request",
            )
        label = MAINTENANCE_LABELS.get(action, action)

        if action in ("align", "calibrate"):
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<cal:CalibrationSession '
                'xmlns:cal="http://www.hp.com/schemas/imaging/con/cnx/markingagentcalibration/2009/04/08">'
                "<cal:CalibrationType>Calibration</cal:CalibrationType>"
                "</cal:CalibrationSession>"
            )
            try:
                status, data = self.post_xml(PATH_CALIBRATION_SESSION, body, timeout=20)
            except HpError as exc:
                log.warning("校准会话请求失败，回退内部打印页: %s", exc)
                status, data = -1, b""
            if 200 <= status < 300:
                return {
                    "ok": True,
                    "detail": "已提交%s请求，设备将开始校准流程" % label,
                    "endpoint": PATH_CALIBRATION_SESSION,
                    "http_status": status,
                }
            log.info(
                "校准会话不可用（HTTP %s），改为打印对齐页", status
            )

        job_type = MAINTENANCE_JOB_TYPES[action]
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ipdyn:InternalPrintDyn '
            'xmlns:ipdyn="http://www.hp.com/schemas/imaging/con/ledm/internalprintdyn/2008/03/21">'
            "<ipdyn:JobType>%s</ipdyn:JobType>"
            "</ipdyn:InternalPrintDyn>" % job_type
        )
        status, data = self.post_xml(PATH_INTERNAL_PRINT, body, timeout=20)
        if 200 <= status < 300:
            return {
                "ok": True,
                "detail": "已提交%s（%s），请稍候观察打印机" % (label, job_type),
                "endpoint": PATH_INTERNAL_PRINT,
                "http_status": status,
                "job_type": job_type,
            }
        raise HpError(
            "设备拒绝了%s请求（HTTP %d）" % (label, status),
            detail=data[:200].decode("utf-8", "replace"),
            code="maintenance_failed",
        )


def fetch_device_info(host: str, timeout: float = 6.0) -> Dict[str, Any]:
    """探测主机是否是 HP 设备：返回 ProductConfigDyn 解析结果。

    失败抛 :class:`PrinterOffline` / :class:`ProtocolError`。
    """
    client = LedmClient(host, timeout=timeout)
    return client.product_config()
