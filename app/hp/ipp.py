"""IPP 2.0 客户端（RFC 8010 / RFC 8011），仅依赖标准库。

设计要点
--------
1. **编码布局**：``value-tag | name-length | name | value-length | value``。
   值本身**不带 tag**；只有同名多值时，后续每个值才重复一次 value-tag + 零长度
   name。（多写一个 tag 字节 → 打印机稳定返回 0x0400 client-error-bad-request。）
   本文件的 :func:`encode_attribute` 与 tools/ipp_probe.py 的已验证实现一致。
2. **传输**：``http.client`` 直连，``ipp://`` → 631 明文，``ipps://`` → 443 TLS
   （关闭证书校验，打印机自签名）。不使用 urllib 以避免代理环境影响。
3. **解码**：容忍同名重复（本机 HP 会把多值属性的 name 重复写出来），
   连续同名属性合并为一个多值属性；支持 collection（0x34/0x37）。
4. **文本解码**：设备可能返回 GB18030 编码的中文（如 printer-supply-description
   实际是「黑色墨水」的 GBK 字节），因此按 utf-8 → gb18030 依次尝试。
"""

from __future__ import annotations

import http.client
import socket
import ssl
import struct
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .. import get_logger
from . import HpError, PrinterOffline, ProtocolError

log = get_logger("hp.ipp")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

IPP_VERSION_MAJOR = 2
IPP_VERSION_MINOR = 0

# 操作码
OP_PRINT_JOB = 0x0002
OP_VALIDATE_JOB = 0x0004
OP_CREATE_JOB = 0x0005
OP_SEND_DOCUMENT = 0x0006
OP_CANCEL_JOB = 0x0008
OP_GET_JOB_ATTRIBUTES = 0x0009
OP_GET_PRINTER_ATTRIBUTES = 0x000B

OPERATION_NAMES = {
    OP_PRINT_JOB: "Print-Job",
    OP_VALIDATE_JOB: "Validate-Job",
    OP_CREATE_JOB: "Create-Job",
    OP_SEND_DOCUMENT: "Send-Document",
    OP_CANCEL_JOB: "Cancel-Job",
    OP_GET_JOB_ATTRIBUTES: "Get-Job-Attributes",
    OP_GET_PRINTER_ATTRIBUTES: "Get-Printer-Attributes",
}

# 组定界符
TAG_OPERATION_ATTRS = 0x01
TAG_JOB_ATTRS = 0x02
TAG_END_ATTRS = 0x03
TAG_PRINTER_ATTRS = 0x04
TAG_UNSUPPORTED_ATTRS = 0x05
TAG_SUBSCRIPTION_ATTRS = 0x06
TAG_EVENT_NOTIFICATION_ATTRS = 0x07
TAG_RESOURCE_ATTRS = 0x08
TAG_DOCUMENT_ATTRS = 0x09
TAG_SYSTEM_ATTRS = 0x0A

GROUP_NAMES = {
    TAG_OPERATION_ATTRS: "operation-attributes",
    TAG_JOB_ATTRS: "job-attributes",
    TAG_END_ATTRS: "end-of-attributes",
    TAG_PRINTER_ATTRS: "printer-attributes",
    TAG_UNSUPPORTED_ATTRS: "unsupported-attributes",
    TAG_SUBSCRIPTION_ATTRS: "subscription-attributes",
    TAG_EVENT_NOTIFICATION_ATTRS: "event-notification-attributes",
    TAG_RESOURCE_ATTRS: "resource-attributes",
    TAG_DOCUMENT_ATTRS: "document-attributes",
    TAG_SYSTEM_ATTRS: "system-attributes",
}

# 值标签
T_UNSUPPORTED = 0x10
T_DEFAULT = 0x11
T_UNKNOWN = 0x12
T_NO_VALUE = 0x13
T_NOT_SETTABLE = 0x15
T_DELETE_ATTR = 0x16
T_ADMIN_DEFINE = 0x17
T_INTEGER = 0x21
T_BOOLEAN = 0x22
T_ENUM = 0x23
T_OCTET_STRING = 0x30
T_DATE_TIME = 0x31
T_RESOLUTION = 0x32
T_RANGE = 0x33
T_BEG_COLLECTION = 0x34
T_TEXT_WITH_LANG = 0x35
T_NAME_WITH_LANG = 0x36
T_END_COLLECTION = 0x37
T_TEXT = 0x41
T_NAME = 0x42
T_KEYWORD = 0x44
T_URI = 0x45
T_URI_SCHEME = 0x46
T_CHARSET = 0x47
T_NATURAL_LANGUAGE = 0x48
T_MIME_TYPE = 0x49
T_MEMBER_NAME = 0x4A

