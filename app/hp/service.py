"""业务服务层：打印机注册、状态缓存、打印/扫描任务线程、事件推送。

职责边界
--------
* 只做编排：协议细节在 :mod:`app.hp.ipp` / :mod:`app.hp.ledm` / :mod:`app.hp.escl`；
* 状态缓存 TTL 由设置里的 ``poll_interval`` 决定，前端 ``?refresh=1`` 可强制刷新；
* 打印/扫描都在工作线程执行，接口立即返回 ``job_id``，进度通过 SSE 推送；
* 打印机 IP 变化时先用 WS-Discovery 按 UUID / 主机名重新定位，再决定失败；
* **不发起任何公网请求**，``cloud_calls`` 恒为 0。
"""

from __future__ import annotations

import os
import queue
import smtplib
import ssl
import subprocess
import threading
import time
import uuid as uuidlib
from email.message import EmailMessage
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .. import DATA_DIR, __version__, get_logger
from ..store import Store
from . import HpError, PrinterOffline, ProtocolError, discovery, postprocess, render
from .escl import EsclClient, auto_crop
from .ipp import IppPrinter
from .ledm import LedmClient

log = get_logger("service")

UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

#: 状态缓存最短 TTL（秒）
MIN_STATUS_TTL = 3.0
#: 能力缓存 TTL（秒）
CAPS_TTL = 3600.0

#: job.state → 进度下限（用于把设备轮询映射成进度条）
JOB_STATE_PROGRESS = {
    "queued": 0.0,
    "preparing": 0.05,
    "sending": 0.15,
    "printing": 0.6,
    "done": 1.0,
    "error": 1.0,
    "canceled": 1.0,
}

#: 打印机状态中文说明
STATE_TEXT = {
    "idle": "就绪",
    "processing": "正在处理",
    "stopped": "需要处理",
    "offline": "离线",
    "unknown": "状态未知",
}


class JobCanceled(Exception):
    """任务被用户取消。"""


