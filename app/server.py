"""HTTP 服务：``python app/server.py`` → http://127.0.0.1:8791

只用标准库（``http.server.ThreadingHTTPServer`` + ``BaseHTTPRequestHandler``）：
    * ``/api/*``   JSON 接口（契约见 docs/api.md）
    * 其余路径     静态文件，来自 ``app/ui/``，``/`` 返回 index.html
    * ``/api/events`` Server-Sent Events（job / printer / scan）

所有面向用户的错误信息都是中文，格式 ``{"error": "<code>", "message": "<中文>"}``。
"""

from __future__ import annotations

import email.parser
import email.policy
import json
import mimetypes
import os
import queue
import re
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

if __package__ in (None, ""):  # 支持 `python app/server.py` 直接运行
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app import DATA_DIR, ROOT_DIR, UI_DIR, __version__, get_logger, setup_logging
    from app.hp import HpError
    from app.hp.service import PrinterService
    from app.store import Store
else:
    from . import DATA_DIR, ROOT_DIR, UI_DIR, __version__, get_logger, setup_logging
    from .hp import HpError
    from .hp.service import PrinterService
    from .store import Store

log = get_logger("server")

HOST = "127.0.0.1"
PORT = 8791
MAX_BODY = 64 * 1024 * 1024  # 64 MiB

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

#: 错误码 → HTTP 状态码
ERROR_STATUS = {
    "bad_request": 400,
    "unsupported_file": 400,
    "bad_file": 400,
    "render_failed": 400,
    "not_found": 404,
    "printer_not_found": 404,
    "job_finished": 409,
    "bad_state": 409,
    "device_busy": 409,
    "not_supported": 400,
    "canceled": 409,
    "printer_offline": 503,
    "scanner_busy": 503,
    "scan_timeout": 504,
}