_STRING_TAGS = {
    T_TEXT,
    T_NAME,
    T_KEYWORD,
    T_URI,
    T_URI_SCHEME,
    T_CHARSET,
    T_NATURAL_LANGUAGE,
    T_MIME_TYPE,
    T_MEMBER_NAME,
    T_OCTET_STRING,
}

STATUS_NAMES = {
    0x0000: "successful-ok",
    0x0001: "successful-ok-ignored-or-substituted-attributes",
    0x0002: "successful-ok-conflicting-attributes",
    0x0400: "client-error-bad-request",
    0x0401: "client-error-forbidden",
    0x0402: "client-error-not-authenticated",
    0x0403: "client-error-not-authorized",
    0x0404: "client-error-not-possible",
    0x0405: "client-error-timeout",
    0x0406: "client-error-not-found",
    0x0407: "client-error-gone",
    0x0408: "client-error-request-entity-too-large",
    0x0409: "client-error-request-value-too-long",
    0x040A: "client-error-document-format-not-supported",
    0x040B: "client-error-attributes-or-values-not-supported",
    0x040C: "client-error-uri-scheme-not-supported",
    0x040D: "client-error-charset-not-supported",
    0x040E: "client-error-conflicting-attributes",
    0x040F: "client-error-compression-not-supported",
    0x0410: "client-error-compression-error",
    0x0411: "client-error-document-format-error",
    0x0412: "client-error-document-access-error",
    0x0413: "client-error-attributes-not-settable",
    0x0414: "client-error-ignored-all-subscriptions",
    0x0415: "client-error-too-many-subscriptions",
    0x0416: "client-error-request-value-too-long",
    0x0417: "client-error-request-entity-too-large",
    0x0418: "client-error-document-format-error",
    0x0500: "server-error-internal-error",
    0x0501: "server-error-operation-not-supported",
    0x0502: "server-error-service-unavailable",
    0x0503: "server-error-version-not-supported",
    0x0504: "server-error-device-error",
    0x0505: "server-error-temporary-error",
    0x0506: "server-error-not-accepting-jobs",
    0x0507: "server-error-busy",
    0x0508: "server-error-job-canceled",
    0x0509: "server-error-multiple-document-jobs-not-supported",
}

#: IPP job-state → 中文说明
JOB_STATE_NAMES = {
    3: "pending",
    4: "pending-held",
    5: "processing",
    6: "stopped",
    7: "canceled",
    8: "aborted",
    9: "completed",
}

#: IPP printer-state → 应用状态
PRINTER_STATE_MAP = {3: "idle", 4: "processing", 5: "stopped"}

#: print-quality 枚举
QUALITY_ENUM = {"draft": 3, "normal": 4, "best": 5}

#: 打印用途的默认请求属性
DEFAULT_IPP_PATH = "/ipp/print"


def status_name(code: int) -> str:
    return STATUS_NAMES.get(code, "0x%04X" % code)


def _decode_text(raw: bytes) -> str:
    """设备文本解码：utf-8 优先，失败回退 gb18030（本机中文属性为 GBK）。"""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# 编码
# ---------------------------------------------------------------------------


def _encode_single_value(tag: int, value: Any) -> bytes:
    """编码单个值（长度 + 负载，**不含 tag 字节**）。"""
    if isinstance(value, bool):
        raw = bytes([1 if value else 0])
    elif isinstance(value, int):
        if tag == T_BOOLEAN:
            raw = bytes([1 if value else 0])
        elif tag in (T_INTEGER, T_ENUM):
            raw = struct.pack(">i", int(value))
        else:
            raw = struct.pack(">i", int(value))
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    elif isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, tuple) and tag == T_RESOLUTION:
        x, y = int(value[0]), int(value[1])
        units = int(value[2]) if len(value) > 2 else 3  # 3 = dpi
        raw = struct.pack(">iib", x, y, units)
    elif isinstance(value, tuple) and tag == T_RANGE:
        raw = struct.pack(">ii", int(value[0]), int(value[1]))
    elif isinstance(value, (list, dict)):
        raise ValueError("collection 值请使用 encode_collection")
    else:
        raise TypeError("不支持的 IPP 值类型: %r" % (type(value),))
    return struct.pack(">H", len(raw)) + raw


def encode_attribute(tag: int, name: str, values: Sequence[Any]) -> bytes:
    """编码一个属性（可多值）。

    ``value-tag | name-len | name | value-len | value``，多值时后续值重复
    value-tag 但 name-len 为 0。
    """
    if isinstance(values, (str, bytes, int, float, bool)):
        values = [values]
    name_b = name.encode("utf-8")
    out = bytearray()
    for idx, value in enumerate(values):
        out.append(tag & 0xFF)
        if idx == 0:
            out += struct.pack(">H", len(name_b)) + name_b
        else:
            out += struct.pack(">H", 0)
        out += _encode_single_value(tag, value)
    return bytes(out)