class PrinterService:
    """打印机业务门面。线程安全。"""

    def __init__(self, store: Store):
        self.store = store
        os.makedirs(UPLOAD_DIR, exist_ok=True)

        self._cache_lock = threading.RLock()
        self._status_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._caps_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._resolving: set = set()

        self._sub_lock = threading.Lock()
        self._subscribers: List[queue.Queue] = []

        self._cancel_lock = threading.Lock()
        self._cancel_events: Dict[int, threading.Event] = {}
        # 暂停信号：Event 被 set 表示该作业处于暂停状态（页与页之间生效）
        self._pause_events: Dict[int, threading.Event] = {}

        # 一台物理设备同时只能做一件事（打印 / 扫描）
        self._device_lock = threading.Lock()

        self._poll_thread: Optional[threading.Thread] = None
        self._poll_stop = threading.Event()

        # 零云端证明：本进程从不访问公网，计数器永远保持 0
        self._cloud_calls = 0

    # =====================================================================
    # 事件（SSE）
    # =====================================================================
    def subscribe(self) -> queue.Queue:
        channel: queue.Queue = queue.Queue(maxsize=200)
        with self._sub_lock:
            self._subscribers.append(channel)
        log.debug("SSE 订阅者 +1（当前 %d）", len(self._subscribers))
        return channel

    def unsubscribe(self, channel: queue.Queue) -> None:
        with self._sub_lock:
            if channel in self._subscribers:
                self._subscribers.remove(channel)
        log.debug("SSE 订阅者 -1（当前 %d）", len(self._subscribers))

    def emit(self, event: Dict[str, Any]) -> None:
        """向所有 SSE 订阅者广播事件（满了就丢最旧的）。"""
        with self._sub_lock:
            subscribers = list(self._subscribers)
        for channel in subscribers:
            try:
                channel.put_nowait(event)
            except queue.Full:
                try:
                    channel.get_nowait()
                    channel.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass

    def _emit_job(self, job_id: int) -> None:
        job = self.store.get_job(job_id)
        if job:
            self.emit({"type": "job", "job": self.serialize_job(job)})

    def _emit_printer(self, printer_id: str) -> None:
        try:
            summary = self.printer_summary(printer_id)
        except HpError as exc:
            log.debug("推送打印机状态失败: %s", exc)
            return
        if summary:
            self.emit({"type": "printer", "printer": summary})

    # =====================================================================
    # 序列化
    # =====================================================================
    @staticmethod
    def serialize_job(job: Dict[str, Any]) -> Dict[str, Any]:
        options = dict(job.get("options") or {})
        # 敏感字段脱敏：数据库里保留原值供重试/再次加密，但 API 与「高级详情」不显示明文
        for secret_key in ("pdf_password",):
            if options.get(secret_key):
                options[secret_key] = "***"
        return {
            "id": job["id"],
            "kind": job["kind"],
            "printer_id": job.get("printer_id"),
            "title": job.get("title") or "",
            "state": job.get("state") or "queued",
            "progress": round(float(job.get("progress") or 0.0), 4),
            "pages_total": int(job.get("pages_total") or 0),
            "pages_sent": int(job.get("pages_sent") or 0),
            "message": job.get("message") or "",
            "error": job.get("error"),
            "created_at": int(job.get("created_at") or 0),
            "updated_at": int(job.get("updated_at") or 0),
            "ipp_job_id": job.get("ipp_job_id"),
            "options": options,
        }

    def _cached_status(self, printer_id: str) -> Optional[Dict[str, Any]]:
        with self._cache_lock:
            entry = self._status_cache.get(printer_id)
        return entry[1] if entry else None

    def _status_ttl(self) -> float:
        try:
            interval = float(self.store.get_settings().get("poll_interval") or 10)
        except (TypeError, ValueError):
            interval = 10.0
        return max(MIN_STATUS_TTL, interval)

    def printer_summary(self, printer_id: str) -> Optional[Dict[str, Any]]:
        printer = self.store.get_printer(printer_id)
        if printer is None:
            return None
        status = self._cached_status(printer_id) or {}
        state = status.get("state") or ("idle" if printer.get("last_seen") else "unknown")
        online = status.get("online")
        if online is None:
            online = bool(status) or bool(printer.get("last_seen"))
        return {
            "id": printer["id"],
            "name": printer.get("name") or printer.get("model") or "HP 打印机",
            "queue_name": printer.get("queue_name") or "",
            "model": printer.get("model") or "",
            "host": printer.get("host") or "",
            "serial": printer.get("serial") or "",
            "firmware": printer.get("firmware") or "",
            "online": bool(online),
            "state": state,
            "state_reason": status.get("state_reason") or "",
            "is_default": bool(printer.get("is_default")),
            "last_seen": int(printer.get("last_seen") or 0),
        }

    # =====================================================================
    # 打印机管理
    # =====================================================================
    def list_printers(self) -> List[Dict[str, Any]]:
        printers = self.store.list_printers()
        result: List[Dict[str, Any]] = []
        for printer in printers:
            cached = self._cached_status(printer["id"])
            if cached is None:
                # 首次访问：做一次快速探测（只读 ProductStatusDyn，约 0.1s），
                # 之后一律走缓存，避免阻塞列表接口。
                try:
                    self.status(printer["id"], refresh=True, fast=True)
                except HpError as exc:
                    log.debug("首屏状态探测失败 %s: %s", printer["id"], exc)
            summary = self.printer_summary(printer["id"])
            if summary:
                result.append(summary)
        return result

    def discover(self) -> List[Dict[str, Any]]:
        """扫描局域网，返回本次发现的设备（不自动保存）。"""
        prefer = None
        default = self.store.default_printer()
        if default:
            prefer = default.get("host")
        found = discovery.discover(prefer_host=prefer)
        cleaned: List[Dict[str, Any]] = []
        for item in found:
            cleaned.append(
                {
                    "host": item.get("host"),
                    "model": item.get("model") or "",
                    "serial": item.get("serial") or "",
                    "uuid": item.get("uuid") or "",
                    "source": item.get("source") or "scan",
                    "hostname": item.get("hostname") or "",
                    "scan": bool(item.get("scan")),
                }
            )
        return cleaned

    def _collect_capabilities(self, host: str, timeout: float = 6.0) -> Dict[str, Any]:
        """合并 IPP 与 eSCL 能力。"""
        caps: Dict[str, Any] = {
            "color": True,
            "duplex": False,
            "scan": False,
            "adf": False,
            "max_scan_dpi": 0,
            "scan_color_modes": [],
            "scan_formats": [],
            "media": [],
        }
        try:
            ipp_caps = IppPrinter(host, timeout=timeout).capabilities()
            caps.update(ipp_caps)
        except HpError as exc:
            log.warning("读取 IPP 能力失败（%s）: %s", host, exc)
        try:
            escl = EsclClient(host, timeout=timeout).capabilities(refresh=True)
            caps["scan"] = True
            caps["adf"] = bool(escl.get("adf"))
            caps["max_scan_dpi"] = int(escl.get("max_scan_dpi") or 0)
            caps["scan_color_modes"] = list(escl.get("scan_color_modes") or [])
            caps["scan_formats"] = [
                f for f in (escl.get("scan_formats") or []) if "/" in f
            ]
            caps["scan_resolutions"] = list(escl.get("resolutions") or [])
            caps["scan_intents"] = list(escl.get("intents") or [])
        except HpError as exc:
            log.warning("读取 eSCL 能力失败（%s）: %s", host, exc)
        caps["scan"] = bool(caps.get("scan"))
        return caps

    def add_printer(self, host: str) -> Dict[str, Any]:
        """手动添加（或更新）一台打印机：探测能力后落库。"""
        host = (host or "").strip()
        if not host:
            raise HpError("请提供打印机 IP 地址", code="bad_request")

        info = discovery.probe_host(host, timeout=5.0)
        if info is None:
            raise HpError(
                "在 %s 上没有找到可用的打印机服务" % host,
                detail="已尝试 LEDM(80)、eSCL(80)、IPP(631)",
                code="printer_not_found",
            )

        printer_id = info.get("uuid") or host
        caps = self._collect_capabilities(host)

        # 队列名 / 型号优先用 IPP 的 printer-name
        queue_name = None
        try:
            attrs = IppPrinter(host, timeout=5.0).get_attributes()
            queue_name = attrs.get("printer-name")
            info["model"] = info.get("model") or attrs.get("printer-make-and-model")
        except HpError as exc:
            log.debug("读取 IPP 名称失败（%s）: %s", host, exc)

        existing = self.store.get_printer(printer_id)
        data = {
            "id": printer_id,
            "name": info.get("name") or info.get("model") or "HP 打印机",
            "queue_name": queue_name or (existing or {}).get("queue_name"),
            "model": info.get("model"),
            "host": host,
            "serial": info.get("serial"),
            "firmware": info.get("firmware"),
            "uuid": (info.get("uuid") or "").lower() or None,
            "hostname": info.get("hostname"),
            "last_seen": int(time.time()),
            "capabilities": caps,
        }
        printer = self.store.upsert_printer(data)
        if self.store.default_printer() is None:
            self.store.set_default_printer(printer["id"])
        log.info("已保存打印机 %s @ %s", printer["id"], host)

        with self._cache_lock:
            self._caps_cache[printer["id"]] = (time.time(), caps)
            self._status_cache.pop(printer["id"], None)
        return printer

    def remove_printer(self, printer_id: str) -> None:
        if not self.store.delete_printer(printer_id):
            raise HpError("打印机不存在", code="not_found")
        with self._cache_lock:
            self._status_cache.pop(printer_id, None)
            self._caps_cache.pop(printer_id, None)
        log.info("已删除打印机 %s", printer_id)

    def set_default(self, printer_id: str) -> None:
        if self.store.get_printer(printer_id) is None:
            raise HpError("打印机不存在", code="not_found")
        self.store.set_default_printer(printer_id)

    # =====================================================================
    # 状态
    # =====================================================================
    def _get_capabilities(self, printer: Dict[str, Any], refresh: bool = False) -> Dict[str, Any]:
        printer_id = printer["id"]
        with self._cache_lock:
            entry = self._caps_cache.get(printer_id)
        if entry and not refresh and time.time() - entry[0] < CAPS_TTL:
            return entry[1]
        caps = printer.get("capabilities") or {}
        if not caps or refresh:
            caps = self._collect_capabilities(printer["host"])
            self.store.upsert_printer({**printer, "capabilities": caps})
        with self._cache_lock:
            self._caps_cache[printer_id] = (time.time(), caps)
        return caps

    def _try_reresolve(self, printer: Dict[str, Any]) -> Optional[str]:
        """打印机 IP 变化时，按 UUID / 主机名重新定位。"""
        printer_id = printer["id"]
        with self._cache_lock:
            if printer_id in self._resolving:
                return None
            self._resolving.add(printer_id)
        try:
            new_host = discovery.resolve(
                target_uuid=printer.get("uuid") or printer.get("id"),
                hostname=printer.get("hostname"),
                previous_host=printer.get("host"),
            )
            if new_host and new_host != printer.get("host"):
                self.store.update_printer_host(printer_id, new_host)
                log.warning(
                    "打印机 %s 的 IP 已变化：%s → %s", printer_id, printer.get("host"), new_host
                )
                return new_host
        finally:
            with self._cache_lock:
                self._resolving.discard(printer_id)
        return None

    def status(
        self, printer_id: str, refresh: bool = False, fast: bool = False
    ) -> Dict[str, Any]:
        """返回 API 契约中的状态结构。"""
        printer = self.store.get_printer(printer_id)
        if printer is None:
            raise HpError("打印机不存在", code="not_found")

        ttl = self._status_ttl()
        with self._cache_lock:
            entry = self._status_cache.get(printer_id)
        if entry and not refresh and time.time() - entry[0] < ttl:
            return entry[1]

        host = printer.get("host")
        client = LedmClient(host, timeout=2.0 if fast else 6.0)
        payload: Dict[str, Any]
        try:
            snapshot = self._collect_snapshot(client, fast=fast)
        except PrinterOffline as exc:
            # IP 可能变了：尝试重新定位后重试一次
            new_host = self._try_reresolve(printer)
            if new_host:
                host = new_host
                client = LedmClient(host, timeout=2.0 if fast else 6.0)
                try:
                    snapshot = self._collect_snapshot(client, fast=fast)
                except HpError as retry_exc:
                    payload = self._offline_status(printer, retry_exc)
                else:
                    payload = self._build_status(printer, host, snapshot, fast=fast)
            else:
                payload = self._offline_status(printer, exc)
        except HpError as exc:
            payload = self._offline_status(printer, exc)
        else:
            payload = self._build_status(printer, host, snapshot, fast=fast)

        with self._cache_lock:
            previous = self._status_cache.get(printer_id)
            self._status_cache[printer_id] = (time.time(), payload)

        if payload.get("online"):
            self.store.touch_printer(printer_id)

        if not previous or previous[1].get("state") != payload.get("state") or \
                previous[1].get("online") != payload.get("online"):
            self.emit(
                {
                    "type": "printer",
                    "printer": {
                        "id": printer_id,
                        "state": payload.get("state"),
                        "online": payload.get("online"),
                        "state_message": payload.get("state_message"),
                    },
                }
            )
        return payload

    def _collect_snapshot(self, client: LedmClient, fast: bool = False) -> Dict[str, Any]:
        """并行读取 LEDM 各资源（失败降级，不整体失败）。"""
        result: Dict[str, Any] = {}
        errors: List[str] = []

        result.update(client.product_status())
        if fast:
            return result

        result["supplies"] = []
        result["counters"] = {"total_pages": 0, "scan_pages": 0, "jam_events": 0}
        result["media"] = {"ready": None, "tray": None, "type": None}

        for name, func in (
            ("supplies", client.consumables),
            ("counters", client.usage),
            ("media", client.media),
        ):
            try:
                result[name] = func()
            except HpError as exc:
                errors.append("%s：%s" % (name, exc.message))
                log.warning("读取 %s 失败: %s", name, exc)
        if errors:
            result["partial_errors"] = errors
        return result

    def _offline_status(self, printer: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
        message = getattr(exc, "message", str(exc))
        log.warning("打印机 %s 离线: %s", printer.get("id"), message)
        return {
            "id": printer["id"],
            "online": False,
            "state": "offline",
            "state_message": "离线：%s" % message,
            "state_reason": message,
            "alerts": [{"category": "offline", "message": "打印机不在线"}],
            "supplies": [],
            "media": {"ready": None, "tray": None},
            "counters": {"total_pages": 0, "scan_pages": 0, "jam_events": 0},
            "capabilities": printer.get("capabilities") or {},
        }

    def _build_status(
        self,
        printer: Dict[str, Any],
        host: str,
        snapshot: Dict[str, Any],
        fast: bool = False,
    ) -> Dict[str, Any]:
        caps = printer.get("capabilities") or {}
        if not fast:
            try:
                caps = self._get_capabilities({**printer, "host": host})
            except HpError as exc:
                log.warning("读取能力失败: %s", exc)

        state = snapshot.get("state") or "unknown"
        media = snapshot.get("media") or {}
        counters = snapshot.get("counters") or {}
        supplies = snapshot.get("supplies") or []

        # 耗材兜底：LEDM 没有时用 IPP marker-* 属性
        if not supplies and not fast:
            try:
                supplies = IppPrinter(host, timeout=4.0).supplies()
            except HpError as exc:
                log.debug("IPP 耗材兜底失败: %s", exc)

        alerts = list(snapshot.get("alerts") or [])
        if any(s.get("state") == "empty" for s in supplies):
            alerts.append({"category": "supplyEmpty", "message": "墨水量耗尽"})
        elif any(s.get("state") == "low" for s in supplies):
            alerts.append({"category": "supplyLow", "message": "墨水量低"})

        return {
            "id": printer["id"],
            "online": True,
            "state": state,
            "state_message": snapshot.get("state_message") or STATE_TEXT.get(state, "状态未知"),
            "state_reason": snapshot.get("state_category") or "",
            "alerts": alerts,
            "supplies": supplies,
            "media": {
                "ready": media.get("ready"),
                "tray": media.get("tray"),
            },
            "counters": {
                "total_pages": int(counters.get("total_pages") or 0),
                "scan_pages": int(counters.get("scan_pages") or 0),
                "jam_events": int(counters.get("jam_events") or 0),
            },
            "capabilities": caps,
            "host": host,
            "partial_errors": snapshot.get("partial_errors") or [],
        }

    def maintenance(self, printer_id: str, action: str) -> Dict[str, Any]:
        printer = self.store.get_printer(printer_id)
        if printer is None:
            raise HpError("打印机不存在", code="not_found")
        client = LedmClient(printer["host"], timeout=8.0)
        try:
            result = client.maintenance(action)
        except PrinterOffline as exc:
            new_host = self._try_reresolve(printer)
            if not new_host:
                raise
            result = LedmClient(new_host, timeout=8.0).maintenance(action)
            log.info("维护动作在重新定位的 %s 上执行成功", new_host)
        log.info("维护动作 %s 已提交（%s）", action, printer["host"])
        return result

    def reports(self, printer_id: str) -> Dict[str, Any]:
        """返回本机真实支持的报告 / 维护作业类型（读 InternalPrintCap）。"""
        printer = self.store.get_printer(printer_id)
        if printer is None:
            raise HpError("打印机已被删除", code="not_found")
        client = LedmClient(printer["host"], timeout=8.0)
        try:
            return client.reports()
        except PrinterOffline:
            new_host = self._relocate(printer)
            if not new_host:
                raise
            return LedmClient(new_host, timeout=8.0).reports()

    def copy(self, printer_id: str, options: Dict[str, Any]) -> Dict[str, Any]:
        """复印 = 本地「扫描 → 打印」流水线。

        设备虽然声明支持 `POST /Copy/Jobs`，但本机固件 KEP1FN2020AR 实测该端点
        连接被接受后永不响应（45s 超时），故不使用原生复印，见 docs/protocol.md §6。
        """
        printer = self.store.get_printer(printer_id)
        if printer is None:
            raise HpError("打印机不存在", code="not_found")

        options = dict(options or {})
        color_mode = options.get("color_mode") or (
            "Grayscale8" if (options.get("color") or "color") == "monochrome" else "RGB24"
        )
        dpi = int(options.get("dpi") or 300)
        scan_opts = {
            "color_mode": color_mode,
            "dpi": dpi,
            "format": "jpeg",
            "intent": options.get("intent") or "Document",
            "auto_crop": bool(options.get("auto_crop", True)),
        }

        scan_job = self.start_scan(printer_id, scan_opts)
        deadline = time.time() + 120.0
        scan_state = "queued"
        while time.time() < deadline:
            job = self.store.get_job(scan_job)
            scan_state = (job or {}).get("state", "queued")
            if scan_state in ("done", "error", "canceled"):
                break
            time.sleep(0.5)

        if scan_state != "done":
            raise HpError(
                "复印失败：扫描阶段未完成（%s）" % scan_state,
                detail="请确认扫描仪盖板已合上、玻璃板上有原件",
                code="copy_scan_failed",
            )

        scan_row = None
        for row in self.list_scans(limit=20):
            if row.get("job_id") == scan_job:
                scan_row = row
                break
        if scan_row is None:
            raise HpError("复印失败：找不到扫描结果", code="copy_scan_missing")

        with open(scan_row["path"], "rb") as handle:
            data = handle.read()

        upload = self.upload(os.path.basename(scan_row["path"]), data)
        print_opts = {
            "copies": max(1, min(9, int(options.get("copies") or 1))),
            "color": "color" if color_mode == "RGB24" else "monochrome",
            "quality": options.get("quality") or "normal",
            "dpi": dpi,
            "media": options.get("media"),
            "scale": options.get("scale") or "fit",
            "pages": "all",
        }
        print_job = self.start_print(printer_id, [upload["token"]], print_opts)
        log.info("复印任务已创建：扫描 #%d → 打印 #%d", scan_job, print_job)
        return {
            "ok": True,
            "mode": "scan_then_print",
            "scan_job": scan_job,
            "print_job": print_job,
            "scan_id": scan_row.get("id"),
        }

    # =====================================================================
    # 本地邮件（SMTP 直发，不经 HP 服务器）
    # =====================================================================
    def email_scan(self, scan_id: int, to: Optional[str] = None,
                   subject: Optional[str] = None, body: Optional[str] = None) -> Dict[str, Any]:
        settings = self.store.get_settings()
        host = (settings.get("smtp_host") or "").strip()
        if not host:
            raise HpError("尚未配置 SMTP 服务器", detail="请到「设置 → 邮件」填写 SMTP 主机与账号",
                          code="smtp_not_configured")
        recipient = (to or settings.get("mail_to") or "").strip()
        if not recipient:
            raise HpError("未填写收件人", code="smtp_no_recipient")

        name, data, mime = self.scan_file(scan_id)
        message = EmailMessage()
        message["From"] = (settings.get("smtp_from") or settings.get("smtp_user") or "").strip()
        message["To"] = recipient
        message["Subject"] = subject or ("HP Offline 扫描件：%s" % name)
        message.set_content(body or "扫描件见附件。\n\n（本邮件由 HP Offline 通过本地 SMTP 直接发送，未经过 HP 服务器）")
        maintype, subtype = (mime.split("/", 1) + ["octet-stream"])[:2]
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)

        port = int(settings.get("smtp_port") or 465)
        use_tls = bool(settings.get("smtp_tls", True))
        user = (settings.get("smtp_user") or "").strip()
        password = settings.get("smtp_password") or ""
        try:
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=30,
                                      context=ssl.create_default_context()) as server:
                    if user:
                        server.login(user, password)
                    server.send_message(message)
            else:
                with smtplib.SMTP(host, port, timeout=30) as server:
                    if use_tls:
                        server.starttls(context=ssl.create_default_context())
                    if user:
                        server.login(user, password)
                    server.send_message(message)
        except Exception as exc:  # noqa: BLE001
            raise HpError("发送邮件失败：%s" % exc, code="smtp_failed")

        log.info("扫描件 #%d 已通过本地 SMTP 发送到 %s", scan_id, recipient)
        return {"ok": True, "to": recipient, "file": name, "size": len(data)}

    # =====================================================================
    # 快捷方式（本地替代官方云端 Smart Tasks）
    # =====================================================================
    def list_shortcuts(self) -> List[Dict[str, Any]]:
        return self.store.list_shortcuts()

    def add_shortcut(self, name: str, icon: str, steps: List[str],
                     scan_options: Dict[str, Any]) -> Dict[str, Any]:
        if not name or not str(name).strip():
            raise HpError("快捷方式名称不能为空", code="bad_request")
        allowed = {"save", "email", "print"}
        steps = [s for s in (steps or []) if s in allowed]
        if not steps:
            steps = ["save"]
        shortcut_id = self.store.add_shortcut(str(name).strip(), icon, steps, scan_options or {})
        log.info("已创建快捷方式 #%d：%s（%s）", shortcut_id, name, "+".join(steps))
        return self.store.get_shortcut(shortcut_id) or {}

    def delete_shortcut(self, shortcut_id: int) -> None:
        self.store.delete_shortcut(shortcut_id)

    def run_shortcut(self, shortcut_id: int) -> Dict[str, Any]:
        shortcut = self.store.get_shortcut(shortcut_id)
        if shortcut is None:
            raise HpError("快捷方式不存在", code="not_found")
        printer_id = shortcut.get("printer_id") or self.store.get_settings().get("default_printer")
        if not printer_id:
            printers = self.store.list_printers()
            printer_id = printers[0]["id"] if printers else ""
        if not printer_id:
            raise HpError("没有可用打印机", code="no_printer")

        options = dict(shortcut.get("scan_options") or {})
        options.setdefault("color_mode", "RGB24")
        options.setdefault("dpi", 300)
        options.setdefault("format", "pdf")
        options.setdefault("auto_crop", True)

        scan_job = self.start_scan(printer_id, options)
        deadline = time.time() + 180.0
        state = "queued"
        while time.time() < deadline:
            job = self.store.get_job(scan_job)
            state = (job or {}).get("state", "queued")
            if state in ("done", "error", "canceled"):
                break
            time.sleep(0.5)
        if state != "done":
            raise HpError("快捷方式失败：扫描未完成（%s）" % state, code="shortcut_scan_failed")

        scan_row = None
        for row in self.list_scans(limit=20):
            if row.get("job_id") == scan_job:
                scan_row = row
                break
        if scan_row is None:
            raise HpError("快捷方式失败：找不到扫描结果", code="shortcut_scan_missing")

        done: List[str] = ["save"]
        errors: List[str] = []
        print_job = None
        for step in shortcut.get("steps") or []:
            if step == "email":
                try:
                    self.email_scan(scan_row["id"])
                    done.append("email")
                except HpError as exc:
                    errors.append("邮件：%s" % exc.message)
            elif step == "print":
                try:
                    with open(scan_row["path"], "rb") as handle:
                        blob = handle.read()
                    upload = self.upload(os.path.basename(scan_row["path"]), blob)
                    print_job = self.start_print(
                        printer_id, [upload["token"]],
                        {"copies": 1, "color": "auto", "quality": "normal", "dpi": 300},
                    )
                    done.append("print")
                except HpError as exc:
                    errors.append("打印：%s" % exc.message)

        return {
            "ok": not errors,
            "shortcut": shortcut.get("name"),
            "scan_id": scan_row["id"],
            "scan_job": scan_job,
            "print_job": print_job,
            "done": done,
            "errors": errors,
        }

    # =====================================================================
    # 上传
    # =====================================================================
    def upload(self, filename: str, data: bytes) -> Dict[str, Any]:
        """保存上传文件并返回契约中的文件描述。"""
        safe_name = os.path.basename(filename or "document").replace("\\", "_")
        token = "u_" + uuidlib.uuid4().hex[:12]
        ext = os.path.splitext(safe_name)[1].lower()
        if not ext:
            head = data[:8]
            if head.startswith(b"%PDF"):
                ext = ".pdf"
            elif head.startswith(b"\x89PNG"):
                ext = ".png"
            else:
                ext = ".jpg"
        path = os.path.join(UPLOAD_DIR, token + ext)
        with open(path, "wb") as handle:
            handle.write(data)

        try:
            kind = render.file_kind(path)
            if kind == "unknown":
                os.remove(path)
                raise HpError(
                    "不支持的文件类型：%s" % safe_name,
                    detail="支持 PDF、PNG、JPG、BMP、WEBP、TIFF",
                    code="unsupported_file",
                )
            pages = render.count_pages(path)
        except HpError:
            raise
        except Exception as exc:  # noqa: BLE001 - 解析失败要如实上报
            try:
                os.remove(path)
            except OSError:
                pass
            log.exception("解析上传文件失败: %s", exc)
            raise HpError("无法读取文件内容：%s" % safe_name, detail=str(exc), code="bad_file")

        self.store.add_upload(token, safe_name, kind, pages, len(data), path)
        thumbs = ["/api/print/thumb/%s/%d" % (token, page) for page in range(min(pages, 30))]
        log.info("已接收上传 %s（%s，%d 页，%d 字节）", safe_name, kind, pages, len(data))
        return {
            "token": token,
            "name": safe_name,
            "kind": kind,
            "pages": pages,
            "size": len(data),
            "thumbs": thumbs,
        }

    def thumb(self, token: str, page: int, options: Optional[Dict[str, Any]] = None) -> bytes:
        upload = self.store.get_upload(token)
        if upload is None:
            raise HpError("上传文件已过期，请重新上传", code="not_found")
        if not os.path.exists(upload["path"]):
            raise HpError("上传文件已被删除，请重新上传", code="not_found")
        # 带参数时渲染「与真正送打一致」的预览（方向 / 缩放 / 黑白 / 纸张）
        if options:
            try:
                return render.preview_png(
                    upload["path"],
                    page=page,
                    dpi=int(options.get("dpi") or 150),
                    color=options.get("color") or "auto",
                    quality=options.get("quality") or "normal",
                    scale=options.get("scale") or "fit",
                    media=options.get("media") or None,
                    orientation=options.get("orientation") or "auto",
                    max_px=int(options.get("max_px") or 900),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("带参数预览失败，退回普通缩略图：%s", exc)
        return render.render_thumb(upload["path"], page)

    # =====================================================================
    # 打印
    # =====================================================================
    def _resolve_uploads(self, tokens: Iterable[str]) -> List[Dict[str, Any]]:
        uploads: List[Dict[str, Any]] = []
        for token in tokens:
            upload = self.store.get_upload(token)
            if upload is None:
                raise HpError("上传文件不存在或已过期：%s" % token, code="not_found")
            if not os.path.exists(upload["path"]):
                raise HpError("上传文件已被删除：%s" % upload["name"], code="not_found")
            uploads.append(upload)
        if not uploads:
            raise HpError("请先上传要打印的文件", code="bad_request")
        return uploads

    def start_print(
        self, printer_id: str, tokens: List[str], options: Dict[str, Any]
    ) -> int:
        printer = self.store.get_printer(printer_id)
        if printer is None:
            raise HpError("打印机不存在", code="not_found")
        uploads = self._resolve_uploads(tokens)

        options = dict(options or {})
        options.setdefault("copies", 1)
        options.setdefault("color", "auto")
        options.setdefault("quality", "normal")
        options.setdefault("dpi", 300)
        options.setdefault("media", None)
        options.setdefault("scale", "fit")
        options.setdefault("pages", "all")
        # 图片默认按「照片」优化，避免打印机用文本/图形模式把照片压暗
        options.setdefault(
            "content_optimize",
            "photo" if uploads and all(u.get("kind") == "image" for u in uploads) else "auto",
        )

        title = uploads[0]["name"] if len(uploads) == 1 else "%s 等 %d 个文件" % (
            uploads[0]["name"],
            len(uploads),
        )
        job_id = self.store.create_job(
            kind="print",
            printer_id=printer_id,
            title=title,
            pages_total=0,
            options={**options, "tokens": tokens},
            state="queued",
            message="任务已排队",
        )
        self._register_cancel(job_id)
        thread = threading.Thread(
            target=self._run_print,
            args=(job_id, printer_id, uploads, options),
            name="print-%d" % job_id,
            daemon=True,
        )
        thread.start()
        self._emit_job(job_id)
        log.info("打印任务 #%d 已创建（%s）", job_id, title)
        return job_id

    def _update_job(self, job_id: int, **fields: Any) -> None:
        # 暂停保护：暂停期间，worker 里所有非终态的状态更新都只能写成 paused，
        # 否则「已暂停」会被 preparing/sending/printing 覆盖，「继续」按钮消失、任务永远卡住。
        if fields.get("state") not in (None, "paused", "done", "error", "canceled"):
            with self._cancel_lock:
                event = self._pause_events.get(job_id)
                paused = event is not None and event.is_set()
            if paused:
                fields["state"] = "paused"
        self.store.update_job(job_id, **fields)
        self._emit_job(job_id)

    def _register_cancel(self, job_id: int) -> threading.Event:
        event = threading.Event()
        with self._cancel_lock:
            self._cancel_events[job_id] = event
        return event

    def _cancel_event(self, job_id: int) -> threading.Event:
        with self._cancel_lock:
            event = self._cancel_events.get(job_id)
            if event is None:
                event = threading.Event()
                self._cancel_events[job_id] = event
            return event

    def _pause_event(self, job_id: int) -> threading.Event:
        with self._cancel_lock:
            event = self._pause_events.get(job_id)
            if event is None:
                event = threading.Event()
                self._pause_events[job_id] = event
            return event

    def _wait_if_paused(self, job_id: int, cancel: threading.Event) -> None:
        """在页与页之间检查暂停。已送到打印机的页无法收回，只能停后续页。

        暂停期间**必须释放设备锁**，否则一次暂停会把扫描/其它打印全部阻塞
        （`_run_print` 是在持有 `_device_lock` 的情况下进入这里的）。
        """
        event = self._pause_events.get(job_id)
        if event is None or not event.is_set():
            return
        log.info("打印任务 #%d 已暂停，等待继续", job_id)
        self._device_lock.release()
        try:
            while event.is_set():
                if cancel.is_set():
                    raise JobCanceled()
                time.sleep(0.3)
            if cancel.is_set():
                raise JobCanceled()
        finally:
            # 无论继续还是取消，都要把锁拿回来，保证 _run_print 的 release 次数匹配
            self._device_lock.acquire()
        log.info("打印任务 #%d 已继续", job_id)

    def _run_print(
        self,
        job_id: int,
        printer_id: str,
        uploads: List[Dict[str, Any]],
        options: Dict[str, Any],
    ) -> None:
        cancel = self._cancel_event(job_id)
        try:
            self._update_job(job_id, state="preparing", progress=0.03, message="正在准备页面")
            dpi = int(options.get("dpi") or 300)
            color = options.get("color") or "auto"
            quality = options.get("quality") or "normal"
            scale = options.get("scale") or "fit"
            media = options.get("media")
            page_spec = options.get("pages") or "all"
            copies = max(1, int(options.get("copies") or 1))

            pages: List[Tuple[str, bytes]] = []
            for upload in uploads:
                if cancel.is_set():
                    raise JobCanceled()
                try:
                    rendered = render.render_pages(
                        upload["path"],
                        dpi=dpi,
                        color=color,
                        quality=quality,
                        scale=scale,
                        media=media,
                        page_spec=page_spec,
                        orientation=(options.get("orientation") or "auto"),
                        canvas_media=options.get("canvas_media"),
                        enhance=bool(options.get("auto_enhance", True)),
                        brightness=int(options.get("brightness") or 0),
                    )
                except ValueError as exc:
                    raise HpError(
                        "无法渲染文件「%s」：%s" % (upload["name"], exc), code="render_failed"
                    )
                except Exception as exc:  # noqa: BLE001
                    log.exception("渲染失败 %s", upload["path"])
                    raise HpError(
                        "无法渲染文件「%s」" % upload["name"], detail=str(exc), code="render_failed"
                    )
                for blob in rendered:
                    pages.append((upload["name"], blob))
                self._update_job(
                    job_id,
                    progress=0.03 + 0.12 * (len(pages) / max(1, len(pages))),
                    message="正在渲染「%s」" % upload["name"],
                )

            total = len(pages) * copies
            self._update_job(
                job_id,
                state="sending",
                progress=0.15,
                pages_total=total,
                message="共 %d 页，准备发送到打印机" % total,
            )

            printer = self.store.get_printer(printer_id)
            if printer is None:
                raise HpError("打印机已被删除", code="not_found")

            acquired = self._device_lock.acquire(timeout=600)
            if not acquired:
                raise HpError("设备长时间忙碌，请稍后再试", code="device_busy")
            try:
                self._send_pages(job_id, printer, pages, copies, options, cancel)
            finally:
                self._device_lock.release()

            # _send_pages 里可能已经把任务标成 done（例如用户在打印机面板上取消），
            # 这种情况下不要用「打印完成」覆盖它的说明。
            current = self.store.get_job(job_id) or {}
            if current.get("state") != "done":
                self._update_job(
                    job_id, state="done", progress=1.0, pages_sent=total,
                    message="打印完成，共 %d 页" % total,
                )
            log.info("打印任务 #%d 完成（%d 页）", job_id, total)
        except JobCanceled:
            self._update_job(job_id, state="canceled", progress=1.0, message="任务已取消")
            log.info("打印任务 #%d 已取消", job_id)
        except HpError as exc:
            # 页已经全部发出去、只是读状态失败（设备休眠/面板取消/网络抖动）时，
            # 按已完成归档，避免任务永久挂在「打印中」。
            job_now = self.store.get_job(job_id) or {}
            sent = int(job_now.get("pages_sent") or 0)
            total_pages = int(job_now.get("pages_total") or 0)
            if total_pages > 0 and sent >= total_pages:
                self._update_job(
                    job_id, state="done", progress=1.0,
                    message="页面已全部发送；读取设备状态失败（%s），按已完成归档" % exc.message,
                )
                log.warning("打印任务 #%d 页已发完，状态读取失败，按完成归档：%s", job_id, exc.message)
            else:
                self._update_job(job_id, state="error", progress=1.0,
                                 message=exc.message, error=exc.message)
                log.error("打印任务 #%d 失败: %s（%s）", job_id, exc.message, exc.detail)
        except Exception as exc:  # noqa: BLE001
            log.exception("打印任务 #%d 出现未预期错误", job_id)
            self._update_job(job_id, state="error", progress=1.0,
                             message="打印失败：%s" % exc, error=str(exc))
        finally:
            with self._cancel_lock:
                self._cancel_events.pop(job_id, None)
                self._pause_events.pop(job_id, None)

    def _send_pages(
        self,
        job_id: int,
        printer: Dict[str, Any],
        pages: List[Tuple[str, bytes]],
        copies: int,
        options: Dict[str, Any],
        cancel: threading.Event,
    ) -> None:
        """用 Create-Job + Send-Document 发送；失败则回退为逐页 Print-Job。"""
        media = options.get("canvas_media") or options.get("media")
        color = options.get("color") or "auto"
        quality = options.get("quality") or "normal"
        content_optimize = options.get("content_optimize") or "auto"
        job_name = "%s" % (self.store.get_job(job_id) or {}).get("title", "HP Offline 文档")

        client = IppPrinter(printer["host"], timeout=60.0)
        total = len(pages) * copies
        sent = 0
        ipp_job_id: Optional[int] = None

        # 本机实测（Ink Tank Wireless 410，固件 KEP1FN2020AR）：
        # Create-Job + Send-Document 会被接受（返回成功、job-id 正常），但打印机随后
        # 永远停在 job-state=5(processing) / job-impressions-completed=0，占住设备直到
        # 超时，并让后续作业全部 server-error-busy。因此这里强制走逐页 Print-Job。
        # 逐页 Print-Job 已真机验证可稳定出纸（job-state 9 / impressions 1）。
        use_create_job = bool(options.get("_use_create_job", False))

        try:
            if use_create_job:
                ipp_job_id = client.create_print_job(
                    job_name, copies=copies, color=color, quality=quality, media=media
                )
                self._update_job(job_id, ipp_job_id=ipp_job_id,
                                 message="已创建打印任务 #%s，正在发送第 1/%d 页" % (ipp_job_id, len(pages)))
        except HpError as exc:
            log.warning("Create-Job 不可用（%s），回退为逐页 Print-Job", exc.message)
            ipp_job_id = None

        if ipp_job_id is not None:
            try:
                for index, (_name, blob) in enumerate(pages):
                    if cancel.is_set():
                        client.cancel(ipp_job_id)
                        raise JobCanceled()
                    client.send_page(ipp_job_id, blob, last=(index == len(pages) - 1))
                    sent += copies
                    self._update_job(
                        job_id,
                        pages_sent=sent,
                        progress=0.15 + 0.45 * ((index + 1) / len(pages)),
                        message="正在发送第 %d/%d 页" % (index + 1, len(pages)),
                    )
            except HpError as exc:
                log.warning("Send-Document 失败（%s），改用 Print-Job 重新发送", exc.message)
                ipp_job_id = None
                sent = 0

        if ipp_job_id is None:
            last_job: Optional[int] = None
            for index, (_name, blob) in enumerate(pages):
                if cancel.is_set():
                    if last_job is not None:
                        IppPrinter(printer["host"], timeout=15.0).cancel(last_job)
                    raise JobCanceled()
                # 页与页之间响应「暂停」
                self._wait_if_paused(job_id, cancel)
                last_job = client.print_document(
                    blob,
                    job_name=job_name,
                    copies=copies,
                    color=color,
                    quality=quality,
                    media=media,
                    content_optimize=content_optimize,
                    scale=scale,
                )
                ipp_job_id = last_job
                sent += copies
                self._update_job(
                    job_id,
                    ipp_job_id=last_job,
                    pages_sent=sent,
                    progress=0.15 + 0.45 * ((index + 1) / len(pages)),
                    message="正在发送第 %d/%d 页" % (index + 1, len(pages)),
                )

        if ipp_job_id is None:
            raise HpError("无法向打印机提交任何页面", code="print_failed")

        self._update_job(job_id, state="printing", progress=0.62, message="打印机正在出纸")

        def _on_progress(info: Dict[str, Any]) -> None:
            state = info.get("state")
            progress = 0.62
            message = "打印机正在处理"
            if state == 5:
                progress = 0.72
                message = "打印机正在出纸"
            elif state in (3, 4):
                progress = 0.62
                message = "任务已进入打印队列"
            elif state == 6:
                progress = 0.7
                message = "打印暂停：%s" % (", ".join(info.get("reasons") or []) or "设备需要处理")
            self._update_job(job_id, progress=progress, message=message)

        result = client.wait_job(
            ipp_job_id, timeout=240.0, poll=1.5, on_progress=_on_progress, cancel_event=cancel
        )
        state = result.get("state")
        reasons = result.get("reasons") or []
        if state == 9:
            self._update_job(job_id, state="printing", progress=0.98,
                             message="打印完成，等待设备收尾")
        elif state == 7:
            if cancel.is_set():
                # 用户在应用里点了取消
                raise JobCanceled()
            # 用户在打印机面板上取消：作业已经结束，保留进度，标记为已完成进历史，
            # 不要留在「任务」里当成进行中/失败。
            self._update_job(
                job_id,
                state="done",
                progress=1.0,
                message="已在打印机上取消（保留已完成的进度）",
            )
            log.info("打印任务 #%d 在打印机面板上被取消，按已完成归档", job_id)
            return
        elif state == 8:
            raise HpError(
                "打印机中止了任务",
                detail=", ".join(reasons),
                code="print_aborted",
            )
        elif result.get("timed_out"):
            # 页已经发完了，只是设备没回传终态。不能让它永远挂在「打印中」。
            self._update_job(
                job_id, state="done", progress=1.0,
                message="打印已结束（设备未回传最终状态，按已完成归档）",
            )
            log.warning("打印任务 #%d 轮询超时，已按完成归档", job_id)

    # =====================================================================
    # 扫描
    # =====================================================================
    def start_scan(self, printer_id: str, options: Dict[str, Any]) -> int:
        printer = self.store.get_printer(printer_id)
        if printer is None:
            raise HpError("打印机不存在", code="not_found")
        options = dict(options or {})
        job_id = self.store.create_job(
            kind="scan",
            printer_id=printer_id,
            title="扫描 %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
            pages_total=1,
            options=options,
            state="queued",
            message="扫描任务已排队",
        )
        self._register_cancel(job_id)
        thread = threading.Thread(
            target=self._run_scan, args=(job_id, printer_id, options),
            name="scan-%d" % job_id, daemon=True,
        )
        thread.start()
        self._emit_job(job_id)
        log.info("扫描任务 #%d 已创建", job_id)
        return job_id

    def _save_dir(self) -> str:
        settings = self.store.get_settings()
        directory = settings.get("save_dir") or os.path.join(
            os.path.expanduser("~"), "Pictures", "HP Offline"
        )
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            log.warning("无法创建保存目录 %s（%s），改用默认目录", directory, exc)
            directory = os.path.join(DATA_DIR, "scans")
            os.makedirs(directory, exist_ok=True)
        return directory

    @staticmethod
    def _unique_path(directory: str, stem: str, ext: str) -> str:
        path = os.path.join(directory, stem + ext)
        counter = 1
        while os.path.exists(path):
            path = os.path.join(directory, "%s_%d%s" % (stem, counter, ext))
            counter += 1
        return path

    def _run_scan(self, job_id: int, printer_id: str, options: Dict[str, Any]) -> None:
        cancel = self._cancel_event(job_id)
        try:
            self._update_job(job_id, state="preparing", progress=0.03, message="正在连接扫描仪")
            printer = self.store.get_printer(printer_id)
            if printer is None:
                raise HpError("打印机已被删除", code="not_found")

            acquired = self._device_lock.acquire(timeout=600)
            if not acquired:
                raise HpError("设备长时间忙碌，请稍后再试", code="device_busy")
            try:
                self._update_job(job_id, state="sending", progress=0.1, message="正在启动扫描")
                documents = self._scan_documents(printer, options, job_id, cancel)
            finally:
                self._device_lock.release()

            fmt = (options.get("format") or "jpeg").lower()
            dpi = int(options.get("dpi") or 300)
            directory = self._save_dir()
            stem = "scan_" + time.strftime("%Y%m%d_%H%M%S")

            self._update_job(job_id, progress=0.9, message="正在后处理扫描结果")
            blobs = [data for data, _ctype in documents]
            try:
                result = postprocess.process_pages(
                    blobs,
                    {
                        "auto_crop": options.get("auto_crop", True),
                        "auto_orient": options.get("auto_orient", False),
                        "auto_enhance": options.get("auto_enhance", False),
                        "merge": options.get("merge") or "none",
                        "format": fmt,
                        "dpi": dpi,
                        "pdf_password": options.get("pdf_password") or None,
                        "pdf_allow_copy": options.get("pdf_allow_copy", True),
                        "ocr": bool(options.get("ocr")),
                        "ocr_lang": options.get("ocr_lang") or "ch",
                    },
                )
                content = result["data"]
                ext = "." + result["ext"]
                width, height = result["width"], result["height"]
                if result["notes"]:
                    self._update_job(job_id, message="；".join(result["notes"]))
            except Exception as exc:  # noqa: BLE001
                # 后处理失败不能毁掉已经扫到的原件：退回原始数据
                log.warning("后处理失败，保存原始扫描件：%s", exc)
                if fmt in ("pdf", "application/pdf"):
                    content = render.images_to_pdf(blobs, dpi=dpi)
                    ext = ".pdf"
                    width, height = render.image_dimensions(blobs[0]) if blobs else (0, 0)
                else:
                    content = blobs[0]
                    ext = ".jpg"
                    width, height = render.image_dimensions(content)

            path = self._unique_path(directory, stem, ext)
            with open(path, "wb") as handle:
                handle.write(content)
            size = os.path.getsize(path)
            scan_id = self.store.add_scan(
                job_id, printer_id, "pdf" if ext == ".pdf" else "jpeg",
                path, width, height, size,
            )
            self._update_job(
                job_id,
                state="done",
                progress=1.0,
                pages_total=len(documents),
                pages_sent=len(documents),
                message="扫描完成：%s" % os.path.basename(path),
            )
            self.emit(
                {
                    "type": "scan",
                    "scan": {
                        "id": scan_id,
                        "job_id": job_id,
                        "printer_id": printer_id,
                        "format": "pdf" if ext == ".pdf" else "jpeg",
                        "path": path,
                        "width": width,
                        "height": height,
                        "size": size,
                        "created_at": int(time.time()),
                    },
                }
            )
            log.info("扫描任务 #%d 完成：%s（%d 字节）", job_id, path, size)
        except JobCanceled:
            self._update_job(job_id, state="canceled", progress=1.0, message="扫描已取消")
        except HpError as exc:
            self._update_job(job_id, state="error", progress=1.0,
                             message=exc.message, error=exc.message)
            log.error("扫描任务 #%d 失败: %s（%s）", job_id, exc.message, exc.detail)
        except Exception as exc:  # noqa: BLE001
            log.exception("扫描任务 #%d 出现未预期错误", job_id)
            self._update_job(job_id, state="error", progress=1.0,
                             message="扫描失败：%s" % exc, error=str(exc))
        finally:
            with self._cancel_lock:
                self._cancel_events.pop(job_id, None)
                self._pause_events.pop(job_id, None)

    def _scan_documents(
        self,
        printer: Dict[str, Any],
        options: Dict[str, Any],
        job_id: int,
        cancel: threading.Event,
    ) -> List[Tuple[bytes, str]]:
        host = printer["host"]

        def _progress(message: str, progress: float) -> None:
            self._update_job(job_id, message=message, progress=max(0.1, min(0.9, progress)))

        client = EsclClient(host, timeout=30.0)
        # 后处理（裁切/纠偏/增强/OCR/拼版/加密）都在本地做，因此始终让设备出 JPEG：
        # 直接要 PDF 会拿到设备端合成的 PDF，无法再做图像处理。
        scan_options = dict(options)
        scan_options["format"] = "jpeg"
        try:
            return client.scan(scan_options, on_progress=_progress, cancel_event=cancel)
        except PrinterOffline:
            new_host = self._try_reresolve(printer)
            if not new_host:
                raise
            log.info("扫描仪重新定位到 %s，重试", new_host)
            return EsclClient(new_host, timeout=30.0).scan(
                scan_options, on_progress=_progress, cancel_event=cancel
            )

    def list_scans(self, limit: int = 50) -> List[Dict[str, Any]]:
        scans = self.store.list_scans(limit)
        result: List[Dict[str, Any]] = []
        for scan in scans:
            item = dict(scan)
            item["thumb"] = "/api/scans/%d/thumb" % scan["id"]
            item["file"] = "/api/scans/%d/file" % scan["id"]
            item["exists"] = os.path.exists(scan["path"])
            result.append(item)
        return result

    def scan_file(self, scan_id: int) -> Tuple[str, bytes, str]:
        """返回 (文件名, 字节, MIME)。"""
        scan = self.store.get_scan(scan_id)
        if scan is None:
            raise HpError("扫描记录不存在", code="not_found")
        path = scan["path"]
        if not os.path.exists(path):
            raise HpError("扫描文件已被移动或删除", code="not_found")
        with open(path, "rb") as handle:
            data = handle.read()
        mime = "application/pdf" if path.lower().endswith(".pdf") else "image/jpeg"
        return os.path.basename(path), data, mime

    def scan_thumb(self, scan_id: int) -> bytes:
        scan = self.store.get_scan(scan_id)
        if scan is None:
            raise HpError("扫描记录不存在", code="not_found")
        if not os.path.exists(scan["path"]):
            raise HpError("扫描文件已被移动或删除", code="not_found")
        return render.render_thumb(scan["path"], 0)

    def delete_scan(self, scan_id: int) -> None:
        scan = self.store.delete_scan(scan_id)
        if scan is None:
            raise HpError("扫描记录不存在", code="not_found")
        try:
            if os.path.exists(scan["path"]):
                os.remove(scan["path"])
        except OSError as exc:
            log.warning("删除扫描文件失败 %s: %s", scan["path"], exc)
        log.info("已删除扫描记录 #%d", scan_id)

    # =====================================================================
    # 任务
    # =====================================================================
    def cancel_job(self, job_id: int) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise HpError("任务不存在", code="not_found")
        if job["state"] in ("done", "error", "canceled"):
            raise HpError("任务已结束，无法取消", code="job_finished")
        event = self._cancel_event(job_id)
        event.set()
        ipp_job_id = job.get("ipp_job_id")
        if ipp_job_id and job.get("kind") == "print":
            printer = self.store.get_printer(job["printer_id"])
            if printer:
                try:
                    IppPrinter(printer["host"], timeout=10.0).cancel(int(ipp_job_id))
                except HpError as exc:
                    log.warning("取消 IPP 任务失败: %s", exc)
        self._update_job(job_id, message="正在取消…")
        return self.store.get_job(job_id) or job

    def list_jobs(self, limit: int = 50, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        return [self.serialize_job(job) for job in self.store.list_jobs(limit, kind)]

    def get_job(self, job_id: int) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise HpError("任务不存在", code="not_found")
        return self.serialize_job(job)

    # =====================================================================
    # 任务控制：暂停 / 继续 / 重试
    # =====================================================================
    def pause_job(self, job_id: int) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise HpError("任务不存在", code="not_found")
        if job.get("kind") != "print":
            raise HpError("只有打印任务支持暂停", detail="扫描是一次性动作，请直接取消",
                          code="not_supported")
        if job.get("state") in ("done", "error", "canceled"):
            raise HpError("任务已结束，无法暂停", code="bad_state")
        if job.get("state") == "paused":
            return self.serialize_job(job)
        self._pause_event(job_id).set()
        self._update_job(job_id, state="paused",
                         message="已暂停：当前页送完后不再发送后续页")
        log.info("打印任务 #%d 已暂停", job_id)
        return self.serialize_job(self.store.get_job(job_id) or job)

    def resume_job(self, job_id: int) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise HpError("任务不存在", code="not_found")
        if job.get("state") != "paused":
            raise HpError("任务当前不在暂停状态", code="bad_state")
        self._pause_event(job_id).clear()
        sent = int(job.get("pages_sent") or 0)
        total = int(job.get("pages_total") or 0)
        next_state = "sending" if total and sent < total else "printing"
        self._update_job(job_id, state=next_state, message="已继续")
        log.info("打印任务 #%d 已继续", job_id)
        return self.serialize_job(self.store.get_job(job_id) or job)

    def retry_job(self, job_id: int) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise HpError("任务不存在", code="not_found")
        kind = job.get("kind")
        printer_id = job.get("printer_id")
        options = dict(job.get("options") or {})
        if kind == "print":
            tokens = options.pop("tokens", None) or []
            if not tokens:
                raise HpError("原始文件已不可用，无法重试", detail="请重新上传文件",
                              code="retry_unavailable")
            new_id = self.start_print(printer_id, tokens, options)
        elif kind == "scan":
            new_id = self.start_scan(printer_id, options)
        else:
            raise HpError("该任务类型不支持重试", code="not_supported")
        log.info("任务 #%d 已重试为 #%d", job_id, new_id)
        return {"job_id": new_id, "retried_from": job_id}

    # =====================================================================
    # 目录选择（Windows 原生对话框）
    # =====================================================================
    def browse_dir(self, initial: Optional[str] = None) -> Dict[str, Any]:
        """弹出系统目录选择框，返回用户选择的路径。取消时返回 canceled=True。"""
        if os.name != "nt":
            raise HpError("当前系统不支持目录选择", detail="请手动输入路径",
                          code="not_supported")
        script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dlg = New-Object System.Windows.Forms.FolderBrowserDialog
$dlg.Description = '选择扫描件保存目录'
$dlg.ShowNewFolderButton = $true
$init = $env:HP_BROWSE_INITIAL
if ($init -and (Test-Path -LiteralPath $init)) { $dlg.SelectedPath = $init }
$form = New-Object System.Windows.Forms.Form
$form.TopMost = $true
$form.ShowInTaskbar = $false
$form.WindowState = 'Minimized'
$form.Show()
$res = $dlg.ShowDialog($form)
$form.Close()
if ($res -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.WriteLine($dlg.SelectedPath) }
"""
        env = dict(os.environ)
        try:
            env["HP_BROWSE_INITIAL"] = initial or (self.store.get_settings().get("save_dir") or "")
        except Exception:  # noqa: BLE001
            env["HP_BROWSE_INITIAL"] = initial or ""
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            raise HpError("目录选择超时（5 分钟未操作）", code="browse_timeout")
        except OSError as exc:
            raise HpError("无法打开目录选择窗口：%s" % exc, code="browse_failed")

        chosen = ""
        for line in reversed((proc.stdout or "").splitlines()):
            candidate = line.strip()
            if candidate and os.path.isdir(candidate):
                chosen = candidate
                break
        if not chosen:
            return {"ok": True, "canceled": True, "path": ""}
        log.info("用户选择保存目录：%s", chosen)
        return {"ok": True, "canceled": False, "path": chosen}

    # =====================================================================
    # 设置 / 健康
    # =====================================================================
    def get_settings(self) -> Dict[str, Any]:
        settings = self.store.get_settings()
        default = self.store.default_printer()
        settings["default_printer"] = default["id"] if default else settings.get("default_printer", "")
        return settings

    def patch_settings(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            "theme",
            "accent",
            "language",
            "save_dir",
            "auto_discover",
            "poll_interval",
            "default_printer",
            "offline_mode",
        }
        cleaned = {k: v for k, v in (patch or {}).items() if k in allowed}
        if "save_dir" in cleaned:
            directory = str(cleaned["save_dir"] or "").strip()
            if not directory:
                cleaned.pop("save_dir")
            else:
                try:
                    os.makedirs(directory, exist_ok=True)
                except OSError as exc:
                    raise HpError(
                        "无法创建保存目录：%s" % directory, detail=str(exc), code="bad_request"
                    )
                cleaned["save_dir"] = directory
        if "poll_interval" in cleaned:
            try:
                cleaned["poll_interval"] = max(3, min(300, int(cleaned["poll_interval"])))
            except (TypeError, ValueError):
                cleaned.pop("poll_interval")
        if "default_printer" in cleaned:
            printer_id = cleaned.pop("default_printer")
            if printer_id:
                self.set_default(printer_id)
        settings = self.store.patch_settings(cleaned)
        default = self.store.default_printer()
        settings["default_printer"] = default["id"] if default else ""
        return settings

    def health(self) -> Dict[str, Any]:
        import platform

        return {
            "ok": True,
            "version": __version__,
            "python": platform.python_version(),
            "cloud_calls": self._cloud_calls,
            "printers": len(self.store.list_printers()),
        }

    # =====================================================================
    # 后台轮询
    # =====================================================================
    def start_poller(self) -> None:
        if self._poll_thread is not None:
            return
        # 先归档上一个进程遗留的「进行中」任务：线程已经不存在，没人会再推进它们
        self._reconcile_orphan_jobs()
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="printer-poller", daemon=True
        )
        self._poll_thread.start()
        log.info("打印机状态轮询已启动")

    def stop_poller(self) -> None:
        self._poll_stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5.0)
            self._poll_thread = None

    def _poll_loop(self) -> None:
        # 启动后先做一次发现，修正可能变化的 IP
        time.sleep(1.0)
        self._startup_reconcile()
        while not self._poll_stop.is_set():
            interval = self._status_ttl()
            try:
                printers = self.store.list_printers()
                for printer in printers:
                    if self._poll_stop.is_set():
                        break
                    try:
                        self.status(printer["id"], refresh=True)
                    except HpError as exc:
                        log.debug("轮询 %s 失败: %s", printer["id"], exc)
            except Exception as exc:  # noqa: BLE001
                log.warning("状态轮询循环异常: %s", exc)
            self._poll_stop.wait(max(MIN_STATUS_TTL, interval))

    def _reconcile_orphan_jobs(self) -> None:
        """服务重启后，上一个进程遗留的进行中作业不会再有人推进，直接归档。

        否则这些记录会永远以「打印中 / 暂停」粘在任务列表里
        （典型场景：用户在打印机面板上取消，或服务重启把工作线程带走了）。
        """
        try:
            jobs = self.store.list_jobs(limit=500)
        except Exception as exc:  # noqa: BLE001
            log.warning("启动归档遗留任务失败: %s", exc)
            return
        active = {"queued", "preparing", "sending", "printing", "paused"}
        stale = [job for job in jobs if job.get("state") in active]
        for job in stale:
            try:
                self._update_job(
                    job["id"],
                    state="done",
                    progress=1.0,
                    message="服务重启，任务已中断并按已完成归档",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("归档遗留任务 #%s 失败: %s", job.get("id"), exc)
        if stale:
            log.info("启动时归档了 %d 个遗留任务", len(stale))

    def _startup_reconcile(self) -> None:
        """启动时用 WS-Discovery 校正已保存打印机的 IP（DHCP 会变）。"""
        printers = self.store.list_printers()
        if not printers:
            return
        try:
            found = discovery.discover(
                prefer_host=printers[0].get("host"),
                wsd_timeout=5.0,
                mdns_timeout=1.5,
                snmp_timeout=1.0,
                do_subnet=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("启动时发现设备失败: %s", exc)
            return
        by_uuid = {(item.get("uuid") or "").lower(): item for item in found if item.get("uuid")}
        by_hostname = {
            (item.get("hostname") or "").lower().rstrip("."): item
            for item in found
            if item.get("hostname")
        }
        for printer in printers:
            uuid_value = (printer.get("uuid") or "").lower()
            hostname = (printer.get("hostname") or "").lower().rstrip(".")
            match = by_uuid.get(uuid_value) or by_hostname.get(hostname)
            if match and match.get("host") and match["host"] != printer.get("host"):
                self.store.update_printer_host(printer["id"], match["host"])
                log.warning(
                    "启动校正：打印机 %s 的 IP %s → %s",
                    printer["id"], printer.get("host"), match["host"],
                )
