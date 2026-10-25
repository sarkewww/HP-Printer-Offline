"""eSCL（Mopria / AirPrint 扫描）客户端，端口 80。

流程（docs/protocol.md 实测）：
    1. ``GET  /eSCL/ScannerCapabilities``  解析能力
    2. ``POST /eSCL/ScanJobs``             Content-Type: text/xml → 201 + Location
    3. ``GET  <Location>/NextDocument``    未就绪返回 503，需退避重试（实测 3–8 秒出图）
    4. 多页（ADF）时重复 3，直到 404/410 表示没有更多页面

注意：503 也可能表示**扫描仪忙**（正在打印 / 上一任务未完成），因此把重试
上限设为约 60 秒并在超时后给出「设备忙，请稍候」的中文提示。
"""

from __future__ import annotations

import http.client
import io
import socket
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import get_logger
from . import HpError, PrinterOffline, ProtocolError

log = get_logger("hp.escl")

ESCL_PORT = 80
PATH_CAPABILITIES = "/eSCL/ScannerCapabilities"
PATH_STATUS = "/eSCL/ScannerStatus"
PATH_JOBS = "/eSCL/ScanJobs"

#: 默认 A4 平台扫描区域（300dpi，实测上限）
DEFAULT_WIDTH_300 = 2550
DEFAULT_HEIGHT_300 = 3508

ESCL_NS = "http://schemas.hp.com/imaging/escl/2011/05/03"
PWG_NS = "http://www.pwg.org/schemas/2010/12/sm"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_all(elem: Optional[ET.Element], local_name: str) -> List[ET.Element]:
    if elem is None:
        return []
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
    for node in _find_all(elem, local_name):
        if node.text and node.text.strip():
            value = node.text.strip()
            if value not in out:
                out.append(value)
    return out


def _int_or(value: Optional[str], default: int = 0) -> int:
    try:
        return int(float(value)) if value is not None else default
    except (TypeError, ValueError):
        return default