def encode_collection(name: str, members: Dict[str, Tuple[int, Any]]) -> bytes:
    """编码 collection 属性（begCollection ... endCollection）。

    ``members``: ``{成员名: (value_tag, 值)}``，按插入顺序输出。
    """
    name_b = name.encode("utf-8")
    out = bytearray()
    first = True
    for member_name, (mtag, mvalue) in members.items():
        if first:
            out.append(T_BEG_COLLECTION)
            out += struct.pack(">H", len(name_b)) + name_b
            raw = member_name.encode("utf-8")
            out += struct.pack(">H", len(raw)) + raw
            first = False
        out.append(mtag & 0xFF)
        out += struct.pack(">H", 0)
        out += _encode_single_value(mtag, mvalue)
    out.append(T_END_COLLECTION)
    out += struct.pack(">H", 0)
    out += struct.pack(">H", 0)
    return bytes(out)


def build_request(
    operation: int,
    operation_attributes: Iterable[Tuple[int, str, Sequence[Any]]],
    job_attributes: Optional[Iterable[Tuple[int, str, Sequence[Any]]]] = None,
    data: bytes = b"",
    request_id: int = 1,
) -> bytes:
    """构造完整 IPP 请求体。"""
    body = bytearray(struct.pack(">BBHI", IPP_VERSION_MAJOR, IPP_VERSION_MINOR, operation, request_id))
    body.append(TAG_OPERATION_ATTRS)
    for tag, name, values in operation_attributes:
        body += encode_attribute(tag, name, values)
    if job_attributes:
        body.append(TAG_JOB_ATTRS)
        for tag, name, values in job_attributes:
            body += encode_attribute(tag, name, values)
    body.append(TAG_END_ATTRS)
    return bytes(body) + data


# ---------------------------------------------------------------------------
# 解码
# ---------------------------------------------------------------------------


def _decode_scalar(tag: int, raw: bytes) -> Any:
    if tag in _STRING_TAGS:
        return _decode_text(raw)
    if tag in (T_INTEGER, T_ENUM):
        if len(raw) == 4:
            return struct.unpack(">i", raw)[0]
        if not raw:
            return None
        return int.from_bytes(raw, "big", signed=True)
    if tag == T_BOOLEAN:
        return bool(raw[0]) if raw else None
    if tag == T_RESOLUTION:
        if len(raw) >= 9:
            x, y, units = struct.unpack(">iib", raw[:9])
            return {"x": x, "y": y, "units": units}
        return raw.hex()
    if tag == T_RANGE:
        if len(raw) == 8:
            low, high = struct.unpack(">ii", raw)
            return {"low": low, "high": high}
        return raw.hex()
    if tag == T_DATE_TIME:
        if len(raw) == 11:
            year = struct.unpack(">H", raw[0:2])[0]
            return "%04d-%02d-%02dT%02d:%02d:%02d.%03d%s" % (
                year,
                raw[2],
                raw[3],
                raw[4],
                raw[5],
                raw[6],
                int.from_bytes(raw[7:9], "big"),
                ("+" if raw[9] == 0x2B else "-") + "%02d%02d" % (raw[9] & 0x0F, raw[10]),
            )
        return raw.hex()
    if tag in (T_TEXT_WITH_LANG, T_NAME_WITH_LANG):
        if len(raw) >= 4:
            lang_len = struct.unpack(">H", raw[0:2])[0]
            lang = _decode_text(raw[2 : 2 + lang_len])
            text_len = struct.unpack(">H", raw[2 + lang_len : 4 + lang_len])[0]
            text = _decode_text(raw[4 + lang_len : 4 + lang_len + text_len])
            return {"language": lang, "text": text}
        return raw.hex()
    if tag in (T_UNSUPPORTED, T_UNKNOWN, T_NO_VALUE, T_NOT_SETTABLE, T_DEFAULT, T_DELETE_ATTR):
        return None
    if tag == T_ADMIN_DEFINE:
        return _decode_text(raw)
    try:
        return _decode_text(raw)
    except Exception:  # pragma: no cover - 兜底
        return raw.hex()


class IppResponse:
    """解析后的 IPP 响应。"""

    __slots__ = ("version", "status", "request_id", "groups", "raw")

    def __init__(self, version: Tuple[int, int], status: int, request_id: int,
                 groups: List[Dict[str, Any]], raw: bytes):
        self.version = version
        self.status = status
        self.request_id = request_id
        self.groups = groups
        self.raw = raw

    # -- 便捷访问 ---------------------------------------------------------
    @property
    def ok(self) -> bool:
        return self.status < 0x0100

    @property
    def status_text(self) -> str:
        return status_name(self.status)

    def group(self, tag: int) -> Optional[Dict[str, Any]]:
        for grp in self.groups:
            if grp["tag"] == tag:
                return grp
        return None

    def attributes(self, tag: Optional[int] = None) -> Dict[str, Any]:
        """返回 ``{属性名: 值或值列表}``（同名多值 → list）。"""
        out: Dict[str, Any] = {}
        for grp in self.groups:
            if tag is not None and grp["tag"] != tag:
                continue
            for attr in grp["attrs"]:
                values = attr["values"]
                value = values[0] if len(values) == 1 else list(values)
                out[attr["name"]] = value
        return out

    def get(self, name: str, default: Any = None) -> Any:
        attrs = self.attributes()
        return attrs.get(name, default)

    def get_list(self, name: str) -> List[Any]:
        value = self.get(name)
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<IppResponse 0x%04X %s groups=%d>" % (self.status, self.status_text, len(self.groups))