PLACEHOLDER_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>HP Offline —— 后端已启动</title>
<style>
 body{font-family:system-ui,"Segoe UI",sans-serif;background:#0f1115;color:#e8ecf1;
      margin:0;display:grid;place-items:center;min-height:100vh}
 main{max-width:640px;padding:32px;border:1px solid #262b33;border-radius:14px;background:#151a21}
 h1{margin:0 0 8px;font-size:20px;color:#fff}
 p{color:#9aa4b2;line-height:1.7;margin:8px 0}
 code{background:#0b0e12;padding:2px 6px;border-radius:5px;color:#7cc7ff}
 .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#3ddc97;margin-right:8px}
 a{color:#4aa8ff}
</style></head>
<body><main>
<h1><span class="dot"></span>HP Offline 后端运行中</h1>
<p>前端界面（<code>app/ui/index.html</code>）尚未就绪，由另一个构建流程生成。</p>
<p>接口可以直接访问：<a href="/api/health">/api/health</a> ·
<a href="/api/printers">/api/printers</a> · <a href="/api/settings">/api/settings</a></p>
<p>版本 <code>__VERSION__</code> —— 纯本地运行，零云端调用。</p>
</main></body></html>""".replace("__VERSION__", __version__)


# ---------------------------------------------------------------------------
# 路由辅助
# ---------------------------------------------------------------------------


class Route:
    __slots__ = ("method", "pattern", "handler")

    def __init__(self, method: str, pattern: str, handler: Callable):
        self.method = method
        self.pattern = re.compile(pattern)
        self.handler = handler


class HttpError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class Handler(BaseHTTPRequestHandler):
    """所有请求的入口。"""

    server_version = "HPOffline/" + __version__
    protocol_version = "HTTP/1.1"

    # 由 HPHTTPServer 注入
    service: PrinterService = None  # type: ignore[assignment]

    # -- 基础输出 ---------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send_bytes(
        self,
        status: int,
        payload: bytes,
        content_type: str = "application/octet-stream",
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _send_json(self, status: int, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, payload, "application/json; charset=utf-8")

    def _send_error(self, status: int, code: str, message: str) -> None:
        self._send_json(status, {"error": code, "message": message})

    # -- 请求解析 ---------------------------------------------------------
    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return b""
        if length > MAX_BODY:
            raise HttpError(413, "too_large", "请求体过大（上限 64MB）")
        return self.rfile.read(length)

    def _json_body(self) -> Dict[str, Any]:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpError(400, "bad_json", "请求体不是合法的 JSON：%s" % exc)
        if not isinstance(data, dict):
            raise HttpError(400, "bad_json", "请求体必须是 JSON 对象")
        return data

    def _parse_multipart(self, body: bytes, content_type: str) -> List[Tuple[str, bytes]]:
        """返回 [(文件名, 字节)]。"""
        if "boundary=" not in content_type:
            raise HttpError(400, "bad_multipart", "上传请求缺少 multipart 边界")
        header = (
            "Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n"
        ).encode("utf-8")
        try:
            message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
                header + body
            )
        except Exception as exc:  # noqa: BLE001
            raise HttpError(400, "bad_multipart", "无法解析上传内容：%s" % exc)
        files: List[Tuple[str, bytes]] = []
        if not message.is_multipart():
            raise HttpError(400, "bad_multipart", "上传请求不是 multipart/form-data")
        for part in message.iter_parts():
            filename = part.get_filename()
            if not filename:
                continue
            data = part.get_payload(decode=True)
            if data is None:
                continue
            files.append((filename, data))
        return files

    # -- 方法分发 ---------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Allow", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _dispatch(self, method: str) -> None:
        started = time.time()
        parts = urlsplit(self.path)
        path = unquote(parts.path)
        query = parse_qs(parts.query)
        try:
            if path == "/api/events" and method == "GET":
                self._handle_events()
                return
            if path.startswith("/api/"):
                self._handle_api(method, path, query)
            else:
                self._serve_static(path)
        except HttpError as exc:
            self._send_error(exc.status, exc.code, exc.message)
        except HpError as exc:
            status = ERROR_STATUS.get(exc.code, 500)
            log.warning("%s %s 失败: %s（%s）", method, path, exc.message, exc.detail)
            self._send_json(
                status,
                {"error": exc.code, "message": exc.message, "detail": exc.detail or ""},
            )
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            log.debug("客户端提前断开: %s %s", method, path)
        except Exception as exc:  # noqa: BLE001
            log.error("处理 %s %s 时出现未捕获异常: %s\n%s", method, path, exc,
                      traceback.format_exc())
            try:
                self._send_error(500, "internal_error", "服务器内部错误：%s" % exc)
            except OSError:
                pass
        finally:
            log.debug("%s %s %.0fms", method, path, (time.time() - started) * 1000)

    # =====================================================================
    # API
    # =====================================================================
    def _handle_api(self, method: str, path: str, query: Dict[str, List[str]]) -> None:
        service = self.service

        # ---- 系统 ----
        if method == "GET" and path == "/api/health":
            self._send_json(200, service.health())
            return

        # ---- 打印机 ----
        if method == "GET" and path == "/api/printers":
            self._send_json(200, {"printers": service.list_printers()})
            return

        if method == "POST" and path == "/api/printers/discover":
            found = service.discover()
            self._send_json(200, {"found": found})
            return

        if method == "POST" and path == "/api/printers":
            body = self._json_body()
            host = str(body.get("host") or "").strip()
            printer = service.add_printer(host)
            self._send_json(200, {"printer": service.printer_summary(printer["id"])})
            return

        match = re.fullmatch(r"/api/printers/([^/]+)/status", path)
        if match and method == "GET":
            printer_id = match.group(1)
            refresh = (query.get("refresh") or ["0"])[0] not in ("0", "", "false", "False")
            self._send_json(200, service.status(printer_id, refresh=refresh))
            return

        match = re.fullmatch(r"/api/printers/([^/]+)/default", path)
        if match and method == "POST":
            service.set_default(match.group(1))
            self._send_json(200, {"ok": True})
            return

        match = re.fullmatch(r"/api/printers/([^/]+)/reports", path)
        if match and method == "GET":
            self._send_json(200, service.reports(match.group(1)))
            return

        match = re.fullmatch(r"/api/printers/([^/]+)/maintenance", path)
        if match and method == "POST":
            body = self._json_body()
            action = str(body.get("action") or "").strip()
            result = service.maintenance(match.group(1), action)
            self._send_json(200, result)
            return

        match = re.fullmatch(r"/api/printers/([^/]+)", path)
        if match and method == "DELETE":
            service.remove_printer(match.group(1))
            self._send_json(200, {"ok": True})
            return

        # ---- 复印（本地 扫描→打印 流水线）----
        if method == "POST" and path == "/api/copy":
            body = self._json_body()
            printer_id = str(body.get("printer_id") or "").strip()
            if not printer_id:
                raise HttpError(400, "bad_request", "缺少 printer_id")
            result = service.copy(printer_id, body.get("options") or {})
            self._send_json(200, result)
            return

        # ---- 打印 ----
        if method == "POST" and path == "/api/print/upload":
            body = self._read_body()
            content_type = self.headers.get("Content-Type") or ""
            files = self._parse_multipart(body, content_type)
            if not files:
                raise HttpError(400, "no_files", "没有收到任何文件（字段名应为 files）")
            results = []
            for filename, data in files:
                results.append(service.upload(filename, data))
            self._send_json(200, {"files": results})
            return

        match = re.fullmatch(r"/api/print/thumb/([^/]+)/(\d+)", path)
        if match and method == "GET":
            preview_keys = ("dpi", "color", "quality", "scale", "media", "orientation", "max_px")
            options = {}
            for key in preview_keys:
                values = query.get(key)
                if values and values[0]:
                    options[key] = values[0]
            data = service.thumb(match.group(1), int(match.group(2)), options or None)
            self._send_bytes(200, data, "image/png")
            return

        if method == "POST" and path == "/api/print":
            body = self._json_body()
            printer_id = str(body.get("printer_id") or "").strip()
            if not printer_id:
                default = service.store.default_printer()
                if default is None:
                    raise HttpError(400, "no_printer", "请先选择打印机")
                printer_id = default["id"]
            tokens = body.get("files") or []
            if isinstance(tokens, str):
                tokens = [tokens]
            options = body.get("options") or {}
            if not isinstance(options, dict):
                raise HttpError(400, "bad_options", "options 必须是对象")
            job_id = service.start_print(printer_id, list(tokens), options)
            self._send_json(200, {"job_id": job_id})
            return

        # ---- 任务 ----
        if method == "GET" and path == "/api/jobs":
            limit = int((query.get("limit") or ["50"])[0] or 50)
            kind = (query.get("kind") or [None])[0]
            if kind not in (None, "print", "scan"):
                raise HttpError(400, "bad_kind", "kind 只能是 print 或 scan")
            self._send_json(200, {"jobs": service.list_jobs(limit, kind)})
            return

        match = re.fullmatch(r"/api/jobs/(\d+)", path)
        if match and method == "GET":
            self._send_json(200, service.get_job(int(match.group(1))))
            return

        match = re.fullmatch(r"/api/jobs/(\d+)/cancel", path)
        if match and method == "POST":
            job = service.cancel_job(int(match.group(1)))
            self._send_json(200, {"ok": True, "job": job})
            return

        match = re.fullmatch(r"/api/jobs/(\d+)/pause", path)
        if match and method == "POST":
            self._send_json(200, {"ok": True, "job": service.pause_job(int(match.group(1)))})
            return

        match = re.fullmatch(r"/api/jobs/(\d+)/resume", path)
        if match and method == "POST":
            self._send_json(200, {"ok": True, "job": service.resume_job(int(match.group(1)))})
            return

        match = re.fullmatch(r"/api/jobs/(\d+)/retry", path)
        if match and method == "POST":
            self._send_json(200, service.retry_job(int(match.group(1))))
            return

        # ---- 扫描 ----
        if method == "POST" and path == "/api/scan":
            body = self._json_body()
            printer_id = str(body.get("printer_id") or "").strip()
            if not printer_id:
                default = service.store.default_printer()
                if default is None:
                    raise HttpError(400, "no_printer", "请先选择打印机")
                printer_id = default["id"]
            options = body.get("options") or {}
            if not isinstance(options, dict):
                raise HttpError(400, "bad_options", "options 必须是对象")
            job_id = service.start_scan(printer_id, options)
            self._send_json(200, {"job_id": job_id})
            return

        if method == "GET" and path == "/api/scans":
            limit = int((query.get("limit") or ["50"])[0] or 50)
            self._send_json(200, {"scans": service.list_scans(limit)})
            return

        match = re.fullmatch(r"/api/scans/(\d+)/file", path)
        if match and method == "GET":
            filename, data, mime = service.scan_file(int(match.group(1)))
            disposition = 'inline; filename="%s"' % filename.replace('"', "")
            self._send_bytes(
                200, data, mime, {"Content-Disposition": disposition}
            )
            return

        match = re.fullmatch(r"/api/scans/(\d+)/thumb", path)
        if match and method == "GET":
            self._send_bytes(200, service.scan_thumb(int(match.group(1))), "image/png")
            return

        match = re.fullmatch(r"/api/scans/(\d+)/email", path)
        if match and method == "POST":
            body = self._json_body()
            result = service.email_scan(
                int(match.group(1)),
                to=body.get("to"),
                subject=body.get("subject"),
                body=body.get("body"),
            )
            self._send_json(200, result)
            return

        match = re.fullmatch(r"/api/scans/(\d+)", path)
        if match and method == "DELETE":
            service.delete_scan(int(match.group(1)))
            self._send_json(200, {"ok": True})
            return

        # ---- 快捷方式（本地替代 Smart Tasks）----
        if method == "GET" and path == "/api/shortcuts":
            self._send_json(200, {"shortcuts": service.list_shortcuts()})
            return

        if method == "POST" and path == "/api/shortcuts":
            body = self._json_body()
            item = service.add_shortcut(
                body.get("name") or "",
                body.get("icon") or "scan",
                body.get("steps") or ["save"],
                body.get("scan_options") or {},
            )
            self._send_json(200, {"shortcut": item})
            return

        match = re.fullmatch(r"/api/shortcuts/(\d+)/run", path)
        if match and method == "POST":
            self._send_json(200, service.run_shortcut(int(match.group(1))))
            return

        match = re.fullmatch(r"/api/shortcuts/(\d+)", path)
        if match and method == "DELETE":
            service.delete_shortcut(int(match.group(1)))
            self._send_json(200, {"ok": True})
            return

        # ---- 设置 ----
        if method == "POST" and path == "/api/settings/browse-dir":
            body = self._json_body()
            self._send_json(200, service.browse_dir(body.get("initial")))
            return

        if method == "GET" and path == "/api/settings":
            self._send_json(200, service.get_settings())
            return

        if method == "PATCH" and path == "/api/settings":
            body = self._json_body()
            self._send_json(200, service.patch_settings(body))
            return

        if path.startswith("/api/"):
            raise HttpError(404, "unknown_endpoint", "接口不存在：%s" % path)

    # =====================================================================
    # SSE
    # =====================================================================
    def _handle_events(self) -> None:
        channel = self.service.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        try:
            hello = json.dumps(
                {"type": "hello", "version": __version__, "cloud_calls": 0},
                ensure_ascii=False,
            )
            self.wfile.write(("event: hello\ndata: %s\n\n" % hello).encode("utf-8"))
            self.wfile.flush()
            while True:
                try:
                    event = channel.get(timeout=15.0)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                payload = json.dumps(event, ensure_ascii=False)
                name = event.get("type", "message")
                self.wfile.write(
                    ("event: %s\ndata: %s\n\n" % (name, payload)).encode("utf-8")
                )
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            log.debug("SSE 客户端断开")
        finally:
            self.service.unsubscribe(channel)

    # =====================================================================
    # 静态文件
    # =====================================================================
    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"

        relative = path.lstrip("/").replace("\\", "/")
        if ".." in relative.split("/"):
            raise HttpError(403, "forbidden", "非法路径")

        ui_root = os.path.realpath(UI_DIR)
        candidate = os.path.realpath(os.path.join(ui_root, relative))
        if not candidate.startswith(ui_root):
            raise HttpError(403, "forbidden", "非法路径")

        if os.path.isfile(candidate):
            with open(candidate, "rb") as handle:
                data = handle.read()
            ext = os.path.splitext(candidate)[1].lower()
            mime = MIME_TYPES.get(ext) or mimetypes.guess_type(candidate)[0] or "application/octet-stream"
            self._send_bytes(200, data, mime)
            return

        if relative == "index.html":
            # 前端尚未生成时给出占位页（绝不写入 app/ui/）
            log.warning("app/ui/index.html 不存在，返回占位页面")
            self._send_bytes(200, PLACEHOLDER_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return

        # 单页应用回退：未知路径交给 index.html 处理
        index_path = os.path.join(ui_root, "index.html")
        if os.path.isfile(index_path):
            with open(index_path, "rb") as handle:
                data = handle.read()
            self._send_bytes(200, data, "text/html; charset=utf-8")
            return

        raise HttpError(404, "not_found", "文件不存在：%s" % path)


class HPHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], service: PrinterService):
        self.service = service
        handler = type("BoundHandler", (Handler,), {"service": service})
        super().__init__(address, handler)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------


def _bootstrap_printer(service: PrinterService) -> None:
    """首次启动（库里没有打印机）时自动发现并保存第一台设备。"""
    try:
        settings = service.store.get_settings()
        if not settings.get("auto_discover", True):
            return
        if service.store.list_printers():
            return
        log.info("库中没有打印机，开始自动发现…")
        found = service.discover()
        if not found:
            log.warning("自动发现没有找到打印机")
            return
        target = found[0]
        printer = service.add_printer(target["host"])
        log.info("已自动添加打印机 %s @ %s", printer.get("model"), printer.get("host"))
    except Exception as exc:  # noqa: BLE001
        log.warning("自动发现失败: %s", exc)


def build_service() -> PrinterService:
    store = Store()
    service = PrinterService(store)
    return service


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    host = HOST
    port = PORT
    for index, arg in enumerate(argv):
        if arg in ("--host", "-H") and index + 1 < len(argv):
            host = argv[index + 1]
        elif arg in ("--port", "-p") and index + 1 < len(argv):
            port = int(argv[index + 1])

    setup_logging()
    log.info("HP Offline %s 启动中…", __version__)
    service = build_service()

    try:
        server = HPHTTPServer((host, port), service)
    except OSError as exc:
        # 端口被占用时自动向后找空闲端口（兼容多实例 / 端口被别的程序占了的情况）
        server = None
        for offset in range(1, 11):
            try:
                server = HPHTTPServer((host, port + offset), service)
                log.warning("端口 %d 被占用（%s），改用 %d", port, exc, port + offset)
                port = port + offset
                break
            except OSError:
                continue
        if server is None:
            log.error("无法监听 %s:%d 及其后 10 个端口，请手动指定 --port", host, port)
            return 1

    try:
        with open(os.path.join(DATA_DIR, "port.txt"), "w", encoding="ascii") as handle:
            handle.write(str(port))
    except OSError:
        pass

    service.start_poller()
    threading.Thread(target=_bootstrap_printer, args=(service,), name="bootstrap", daemon=True).start()

    log.info("服务已就绪: http://%s:%d  （数据目录 %s）", host, port, DATA_DIR)
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        log.info("收到中断信号，正在关闭…")
    finally:
        service.stop_poller()
        server.shutdown()
        server.server_close()
        service.store.close()
        log.info("服务已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