class EsclClient:
    """单个 eSCL 扫描仪端点。"""

    def __init__(self, host: str, port: int = ESCL_PORT, timeout: float = 30.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._caps_cache: Optional[Dict[str, Any]] = None

    # -- 传输 -------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[int, Dict[str, str], bytes]:
        timeout = timeout if timeout is not None else self.timeout
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            hdrs = {"Connection": "close"}
            if headers:
                hdrs.update(headers)
            conn.request(method, path, body=body, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, resp_headers, data
        except (socket.timeout, TimeoutError) as exc:
            raise PrinterOffline("扫描仪响应超时（%s）" % self.host, str(exc))
        except (ConnectionError, OSError) as exc:
            raise PrinterOffline(
                "无法连接扫描仪（%s:%d）" % (self.host, self.port),
                "%s: %s" % (type(exc).__name__, exc),
            )
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass

    # -- 状态 / 能力 ------------------------------------------------------
    def scanner_status(self) -> Dict[str, Any]:
        status, headers, data = self._request("GET", PATH_STATUS, timeout=6)
        if status != 200:
            raise HpError("读取扫描仪状态失败（HTTP %d）" % status, code="escl_status_error")
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise ProtocolError("扫描仪状态 XML 无法解析", detail=str(exc))
        state = _text(root, "State", "Unknown") or "Unknown"
        jobs: List[Dict[str, Any]] = []
        for job in _find_all(root, "JobInfo"):
            jobs.append(
                {
                    "uri": _text(job, "JobUri"),
                    "uuid": _text(job, "JobUuid"),
                    "state": _text(job, "JobState"),
                    "state_reasons": _texts(job, "JobStateReasons"),
                    "images_completed": _int_or(_text(job, "ImagesCompleted")),
                    "images_to_transfer": _int_or(_text(job, "ImagesToTransfer")),
                }
            )
        return {"state": state, "jobs": jobs, "busy": state.lower() not in ("idle", "ready")}

    def capabilities(self, refresh: bool = False) -> Dict[str, Any]:
        """解析 ScannerCapabilities → 归一化能力字典。"""
        if self._caps_cache is not None and not refresh:
            return self._caps_cache
        status, headers, data = self._request("GET", PATH_CAPABILITIES, timeout=8)
        if status != 200:
            raise HpError(
                "读取扫描能力失败（HTTP %d）" % status, code="escl_caps_error"
            )
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise ProtocolError("扫描能力 XML 无法解析", detail=str(exc))

        platen = _first(root, "Platen")
        adf = _first(root, "Adf")
        source = adf if adf is not None else platen
        caps_node = _first(source, "AdfInputCaps") if adf is not None else _first(source, "PlatenInputCaps")
        if caps_node is None:
            caps_node = source

        max_width = _int_or(_text(caps_node, "MaxWidth"), DEFAULT_WIDTH_300)
        max_height = _int_or(_text(caps_node, "MaxHeight"), DEFAULT_HEIGHT_300)
        min_width = _int_or(_text(caps_node, "MinWidth"), 8)
        min_height = _int_or(_text(caps_node, "MinHeight"), 8)

        color_modes = _texts(caps_node, "ColorMode") or ["BlackAndWhite1", "Grayscale8", "RGB24"]
        formats = _texts(caps_node, "DocumentFormat")
        formats += [f for f in _texts(caps_node, "DocumentFormatExt") if f not in formats]
        formats = [f for f in formats if f != "application/octet-stream"] or ["image/jpeg"]

        resolutions: List[int] = []
        for res in _find_all(caps_node, "DiscreteResolution"):
            x = _int_or(_text(res, "XResolution"), 0)
            if x and x not in resolutions:
                resolutions.append(x)
        if not resolutions:
            for res in _find_all(caps_node, "Resolution"):
                x = _int_or(_text(res, "XResolution"), 0)
                if x and x not in resolutions:
                    resolutions.append(x)
        resolutions.sort()
        max_optical = _int_or(_text(caps_node, "MaxOpticalXResolution"), resolutions[-1] if resolutions else 300)

        intents = _texts(caps_node, "Intent") or ["Document", "Photo", "TextAndGraphic"]

        # 亮度 / 对比度 / 阈值范围
        def _range(name: str) -> Dict[str, int]:
            node = _first(root, name)
            return {
                "min": _int_or(_text(node, "Min"), 0),
                "max": _int_or(_text(node, "Max"), 2000),
                "normal": _int_or(_text(node, "Normal"), 1000),
                "step": _int_or(_text(node, "Step"), 1),
            }

        caps = {
            "scan": True,
            "adf": adf is not None,
            "platen": platen is not None,
            "max_width": max_width,
            "max_height": max_height,
            "min_width": min_width,
            "min_height": min_height,
            "max_scan_dpi": max_optical,
            "resolutions": resolutions,
            "scan_color_modes": color_modes,
            "scan_formats": formats,
            "intents": intents,
            "brightness": _range("BrightnessSupport"),
            "contrast": _range("ContrastSupport"),
            "threshold": _range("ThresholdSupport"),
            "uuid": _text(root, "UUID"),
            "make_and_model": _text(root, "MakeAndModel"),
            "version": _text(root, "Version"),
        }
        self._caps_cache = caps
        return caps

    def is_scanner(self, timeout: float = 3.0) -> bool:
        """轻量探测：主机是否提供 eSCL 扫描。"""
        try:
            status, _headers, _data = self._request("GET", PATH_STATUS, timeout=timeout)
        except HpError:
            return False
        return status == 200

    # -- 扫描 -------------------------------------------------------------
    def build_settings(self, options: Dict[str, Any], caps: Optional[Dict[str, Any]] = None) -> str:
        """根据 API 选项构造 scan:ScanSettings XML。"""
        caps = caps or self.capabilities()
        dpi = int(options.get("dpi") or 300)
        color_mode = options.get("color_mode") or "RGB24"
        if color_mode not in caps["scan_color_modes"]:
            color_mode = caps["scan_color_modes"][-1]

        fmt = (options.get("format") or "jpeg").lower()
        if fmt in ("pdf", "application/pdf"):
            document_format = "application/pdf"
        else:
            document_format = "image/jpeg"
        if document_format not in caps["scan_formats"]:
            document_format = "image/jpeg"

        region = options.get("region") or {}
        # 设备的上限是 300dpi 下的像素数，需要按 dpi 等比放大
        scale = dpi / 300.0
        default_w = int(round(caps["max_width"] * scale))
        default_h = int(round(caps["max_height"] * scale))
        width = int(region.get("width") or default_w)
        height = int(region.get("height") or default_h)
        x_offset = int(region.get("x") or 0)
        y_offset = int(region.get("y") or 0)
        width = max(caps["min_width"], min(width, default_w))
        height = max(caps["min_height"], min(height, default_h))

        intent = options.get("intent") or "Document"
        if intent not in caps["intents"]:
            intent = caps["intents"][0]

        brightness = options.get("brightness")
        contrast = options.get("contrast")

        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<scan:ScanSettings xmlns:scan="%s" xmlns:pwg="%s">' % (ESCL_NS, PWG_NS),
            "<pwg:Version>2.6</pwg:Version>",
            "<pwg:ScanRegions><pwg:ScanRegion>",
            "<pwg:Height>%d</pwg:Height>" % height,
            "<pwg:Width>%d</pwg:Width>" % width,
            "<pwg:XOffset>%d</pwg:XOffset>" % x_offset,
            "<pwg:YOffset>%d</pwg:YOffset>" % y_offset,
            "</pwg:ScanRegion></pwg:ScanRegions>",
            "<pwg:InputSource>%s</pwg:InputSource>" % ("Adf" if options.get("source") == "adf" else "Platen"),
            "<scan:ColorMode>%s</scan:ColorMode>" % color_mode,
            "<scan:XResolution>%d</scan:XResolution>" % dpi,
            "<scan:YResolution>%d</scan:YResolution>" % dpi,
            "<pwg:DocumentFormat>%s</pwg:DocumentFormat>" % document_format,
            "<scan:Intent>%s</scan:Intent>" % intent,
        ]
        if brightness is not None:
            parts.append("<scan:Brightness>%d</scan:Brightness>" % int(brightness))
        if contrast is not None:
            parts.append("<scan:Contrast>%d</scan:Contrast>" % int(contrast))
        parts.append("</scan:ScanSettings>")
        return "".join(parts)

    def create_scan_job(self, settings_xml: str, timeout: float = 20.0,
                        retry_seconds: float = 90.0) -> str:
        """POST ScanJobs → 返回 job 的绝对 URL。

        实测：打印机在出纸 / 上一任务收尾期间会返回 503（哪怕 ScannerStatus 显示 Idle），
        通常 5~30 秒后自行恢复。因此这里做退避重试，而不是直接让用户看到「扫描仪正忙」。
        """
        payload = settings_xml.encode("utf-8")
        deadline = time.time() + max(0.0, retry_seconds)
        attempt = 0
        last_detail = ""
        while True:
            attempt += 1
            status, headers, data = self._request(
                "POST",
                PATH_JOBS,
                body=payload,
                headers={"Content-Type": "text/xml", "Content-Length": str(len(payload))},
                timeout=timeout,
            )
            if status in (200, 201):
                location = headers.get("location")
                if not location:
                    raise ProtocolError("扫描任务响应缺少 Location 头")
                if location.startswith("http://") or location.startswith("https://"):
                    return location.rstrip("/")
                if not location.startswith("/"):
                    location = "/" + location
                return "http://%s:%d%s" % (self.host, self.port, location.rstrip("/"))

            last_detail = data[:300].decode("utf-8", "replace")
            if status in (503, 409) and time.time() < deadline:
                wait = min(8.0, 2.0 + attempt * 1.5)
                log.info("扫描仪忙（HTTP %d），%.1fs 后重试（第 %d 次）", status, wait, attempt)
                time.sleep(wait)
                continue

            if status in (503, 409):
                raise HpError(
                    "扫描仪正忙，请稍候再试（已重试 %d 次）" % attempt,
                    detail=last_detail,
                    code="scanner_busy",
                )
            raise HpError("创建扫描任务失败（HTTP %d）" % status, detail=last_detail,
                          code="scan_job_failed")

    def next_document(
        self,
        job_url: str,
        deadline: float = 60.0,
        poll_start: float = 0.8,
        poll_max: float = 4.0,
        on_progress: Optional[Callable[[str, float], None]] = None,
        cancel_event=None,
    ) -> Optional[Tuple[bytes, str]]:
        """取下一张图像；没有更多页面时返回 ``None``。

        503 → 退避重试直到 ``deadline`` 秒；404/410 → 扫描结束。
        """
        url = job_url.rstrip("/") + "/NextDocument"
        path = url.split("://", 1)[1]
        path = path[path.find("/"):] if "/" in path else "/"
        started = time.time()
        delay = poll_start
        attempt = 0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise HpError("扫描已取消", code="canceled")
            elapsed = time.time() - started
            if elapsed > deadline:
                raise HpError(
                    "等待扫描仪出图超时（%.0f 秒）。设备可能正忙，请稍候再试。" % deadline,
                    code="scan_timeout",
                )
            attempt += 1
            try:
                status, headers, data = self._request(
                    "GET", path, timeout=min(120.0, deadline + 30)
                )
            except PrinterOffline:
                raise
            if status == 200:
                content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
                if not content_type:
                    content_type = "application/pdf" if data[:4] == b"%PDF" else "image/jpeg"
                if on_progress is not None:
                    on_progress("已获取扫描图像", 0.85)
                return data, content_type
            if status in (404, 410):
                return None
            if status == 503:
                if on_progress is not None:
                    on_progress("扫描仪正在出图（第 %d 次等待）" % attempt, min(0.8, 0.2 + elapsed / deadline * 0.6))
                time.sleep(delay)
                delay = min(poll_max, delay * 1.4)
                continue
            detail = data[:300].decode("utf-8", "replace")
            raise HpError("获取扫描图像失败（HTTP %d）" % status, detail=detail, code="scan_fetch_failed")

    def cancel_job(self, job_url: str) -> bool:
        path = job_url.split("://", 1)[-1]
        path = path[path.find("/"):] if "/" in path else "/"
        try:
            status, _headers, _data = self._request("DELETE", path, timeout=8)
        except HpError as exc:
            log.warning("取消扫描任务失败: %s", exc)
            return False
        return 200 <= status < 300

    def scan(
        self,
        options: Dict[str, Any],
        on_progress: Optional[Callable[[str, float], None]] = None,
        cancel_event=None,
        max_pages: int = 20,
        page_deadline: float = 60.0,
    ) -> List[Tuple[bytes, str]]:
        """执行一次扫描，返回 ``[(字节, content-type), ...]``（平台式只有 1 页）。"""
        caps = self.capabilities()
        if on_progress is not None:
            on_progress("正在读取扫描仪能力", 0.05)
        settings = self.build_settings(options, caps)
        job_url = self.create_scan_job(settings)
        log.info("扫描任务已创建: %s", job_url)
        if on_progress is not None:
            on_progress("扫描任务已提交，等待出图", 0.2)

        documents: List[Tuple[bytes, str]] = []
        for index in range(max_pages):
            result = self.next_document(
                job_url,
                deadline=page_deadline,
                on_progress=on_progress,
                cancel_event=cancel_event,
            )
            if result is None:
                break
            documents.append(result)
            if on_progress is not None:
                on_progress("已获取第 %d 页" % (index + 1), min(0.95, 0.6 + 0.1 * index))
            # 平台式扫描只会有一页
            if not caps.get("adf") or options.get("source") != "adf":
                break
        if not documents:
            raise HpError("扫描仪没有返回任何图像，请检查原件是否放好", code="scan_empty")
        return documents


def is_escl_scanner(host: str, timeout: float = 3.0) -> bool:
    """探测主机是否提供 eSCL 扫描服务。"""
    return EsclClient(host, timeout=timeout).is_scanner(timeout=timeout)


def auto_crop(image_bytes: bytes, tolerance: int = 12) -> bytes:
    """裁掉纯色（白）边框，返回 JPEG 字节。失败时原样返回。"""
    try:
        from PIL import Image, ImageChops
    except ImportError:  # pragma: no cover - Pillow 已安装
        return image_bytes
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB")
            background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
            diff = ImageChops.difference(rgb, background)
            bbox = diff.point(lambda p: 255 if p > tolerance else 0).getbbox()
            if not bbox:
                return image_bytes
            # 留一点边距
            pad = 8
            left = max(0, bbox[0] - pad)
            top = max(0, bbox[1] - pad)
            right = min(rgb.width, bbox[2] + pad)
            bottom = min(rgb.height, bbox[3] + pad)
            if (right - left) < 32 or (bottom - top) < 32:
                return image_bytes
            cropped = rgb.crop((left, top, right, bottom))
            out = io.BytesIO()
            cropped.save(out, "JPEG", quality=92, progressive=False, optimize=False)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001 - 裁剪失败不应让扫描失败
        log.warning("自动裁剪失败，保留原图: %s", exc)
        return image_bytes