def parse_response(raw: bytes) -> IppResponse:
    """解析 IPP 响应字节流。"""
    if len(raw) < 8:
        raise ProtocolError("IPP 响应过短，无法解析", detail=raw[:32].hex())

    major, minor = raw[0], raw[1]
    status = struct.unpack(">H", raw[2:4])[0]
    request_id = struct.unpack(">I", raw[4:8])[0]

    groups: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    # collection 栈：[(attr_dict, collection_dict, current_member_name)]
    stack: List[List[Any]] = []
    last_attr: Optional[Dict[str, Any]] = None

    i = 8
    n = len(raw)
    while i < n:
        tag = raw[i]
        i += 1

        if tag == TAG_END_ATTRS:
            break
        if tag in GROUP_NAMES and tag != TAG_END_ATTRS:
            current = {"tag": tag, "name": GROUP_NAMES[tag], "attrs": []}
            groups.append(current)
            last_attr = None
            stack = []
            continue

        # 读取 name-length + name
        if i + 2 > n:
            break
        name_len = struct.unpack(">H", raw[i : i + 2])[0]
        i += 2
        name = ""
        if name_len:
            name = _decode_text(raw[i : i + name_len])
            i += name_len

        # 读取 value-length + value
        if i + 2 > n:
            break
        value_len = struct.unpack(">H", raw[i : i + 2])[0]
        i += 2
        value_raw = raw[i : i + value_len]
        i += value_len

        if tag == T_BEG_COLLECTION:
            # 值内容是第一个成员的名字
            first_member = _decode_text(value_raw)
            coll: Dict[str, Any] = {}
            if name or last_attr is None:
                last_attr = {"name": name, "tag": tag, "values": []}
                if current is not None:
                    current["attrs"].append(last_attr)
            stack.append([last_attr, coll, first_member])
            continue

        if tag == T_END_COLLECTION:
            if stack:
                attr, coll, _member = stack.pop()
                attr["values"].append(coll)
            continue

        if stack:
            attr, coll, member = stack[-1]
            key = name or member
            stack[-1][2] = key
            value = _decode_scalar(tag, value_raw)
            if key in coll:
                if not isinstance(coll[key], list):
                    coll[key] = [coll[key]]
                coll[key].append(value)
            else:
                coll[key] = value
            continue

        value = _decode_scalar(tag, value_raw)

        if current is None:
            continue

        if name:
            # 同名重复（本机 HP 会重复 name）→ 合并为一个多值属性
            if last_attr is not None and last_attr["name"] == name and last_attr["tag"] == tag:
                last_attr["values"].append(value)
            else:
                last_attr = {"name": name, "tag": tag, "values": [value]}
                current["attrs"].append(last_attr)
        else:
            if last_attr is not None:
                last_attr["values"].append(value)

    return IppResponse((major, minor), status, request_id, groups, raw)


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


def parse_printer_uri(uri: str) -> Tuple[str, str, int, str]:
    """解析 ``ipp://host:port/path`` / ``ipps://host:port/path``。

    返回 ``(scheme, host, port, path)``。
    """
    if "://" not in uri:
        uri = "ipp://" + uri
    parts = urlsplit(uri)
    scheme = (parts.scheme or "ipp").lower()
    if scheme not in ("ipp", "ipps"):
        raise ValueError("不支持的打印机 URI 协议: %s" % scheme)
    host = parts.hostname or ""
    if not host:
        raise ValueError("打印机 URI 缺少主机地址: %s" % uri)
    default_port = 443 if scheme == "ipps" else 631
    port = parts.port or default_port
    path = parts.path or DEFAULT_IPP_PATH
    return scheme, host, port, path


class IppClient:
    """单个 IPP 端点的低层客户端。"""

    def __init__(self, uri: str, timeout: float = 30.0, user: str = "hp-offline"):
        self.uri = uri
        self.scheme, self.host, self.port, self.path = parse_printer_uri(uri)
        self.timeout = timeout
        self.user = user
        self._request_id = 0

    # -- 传输 -------------------------------------------------------------
    def _next_request_id(self) -> int:
        self._request_id = (self._request_id % 0x7FFFFFFE) + 1
        return self._request_id

    def _connect(self):
        if self.scheme == "ipps":
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.minimum_version = ssl.TLSVersion.TLSv1
            return http.client.HTTPSConnection(
                self.host, self.port, timeout=self.timeout, context=ctx
            )
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def raw_request(self, body: bytes, content_type: str = "application/ipp") -> bytes:
        """发送已编码的 IPP 请求体，返回原始响应字节。"""
        conn = self._connect()
        try:
            conn.request(
                "POST",
                self.path,
                body=body,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(len(body)),
                    "Accept": "application/ipp",
                },
            )
            resp = conn.getresponse()
            data = resp.read()
            if resp.status != 200:
                raise HpError(
                    "打印机拒绝了 IPP 请求（HTTP %d）" % resp.status,
                    detail=data[:200].decode("utf-8", "replace"),
                    code="ipp_http_error",
                )
            return data
        except (socket.timeout, TimeoutError) as exc:
            raise PrinterOffline("连接打印机超时（%s:%d）" % (self.host, self.port), str(exc))
        except (ConnectionError, OSError) as exc:
            raise PrinterOffline(
                "无法连接打印机（%s:%d）" % (self.host, self.port), "%s: %s" % (type(exc).__name__, exc)
            )
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover - 关闭失败无意义
                pass

    def _base_attrs(self) -> List[Tuple[int, str, Sequence[Any]]]:
        return [
            (T_CHARSET, "attributes-charset", ["utf-8"]),
            (T_NATURAL_LANGUAGE, "attributes-natural-language", ["zh-cn"]),
            (T_URI, "printer-uri", [self.uri]),
        ]

    def _call(
        self,
        operation: int,
        attrs: Sequence[Tuple[int, str, Sequence[Any]]],
        job_attrs: Optional[Sequence[Tuple[int, str, Sequence[Any]]]] = None,
        data: bytes = b"",
    ) -> IppResponse:
        body = build_request(operation, attrs, job_attrs, data, self._next_request_id())
        raw = self.raw_request(body)
        response = parse_response(raw)
        if not response.ok:
            detail = ""
            unsupported = response.group(TAG_UNSUPPORTED_ATTRS)
            if unsupported:
                names = [a["name"] for a in unsupported["attrs"]]
                detail = "不支持的属性: " + ", ".join(names)
            log.warning(
                "IPP %s 失败: 0x%04X %s %s",
                OPERATION_NAMES.get(operation, hex(operation)),
                response.status,
                response.status_text,
                detail,
            )
        return response

    # -- 操作 -------------------------------------------------------------
    def get_printer_attributes(self, requested: Optional[Sequence[str]] = None) -> IppResponse:
        attrs = self._base_attrs()
        if requested:
            attrs.append((T_KEYWORD, "requested-attributes", list(requested)))
        return self._call(OP_GET_PRINTER_ATTRIBUTES, attrs)

    def validate_job(
        self,
        job_attrs: Optional[Sequence[Tuple[int, str, Sequence[Any]]]] = None,
        document_format: str = "image/jpeg",
    ) -> IppResponse:
        attrs = self._base_attrs() + [
            (T_NAME, "requesting-user-name", [self.user]),
            (T_MIME_TYPE, "document-format", [document_format]),
        ]
        return self._call(OP_VALIDATE_JOB, attrs, job_attrs)

    def print_job(
        self,
        data: bytes,
        job_name: str = "HP Offline 文档",
        document_format: str = "image/jpeg",
        job_attrs: Optional[Sequence[Tuple[int, str, Sequence[Any]]]] = None,
        timeout: Optional[float] = None,
    ) -> IppResponse:
        old_timeout = self.timeout
        if timeout is not None:
            self.timeout = timeout
        try:
            attrs = self._base_attrs() + [
                (T_NAME, "requesting-user-name", [self.user]),
                (T_NAME, "job-name", [job_name]),
                (T_MIME_TYPE, "document-format", [document_format]),
                (T_BOOLEAN, "last-document", [True]),
            ]
            return self._call(OP_PRINT_JOB, attrs, job_attrs, data)
        finally:
            self.timeout = old_timeout

    def create_job(
        self,
        job_name: str = "HP Offline 文档",
        job_attrs: Optional[Sequence[Tuple[int, str, Sequence[Any]]]] = None,
    ) -> IppResponse:
        attrs = self._base_attrs() + [
            (T_NAME, "requesting-user-name", [self.user]),
            (T_NAME, "job-name", [job_name]),
        ]
        return self._call(OP_CREATE_JOB, attrs, job_attrs)

    def send_document(
        self,
        job_id: int,
        data: bytes,
        document_format: str = "image/jpeg",
        last_document: bool = True,
        timeout: Optional[float] = None,
    ) -> IppResponse:
        old_timeout = self.timeout
        if timeout is not None:
            self.timeout = timeout
        try:
            attrs = self._base_attrs() + [
                (T_NAME, "requesting-user-name", [self.user]),
                (T_INTEGER, "job-id", [int(job_id)]),
                (T_MIME_TYPE, "document-format", [document_format]),
                (T_BOOLEAN, "last-document", [bool(last_document)]),
            ]
            return self._call(OP_SEND_DOCUMENT, attrs, None, data)
        finally:
            self.timeout = old_timeout

    def get_job_attributes(
        self, job_id: int, requested: Optional[Sequence[str]] = None
    ) -> IppResponse:
        attrs = self._base_attrs() + [
            (T_NAME, "requesting-user-name", [self.user]),
            (T_INTEGER, "job-id", [int(job_id)]),
        ]
        if requested:
            attrs.append((T_KEYWORD, "requested-attributes", list(requested)))
        return self._call(OP_GET_JOB_ATTRIBUTES, attrs)

    def cancel_job(self, job_id: int) -> IppResponse:
        attrs = self._base_attrs() + [
            (T_NAME, "requesting-user-name", [self.user]),
            (T_INTEGER, "job-id", [int(job_id)]),
        ]
        return self._call(OP_CANCEL_JOB, attrs)

    def __repr__(self) -> str:  # pragma: no cover
        return "<IppClient %s>" % self.uri


# ---------------------------------------------------------------------------
# 友好封装
# ---------------------------------------------------------------------------


def _supply_label(description: str, colorant: str) -> str:
    text = (description or "").strip()
    if text:
        return text
    colorant = (colorant or "").lower()
    if "black" in colorant:
        return "黑色墨水"
    if colorant:
        return "三色墨水"
    return "耗材"


def _supply_key(colorant: str, description: str) -> str:
    colorant = (colorant or "").lower()
    if "black" in colorant:
        return "black"
    if "multi" in colorant or "tri" in colorant or "cyan" in colorant:
        return "color"
    if "黑色" in (description or ""):
        return "black"
    return (colorant or "supply").replace(" ", "_")


class IppPrinter:
    """面向业务的 IPP 打印机封装。

    自动在 ``ipp://host:631/ipp/print`` 与 ``ipps://host:443/ipp/print`` 间回退。
    """

    def __init__(self, host: str, path: str = DEFAULT_IPP_PATH, timeout: float = 30.0,
                 prefer_tls: bool = False):
        self.host = host
        self.path = path
        self.timeout = timeout
        self.prefer_tls = prefer_tls
        self._client: Optional[IppClient] = None
        self._attrs_cache: Optional[Dict[str, Any]] = None

    # -- 端点选择 ---------------------------------------------------------
    @property
    def client(self) -> IppClient:
        if self._client is not None:
            return self._client
        schemes = ["ipps", "ipp"] if self.prefer_tls else ["ipp", "ipps"]
        last_error: Optional[Exception] = None
        for scheme in schemes:
            port = 443 if scheme == "ipps" else 631
            uri = "%s://%s:%d%s" % (scheme, self.host, port, self.path)
            candidate = IppClient(uri, timeout=self.timeout)
            try:
                candidate.get_printer_attributes(["printer-name"])
            except HpError as exc:
                last_error = exc
                log.debug("IPP 端点不可用 %s: %s", uri, exc)
                continue
            self._client = candidate
            return candidate
        raise last_error or PrinterOffline("找不到可用的 IPP 端点（%s）" % self.host)

    @property
    def uri(self) -> str:
        return self.client.uri

    # -- 能力 -------------------------------------------------------------
    def get_attributes(self, refresh: bool = False) -> Dict[str, Any]:
        if self._attrs_cache is not None and not refresh:
            return self._attrs_cache
        response = self.client.get_printer_attributes()
        if not response.ok:
            raise HpError(
                "读取打印机能力失败：%s" % response.status_text,
                detail="0x%04X" % response.status,
                code="ipp_error",
            )
        attrs = response.attributes()
        self._attrs_cache = attrs
        return attrs

    def capabilities(self) -> Dict[str, Any]:
        """把 IPP 属性映射成 API 契约中的 capabilities 结构。"""
        attrs = self.get_attributes()
        media = attrs.get("media-supported") or []
        if isinstance(media, str):
            media = [media]
        sides = attrs.get("sides-supported") or []
        if isinstance(sides, str):
            sides = [sides]
        color_modes = attrs.get("print-color-mode-supported") or []
        if isinstance(color_modes, str):
            color_modes = [color_modes]
        formats = attrs.get("document-format-supported") or []
        if isinstance(formats, str):
            formats = [formats]

        # 媒体名归一：本机返回 na_letter_8.5x11in，前端契约示例为 na_letter_8.5x11in
        normalized_media: List[str] = []
        for item in media:
            name = item.split("_")[0] + "_" + item.split("_", 1)[1] if "_" in item else item
            if name not in normalized_media:
                normalized_media.append(name)

        return {
            "color": bool(attrs.get("color-supported", True)),
            "duplex": any("two-sided" in str(s) for s in sides),
            "scan": False,  # 由 service 结合 eSCL 覆盖
            "adf": False,
            "max_scan_dpi": 0,
            "scan_color_modes": [],
            "scan_formats": [],
            "media": normalized_media,
            "document_formats": formats,
            "color_modes": color_modes,
            "sides": sides,
            "resolution_default": attrs.get("printer-resolution-default"),
            "media_default": attrs.get("media-default"),
        }

    def supplies(self) -> List[Dict[str, Any]]:
        """从 IPP marker-* 属性推导耗材（LEDM 不可用时的兜底）。"""
        attrs = self.get_attributes()
        names = attrs.get("marker-names") or []
        colors = attrs.get("marker-colors") or []
        levels = attrs.get("marker-levels") or []
        descriptions = attrs.get("printer-supply-description") or []
        colorants: List[str] = []
        for raw in attrs.get("printer-supply") or []:
            colorant = ""
            if isinstance(raw, str):
                for part in raw.split(";"):
                    if part.startswith("colorantname="):
                        colorant = part.split("=", 1)[1]
            elif isinstance(raw, dict):
                colorant = str(raw.get("colorantname", ""))
            colorants.append(colorant)

        def as_list(value: Any) -> List[Any]:
            if value is None:
                return []
            return value if isinstance(value, list) else [value]

        names = as_list(names)
        colors = as_list(colors)
        levels = as_list(levels)
        descriptions = as_list(descriptions)

        result: List[Dict[str, Any]] = []
        count = max(len(names), len(levels))
        for idx in range(count):
            colorant = colorants[idx] if idx < len(colorants) else ""
            desc = descriptions[idx] if idx < len(descriptions) else ""
            label = _supply_label(desc, colorant)
            key = _supply_key(colorant, desc)
            level_raw = levels[idx] if idx < len(levels) else -1
            try:
                level_int = int(level_raw)
            except (TypeError, ValueError):
                level_int = -1
            # -1 / -2 / 0 均视为「设备不提供百分比」
            if level_int in (-1, -2, 0):
                level_int = -1
            color = "#000000" if key == "black" else "#00A0E9"
            if idx < len(colors) and isinstance(colors[idx], str) and colors[idx].startswith("#"):
                hex_part = colors[idx]
                if "#" in hex_part[1:]:
                    hex_part = hex_part.split("#")[1]
                color = "#" + hex_part.strip("#")[:6]
            state = "ok"
            if level_int >= 0:
                if level_int <= 5:
                    state = "empty"
                elif level_int <= 15:
                    state = "low"
            result.append(
                {
                    "key": key,
                    "label": label,
                    "color": color,
                    "level": level_int,
                    "state": state,
                    "kind": "ink",
                }
            )
        return result

    # -- 打印 -------------------------------------------------------------
    def build_job_attributes(
        self,
        copies: int = 1,
        color: str = "auto",
        quality: str = "normal",
        media: Optional[str] = None,
        content_optimize: str = "auto",
        scale: str = "fit",
        sides: str = "one-sided",
    ) -> List[Tuple[int, str, Sequence[Any]]]:
        """构造 job 属性组。"""
        mode = (color or "auto").lower()
        if mode == "monochrome":
            color_mode = "monochrome"
        elif mode == "color":
            color_mode = "color"
        elif (content_optimize or "").lower() == "photo":
            # 照片打印时 auto 会被打印机按通用模式处理，容易压暗；照片直接用 color
            color_mode = "color"
        else:
            color_mode = "auto"
        attrs: List[Tuple[int, str, Sequence[Any]]] = [
            (T_INTEGER, "copies", [max(1, int(copies))]),
            (T_KEYWORD, "print-color-mode", [color_mode]),
            (T_ENUM, "print-quality", [QUALITY_ENUM.get(quality, 4)]),
        ]
        if media:
            attrs.append((T_KEYWORD, "media", [media]))
        if content_optimize:
            attrs.append((T_KEYWORD, "print-content-optimize", [content_optimize]))
        scaling_map = {"fit": "fit", "fill": "fill", "actual": "none"}
        attrs.append((T_KEYWORD, "print-scaling", [scaling_map.get((scale or "fit").lower(), "fit")]))
        if sides:
            attrs.append((T_KEYWORD, "sides", [sides]))
        return attrs

    def print_document(
        self,
        data: bytes,
        job_name: str,
        copies: int = 1,
        color: str = "auto",
        quality: str = "normal",
        media: Optional[str] = None,
        content_optimize: str = "auto",
        scale: str = "fit",
        sides: str = "one-sided",
        document_format: str = "image/jpeg",
        timeout: float = 120.0,
    ) -> int:
        """Print-Job，返回 job-id。"""
        job_attrs = self.build_job_attributes(copies, color, quality, media, content_optimize, scale, sides)
        response = self.client.print_job(
            data,
            job_name=job_name,
            document_format=document_format,
            job_attrs=job_attrs,
            timeout=timeout,
        )
        if not response.ok:
            raise HpError(
                "打印机拒绝了打印任务：%s" % response.status_text,
                detail=response.get("job-state-reasons") or "",
                code="print_rejected",
            )
        job_id = response.get("job-id")
        if job_id is None:
            raise ProtocolError("打印响应缺少 job-id")
        return int(job_id)

    def create_print_job(
        self,
        job_name: str,
        copies: int = 1,
        color: str = "auto",
        quality: str = "normal",
        media: Optional[str] = None,
    ) -> int:
        job_attrs = self.build_job_attributes(copies, color, quality, media, content_optimize, scale, sides)
        response = self.client.create_job(job_name=job_name, job_attrs=job_attrs)
        if not response.ok:
            raise HpError(
                "无法创建打印任务：%s" % response.status_text,
                detail=response.get("job-state-reasons") or "",
                code="create_job_failed",
            )
        job_id = response.get("job-id")
        if job_id is None:
            raise ProtocolError("Create-Job 响应缺少 job-id")
        return int(job_id)

    def send_page(
        self,
        job_id: int,
        data: bytes,
        last: bool,
        document_format: str = "image/jpeg",
        timeout: float = 120.0,
    ) -> None:
        response = self.client.send_document(
            job_id, data, document_format=document_format, last_document=last, timeout=timeout
        )
        if not response.ok:
            raise HpError(
                "发送页面失败：%s" % response.status_text,
                detail=response.get("job-state-reasons") or "",
                code="send_document_failed",
            )

    def job_state(self, job_id: int) -> Dict[str, Any]:
        response = self.client.get_job_attributes(job_id)
        if not response.ok:
            return {"job_id": job_id, "state": None, "state_name": "unknown", "reasons": []}
        state = response.get("job-state")
        reasons = response.get_list("job-state-reasons")
        return {
            "job_id": job_id,
            "state": state,
            "state_name": JOB_STATE_NAMES.get(state, "unknown"),
            "reasons": reasons,
            "message": response.get("job-state-message") or "",
            "impressions": response.get("job-impressions-completed"),
            "k_octets": response.get("job-k-octets-processed"),
        }

    def cancel(self, job_id: int) -> bool:
        response = self.client.cancel_job(job_id)
        return response.ok

    def wait_job(
        self,
        job_id: int,
        timeout: float = 180.0,
        poll: float = 1.5,
        on_progress=None,
        cancel_event=None,
        finish_on_idle: bool = True,
    ) -> Dict[str, Any]:
        """轮询直到 job 进入终态（7 canceled / 8 aborted / 9 completed）。

        本机（Ink Tank Wireless 410）实测缺陷：纸张早已输出，但打印机把 job-state
        一直挂在 5(processing) 长达 1~2 分钟才置 9，导致 UI 白等。
        因此额外用 printer-state 兜底：只要设备回到 idle(3) 且已过宽限期，
        就认为作业已完成。
        """
        deadline = time.time() + timeout
        started = time.time()
        last: Dict[str, Any] = {}
        idle_hits = 0
        while time.time() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                try:
                    self.cancel(job_id)
                except HpError as exc:
                    log.warning("取消 IPP 任务失败: %s", exc)
                return {"job_id": job_id, "state": 7, "state_name": "canceled", "reasons": []}
            try:
                last = self.job_state(job_id)
            except PrinterOffline:
                raise
            if on_progress is not None:
                on_progress(last)
            if last.get("state") in (7, 8, 9):
                return last
            if finish_on_idle and (time.time() - started) > 4.0:
                try:
                    pstate = self.get_attributes().get("printer-state")
                except HpError:
                    pstate = None
                if pstate == 3:  # idle
                    idle_hits += 1
                    if idle_hits >= 2:  # 连续两次 idle 才判定，避免页间空档误判
                        done = dict(last)
                        done["state"] = 9
                        done["state_name"] = "completed"
                        done["finished_by_idle"] = True
                        return done
                else:
                    idle_hits = 0
            time.sleep(poll)
        last["timed_out"] = True
        return last


def probe_ipp(host: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """轻量探测：主机是否是 IPP 打印机。失败返回 None。"""
    printer = IppPrinter(host, timeout=timeout)
    try:
        attrs = printer.get_attributes()
    except HpError as exc:
        log.debug("IPP 探测失败 %s: %s", host, exc)
        return None
    return attrs
