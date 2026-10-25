"""局域网打印机发现：四种策略并行，结果按 UUID / 主机去重。

    1. WS-Discovery（UDP 组播 239.255.255.250:3702）—— 本机实测最可靠
    2. mDNS（224.0.0.251:5353，_ipp._tcp / _uscan._tcp / _pdl-datastream._tcp）
       —— 本机实测无响应，仅作兜底，允许 0 结果
    3. SNMP v1 GET sysDescr（161，广播）—— 实测无响应，仅作兜底
    4. 子网 TCP 扫描（并发，200ms 连接超时）—— 最后兜底，实测有效

⚠️ 本机装有 Clash / Meta TUN：默认路由会把 192.168.1.x 也指向 198.18.0.1，
组播报文会被 TUN 适配器吞掉。因此**每一个组播 socket 都必须**：
    setsockopt(IPPROTO_IP, IP_MULTICAST_IF, inet_aton(源地址))
    bind((源地址, 0))
并且候选源地址要排除 198.18.0.0/15（Clash TUN）与 169.254.0.0/16（链路本地）。
"""

from __future__ import annotations

import concurrent.futures
import http.client
import ipaddress
import os
import random
import re
import socket
import struct
import threading
import time
import uuid as uuidlib
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .. import get_logger
from . import HpError, PrinterOffline
from .escl import EsclClient
from .ledm import LedmClient

log = get_logger("hp.discovery")

WSD_MULTICAST_ADDR = "239.255.255.250"
WSD_PORT = 3702
MDNS_MULTICAST_ADDR = "224.0.0.251"
MDNS_PORT = 5353
SNMP_PORT = 161

#: 视为虚拟 / 隧道 / 容器网络的网段（组播源必须排除）
_EXCLUDED_NETWORKS = (
    ipaddress.ip_network("198.18.0.0/15"),   # Clash / Meta TUN
    ipaddress.ip_network("169.254.0.0/16"),  # 链路本地
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("172.17.0.0/16"),   # docker 默认网桥
)

_SERVICE_TYPES = (
    "_ipp._tcp.local",
    "_uscan._tcp.local",
    "_pdl-datastream._tcp.local",
    "_printer._tcp.local",
)

#: 设备名里出现这些关键字才认为是打印机
_PRINTER_HINTS = ("hp", "ink", "laserjet", "officejet", "deskjet", "envy", "printer", "mfp")


# ---------------------------------------------------------------------------
# 本机地址
# ---------------------------------------------------------------------------


def local_addresses(prefer_host: Optional[str] = None) -> List[str]:
    """返回可用于局域网组播的源地址列表（已过滤虚拟网卡）。"""
    found: List[str] = []

    def _add(addr: str) -> None:
        if not addr or addr.startswith("0."):
            return
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return
        if ip.version != 4 or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return
        for net in _EXCLUDED_NETWORKS:
            if ip in net:
                return
        if addr not in found:
            found.append(addr)

    # 1) 通过目标主机探测真实出口地址（connect 不会发出任何报文）
    if prefer_host:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.3)
            sock.connect((prefer_host, 631))
            _add(sock.getsockname()[0])
        except OSError as exc:
            log.debug("探测到 %s 的源地址失败: %s", prefer_host, exc)
        finally:
            sock.close()

    # 2) 主机名解析出的地址
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            _add(info[4][0])
    except OSError as exc:
        log.debug("解析本机主机名失败: %s", exc)

    # 3) 通过 UDP connect 一个局域网地址推断（不发送数据）
    for probe in ("192.168.1.1", "192.168.0.1", "10.0.0.1"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.2)
            sock.connect((probe, 80))
            _add(sock.getsockname()[0])
        except OSError:
            pass
        finally:
            sock.close()

    # 私网优先，且 192.168 排在前面（家用网络更常见）
    def _rank(addr: str) -> Tuple[int, int]:
        if addr.startswith("192.168."):
            return (0, 0)
        if addr.startswith("10."):
            return (1, 0)
        return (2, 0)

    found.sort(key=_rank)
    return found


def subnet_hosts(addresses: Sequence[str]) -> List[str]:
    """把源地址列表展开成待扫描的主机列表（/24，排除自身与网络/广播地址）。"""
    hosts: List[str] = []
    seen: Set[str] = set()
    for addr in addresses:
        try:
            net = ipaddress.ip_network(addr + "/24", strict=False)
        except ValueError:
            continue
        for host in net.hosts():
            text = str(host)
            if text in seen or text == addr:
                continue
            seen.add(text)
            hosts.append(text)
    return hosts


# ---------------------------------------------------------------------------
# WS-Discovery
# ---------------------------------------------------------------------------

_WSD_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <soap:Header>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
    <wsa:MessageID>urn:uuid:%s</wsa:MessageID>
  </soap:Header>
  <soap:Body><wsd:Probe/></soap:Body>
</soap:Envelope>"""


def _tag_text(pattern: str, text: str) -> Optional[str]:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def parse_wsd_response(xml_text: str, sender: str) -> Optional[Dict[str, Any]]:
    """从 WS-Discovery ProbeMatches 中提取设备信息。"""
    types = " ".join(re.findall(r"<(?:[A-Za-z0-9]+:)?Types>(.*?)</", xml_text, re.DOTALL))
    if types and "PrintDeviceType" not in types and "ScanDeviceType" not in types:
        # 明确声明了类型但不是打印/扫描设备
        if "Device" in types and "Print" not in types:
            return None

    host = _tag_text(r"<(?:[A-Za-z0-9]+:)?IPv4Address>(.*?)<", xml_text) or sender
    device_id = _tag_text(r"<(?:[A-Za-z0-9]+:)?DeviceId>(.*?)<", xml_text) or ""
    model = None
    serial = None
    manufacturer = None
    if device_id:
        for part in device_id.split(";"):
            key, _, value = part.partition(":")
            key = key.strip().upper()
            value = value.strip()
            if key == "MDL":
                model = value
            elif key == "SN":
                serial = value
            elif key == "MFG":
                manufacturer = value
    if not serial:
        serial = _tag_text(r"<(?:[A-Za-z0-9]+:)?SerialNumber>(.*?)<", xml_text)
    hostname = _tag_text(r"<(?:[A-Za-z0-9]+:)?Hostname>(.*?)<", xml_text)
    mac = _tag_text(r"<(?:[A-Za-z0-9]+:)?HardwareAddress>(.*?)<", xml_text)
    uuid_value = _tag_text(r"<(?:[A-Za-z0-9]+:)?UUID>(.*?)<", xml_text)
    if not uuid_value:
        uuid_value = _tag_text(r"uuid:([0-9a-fA-F\-]{36})", xml_text)

    services = _tag_text(r"<(?:[A-Za-z0-9]+:)?Services>(.*?)<", xml_text) or ""
    return {
        "host": host,
        "model": model or hostname,
        "serial": serial,
        "uuid": (uuid_value or "").strip().lower() or None,
        "hostname": hostname,
        "mac": mac,
        "manufacturer": manufacturer,
        "scan": "RESTScan" in services or "ScanDeviceType" in types,
        "source": "wsd",
    }


def wsd_probe(addresses: Sequence[str], timeout: float = 6.0) -> List[Dict[str, Any]]:
    """向每个源地址发送 WS-Discovery Probe 并收集 ProbeMatches。"""
    if not addresses:
        return []
    message = (_WSD_TEMPLATE % uuidlib.uuid4()).encode("utf-8")
    sockets: List[socket.socket] = []
    results: List[Dict[str, Any]] = []

    for addr in addresses:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # 关键：绑定到局域网源地址，否则组播会被 Clash TUN 吞掉
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(addr))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
            sock.bind((addr, 0))
            sock.settimeout(0.4)
            sock.sendto(message, (WSD_MULTICAST_ADDR, WSD_PORT))
            sockets.append(sock)
            log.debug("WS-D Probe 已从 %s 发出", addr)
        except OSError as exc:
            log.debug("从 %s 发送 WS-D Probe 失败: %s", addr, exc)
            sock.close()

    if not sockets:
        return []

    deadline = time.time() + timeout
    seen_hosts: Set[str] = set()
    while time.time() < deadline:
        got_any = False
        for sock in sockets:
            try:
                data, sender = sock.recvfrom(16384)
            except socket.timeout:
                continue
            except OSError:
                continue
            got_any = True
            text = data.decode("utf-8", "replace")
            info = parse_wsd_response(text, sender[0])
            if not info:
                continue
            host = info.get("host") or sender[0]
            if host in seen_hosts:
                continue
            seen_hosts.add(host)
            results.append(info)
            log.info("WS-D 发现设备 %s (%s)", host, info.get("model"))
        if not got_any:
            time.sleep(0.05)

    for sock in sockets:
        try:
            sock.close()
        except OSError:
            pass
    return results


# ---------------------------------------------------------------------------
# mDNS
# ---------------------------------------------------------------------------


def _encode_dns_name(name: str) -> bytes:
    out = bytearray()
    for label in name.strip(".").split("."):
        if not label:
            continue
        raw = label.encode("utf-8")
        out.append(len(raw))
        out += raw
    out.append(0)
    return bytes(out)


def _read_dns_name(data: bytes, offset: int, depth: int = 0) -> Tuple[str, int]:
    """读取（可能压缩的）DNS 名称，返回 (名称, 新偏移)。"""
    if depth > 8:
        return "", offset
    labels: List[str] = []
    start = offset
    jumped = False
    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset += 1
            if not jumped:
                start = offset
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                return ".".join(labels), offset + 1
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                start = offset + 2
            sub, _ = _read_dns_name(data, pointer, depth + 1)
            if sub:
                labels.append(sub)
            jumped = True
            break
        offset += 1
        labels.append(data[offset : offset + length].decode("utf-8", "replace"))
        offset += length
    if not jumped:
        start = offset
    return ".".join(labels), start


def mdns_probe(addresses: Sequence[str], timeout: float = 3.0) -> List[Dict[str, Any]]:
    """发送 PTR 查询并解析响应。本机实测通常无响应，允许返回空列表。"""
    if not addresses:
        return []
    packet = bytearray(struct.pack(">HHHHHH", 0, 0, len(_SERVICE_TYPES), 0, 0, 0))
    for service in _SERVICE_TYPES:
        packet += _encode_dns_name(service)
        packet += struct.pack(">HH", 12, 1)  # PTR, IN

    sockets: List[socket.socket] = []
    for addr in addresses:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(addr))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
            sock.bind((addr, 0))
            sock.settimeout(0.4)
            sock.sendto(bytes(packet), (MDNS_MULTICAST_ADDR, MDNS_PORT))
            sockets.append(sock)
        except OSError as exc:
            log.debug("从 %s 发送 mDNS 查询失败: %s", addr, exc)
            sock.close()

    services: Dict[str, Dict[str, Any]] = {}
    addresses_by_name: Dict[str, str] = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sock in sockets:
            try:
                data, sender = sock.recvfrom(9000)
            except (socket.timeout, OSError):
                continue
            try:
                _parse_mdns_packet(data, sender[0], services, addresses_by_name)
            except Exception as exc:  # noqa: BLE001 - 单个坏包不影响整体
                log.debug("解析 mDNS 包失败: %s", exc)
    for sock in sockets:
        try:
            sock.close()
        except OSError:
            pass

    results: List[Dict[str, Any]] = []
    for name, info in services.items():
        host = info.get("host") or addresses_by_name.get(info.get("target", ""))
        if not host:
            continue
        results.append(
            {
                "host": host,
                "model": info.get("model") or info.get("ty") or name.split(".")[0],
                "serial": None,
                "uuid": None,
                "hostname": info.get("target"),
                "scan": "_uscan" in name,
                "source": "mdns",
            }
        )
    return results


def _parse_mdns_packet(
    data: bytes,
    sender: str,
    services: Dict[str, Dict[str, Any]],
    addresses_by_name: Dict[str, str],
) -> None:
    if len(data) < 12:
        return
    _tid, _flags, qdcount, ancount, _ns, _ar = struct.unpack(">HHHHHH", data[:12])
    offset = 12
    for _ in range(qdcount):
        _name, offset = _read_dns_name(data, offset)
        offset += 4
    for _ in range(ancount):
        name, offset = _read_dns_name(data, offset)
        if offset + 10 > len(data):
            return
        rtype, _rclass, _ttl, rdlength = struct.unpack(">HHIH", data[offset : offset + 10])
        offset += 10
        rdata = data[offset : offset + rdlength]
        offset += rdlength
        lower = name.lower()
        if rtype == 12 and rdata:  # PTR
            target, _ = _read_dns_name(data, offset - rdlength)
            entry = services.setdefault(target.lower(), {"name": target})
            entry["service"] = lower
            entry.setdefault("target", "")
        elif rtype == 33 and len(rdata) >= 6:  # SRV
            _prio, _weight, port = struct.unpack(">HHH", rdata[:6])
            target, _ = _read_dns_name(data, offset - rdlength + 6)
            entry = services.setdefault(lower, {"name": name})
            entry["target"] = target
            entry["port"] = port
            entry.setdefault("service", lower)
        elif rtype == 1 and len(rdata) == 4:  # A
            addresses_by_name[lower] = socket.inet_ntoa(rdata)
        elif rtype == 16 and rdata:  # TXT
            entry = services.setdefault(lower, {"name": name})
            for item in rdata.split(b"\x00"):
                text = item.decode("utf-8", "replace")
                if text.startswith("ty="):
                    entry["model"] = text[3:]
                elif text.startswith("usb_MFG=") or text.startswith("usb_MDL="):
                    entry["model"] = text.split("=", 1)[1]


# ---------------------------------------------------------------------------
# SNMP
# ---------------------------------------------------------------------------


def _ber_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    out = bytearray()
    while length:
        out.insert(0, length & 0xFF)
        length >>= 8
    return bytes([0x80 | len(out)]) + bytes(out)


def _ber_tlv(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + _ber_length(len(payload)) + payload


def _ber_int(value: int) -> bytes:
    if value == 0:
        return b"\x00"
    if value > 0:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        if raw[0] & 0x80:
            raw = b"\x00" + raw
        return raw
    return (-value).to_bytes(4, "big")


def _ber_oid(dotted: str) -> bytes:
    parts = [int(p) for p in dotted.strip(".").split(".")]
    out = bytearray([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        chunk = bytearray([part & 0x7F])
        part >>= 7
        while part:
            chunk.insert(0, (part & 0x7F) | 0x80)
            part >>= 7
        out += chunk
    return bytes(out)


def _snmp_get_packet(oids: Sequence[str], community: str = "public") -> bytes:
    varbinds = b"".join(
        _ber_tlv(0x30, _ber_tlv(0x06, _ber_oid(oid)) + _ber_tlv(0x05, b"")) for oid in oids
    )
    pdu = _ber_tlv(
        0xA0,
        _ber_tlv(0x02, _ber_int(random.randint(1, 0x7FFFFFFF)))
        + _ber_tlv(0x02, _ber_int(0))
        + _ber_tlv(0x02, _ber_int(0))
        + _ber_tlv(0x30, varbinds),
    )
    return _ber_tlv(0x30, _ber_tlv(0x02, _ber_int(1)) + _ber_tlv(0x04, community.encode()) + pdu)


def _ber_walk(data: bytes, offset: int = 0) -> List[Tuple[int, Any]]:
    """把 BER 结构展平成 [(tag, value_or_children)]。"""
    nodes: List[Tuple[int, Any]] = []
    while offset < len(data):
        tag = data[offset]
        offset += 1
        if offset >= len(data):
            break
        length = data[offset]
        offset += 1
        if length & 0x80:
            count = length & 0x7F
            length = int.from_bytes(data[offset : offset + count], "big")
            offset += count
        payload = data[offset : offset + length]
        offset += length
        if tag in (0x30, 0xA0, 0xA1, 0xA2):  # 构造类型
            nodes.append((tag, _ber_walk(payload)))
        elif tag == 0x04:
            nodes.append((tag, payload))
        elif tag == 0x02:
            nodes.append((tag, int.from_bytes(payload, "big", signed=True)))
        else:
            nodes.append((tag, payload))
    return nodes


def snmp_probe(addresses: Sequence[str], timeout: float = 2.5) -> List[Dict[str, Any]]:
    """SNMP v1 GET sysDescr / sysName，向各子网广播地址发送。"""
    targets: Set[str] = set()
    for addr in addresses:
        try:
            net = ipaddress.ip_network(addr + "/24", strict=False)
        except ValueError:
            continue
        targets.add(str(net.broadcast_address))
    targets.add("255.255.255.255")

    packet = _snmp_get_packet(["1.3.6.1.2.1.1.1.0", "1.3.6.1.2.1.1.5.0"])
    results: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if addresses:
            sock.bind((addresses[0], 0))
        sock.settimeout(0.4)
        for target in targets:
            try:
                sock.sendto(packet, (target, SNMP_PORT))
            except OSError as exc:
                log.debug("SNMP 广播到 %s 失败: %s", target, exc)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, sender = sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            host = sender[0]
            if host in seen:
                continue
            seen.add(host)
            text = data.decode("latin-1", "replace")
            if "HP" not in text and "hp" not in text:
                continue
            serial = _tag_text(r"SN:([^,]+)", text)
            model = _tag_text(r"MDL:([^,;]+)", text)
            results.append(
                {
                    "host": host,
                    "model": (model or "HP 打印机").strip(),
                    "serial": serial.strip() if serial else None,
                    "uuid": None,
                    "scan": False,
                    "source": "snmp",
                }
            )
    finally:
        sock.close()
    return results


# ---------------------------------------------------------------------------
# 子网扫描
# ---------------------------------------------------------------------------


def _http_probe(host: str, path: str, timeout: float, port: int = 80) -> Optional[bytes]:
    """极短超时的 HTTP GET；任何失败返回 None（不抛异常）。"""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path, headers={"Connection": "close"})
        response = conn.getresponse()
        if response.status != 200:
            return None
        return response.read()
    except (OSError, http.client.HTTPException):
        return None
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            pass


def _is_hp_host(host: str, timeout: float = 0.7) -> bool:
    """快速判定：主机是否响应 HP 的 LEDM 或 eSCL 资源。

    ⚠️ 本机 Clash TUN 会接受**所有** TCP 连接（connect_ex 恒为 0），因此
    端口探测完全不可信，必须用真实 HTTP 响应判定。
    """
    data = _http_probe(host, "/DevMgmt/ProductStatusDyn.xml", timeout)
    if data and b"ProductStatusDyn" in data:
        return True
    data = _http_probe(host, "/eSCL/ScannerStatus", timeout)
    if data and (b"ScannerStatus" in data or b"scan:" in data):
        return True
    return False


def probe_host(host: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """探测单个主机是否是打印机；是则返回设备信息（LEDM → eSCL → IPP 依次尝试）。"""
    config: Dict[str, Any] = {}
    try:
        config = LedmClient(host, timeout=timeout).product_config()
    except HpError as exc:
        log.debug("LEDM 探测 %s 失败: %s", host, exc)

    scan = False
    try:
        scan = EsclClient(host, timeout=timeout).is_scanner(timeout=min(2.0, timeout))
    except HpError as exc:
        log.debug("eSCL 探测 %s 失败: %s", host, exc)

    if not config and not scan:
        # 最后尝试 IPP（非 HP 的 IPP 打印机也能被识别）
        try:
            from .ipp import IppPrinter

            attrs = IppPrinter(host, timeout=timeout).get_attributes()
            model = attrs.get("printer-make-and-model") or attrs.get("printer-info")
            if not model:
                return None
            config = {"model": model, "name": attrs.get("printer-info")}
        except HpError as exc:
            log.debug("IPP 探测 %s 失败: %s", host, exc)
            return None

    return {
        "host": host,
        "model": config.get("model"),
        "serial": config.get("serial"),
        "uuid": (config.get("uuid") or "").lower() or None,
        "hostname": config.get("hostname"),
        "name": config.get("name"),
        "firmware": config.get("firmware"),
        "scan": scan,
        "source": "scan",
    }


def subnet_scan(
    addresses: Sequence[str],
    probe_timeout: float = 0.7,
    max_workers: int = 200,
    overall_timeout: float = 25.0,
) -> List[Dict[str, Any]]:
    """并发扫描各源地址所在的 /24，返回打印机列表。

    注意：不做 TCP 端口预筛（Clash TUN 会让所有 connect 都成功），
    直接对每个地址发 HTTP 探测，只有真正返回 LEDM/eSCL 内容的主机才算命中。
    """
    hosts = subnet_hosts(addresses)
    if not hosts:
        return []
    log.info("子网扫描 %d 个地址（并发 %d）", len(hosts), max_workers)
    started = time.time()
    candidates: List[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_is_hp_host, host, probe_timeout): host for host in hosts}
        try:
            for future in concurrent.futures.as_completed(futures, timeout=overall_timeout):
                try:
                    if future.result():
                        candidates.append(futures[future])
                except Exception as exc:  # noqa: BLE001
                    log.debug("HTTP 探测异常: %s", exc)
        except concurrent.futures.TimeoutError:
            log.warning("子网扫描超时（%.0fs），已命中 %d 台", overall_timeout, len(candidates))

    log.info("子网扫描完成，命中 %d 台（%.1fs）", len(candidates), time.time() - started)
    if not candidates:
        return []

    results: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(candidates))) as pool:
        futures = [pool.submit(probe_host, host, 2.5) for host in candidates]
        for future in concurrent.futures.as_completed(futures):
            try:
                info = future.result()
            except Exception as exc:  # noqa: BLE001
                log.debug("主机探测异常: %s", exc)
                continue
            if info:
                results.append(info)
    return results


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def _merge(found: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 UUID / host 去重合并，信息越全优先级越高。"""
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for item in found:
        if not item or not item.get("host"):
            continue
        key = (item.get("uuid") or "").lower() or item["host"]
        if key not in merged:
            merged[key] = dict(item)
            order.append(key)
            continue
        current = merged[key]
        for field in ("model", "serial", "uuid", "hostname", "firmware", "name"):
            if not current.get(field) and item.get(field):
                current[field] = item[field]
        if item.get("scan"):
            current["scan"] = True
        sources = {s.strip() for s in str(current.get("source", "")).split("+") if s.strip()}
        sources.add(item.get("source", "unknown"))
        current["source"] = "+".join(sorted(sources))
    return [merged[key] for key in order]


def discover(
    prefer_host: Optional[str] = None,
    wsd_timeout: float = 6.0,
    mdns_timeout: float = 3.0,
    snmp_timeout: float = 2.0,
    do_subnet: bool = True,
    addresses: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """四路发现并行执行，合并去重后返回。"""
    started = time.time()
    sources = list(addresses) if addresses else local_addresses(prefer_host)
    log.info("发现开始，本机局域网地址: %s", ", ".join(sources) or "(无)")

    buckets: Dict[str, List[Dict[str, Any]]] = {}

    def _run(name: str, func, *args) -> None:
        try:
            buckets[name] = func(*args) or []
            log.info("%s 发现 %d 台设备（%.1fs）", name, len(buckets[name]), time.time() - started)
        except Exception as exc:  # noqa: BLE001 - 单路失败不影响整体
            log.warning("%s 发现失败: %s", name, exc)
            buckets[name] = []

    threads = [
        threading.Thread(target=_run, args=("wsd", wsd_probe, sources, wsd_timeout), daemon=True),
        threading.Thread(target=_run, args=("mdns", mdns_probe, sources, mdns_timeout), daemon=True),
        threading.Thread(target=_run, args=("snmp", snmp_probe, sources, snmp_timeout), daemon=True),
    ]
    if do_subnet:
        threads.append(
            threading.Thread(target=_run, args=("scan", subnet_scan, sources), daemon=True)
        )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=wsd_timeout + 14.0)

    collected: List[Dict[str, Any]] = []
    for name in ("wsd", "mdns", "snmp", "scan"):
        collected.extend(buckets.get(name, []))

    merged = _merge(collected)
    # 过滤明显不是打印机的条目
    filtered: List[Dict[str, Any]] = []
    for item in merged:
        text = " ".join(
            str(item.get(field) or "") for field in ("model", "hostname", "name", "manufacturer")
        ).lower()
        if item.get("source", "").startswith("scan") or item.get("scan"):
            filtered.append(item)
        elif any(hint in text for hint in _PRINTER_HINTS) or item.get("model"):
            filtered.append(item)
    log.info("发现结束：%d 台设备（耗时 %.1fs）", len(filtered), time.time() - started)
    return filtered


def resolve(
    target_uuid: Optional[str] = None,
    hostname: Optional[str] = None,
    previous_host: Optional[str] = None,
    timeout: float = 8.0,
) -> Optional[str]:
    """打印机换了 IP 时，用 UUID / 主机名重新定位。返回新的 IP。"""
    wanted_uuid = (target_uuid or "").lower()
    wanted_host = (hostname or "").lower().rstrip(".")
    log.info("尝试重新定位打印机 uuid=%s hostname=%s", wanted_uuid or "-", wanted_host or "-")

    found = discover(prefer_host=previous_host, wsd_timeout=timeout, mdns_timeout=2.0,
                     snmp_timeout=1.5, do_subnet=True)
    for item in found:
        item_uuid = (item.get("uuid") or "").lower()
        item_host = (item.get("hostname") or "").lower().rstrip(".")
        if wanted_uuid and item_uuid and item_uuid == wanted_uuid:
            log.info("按 UUID 重新定位到 %s", item["host"])
            return item["host"]
        if wanted_host and item_host and item_host == wanted_host:
            log.info("按主机名重新定位到 %s", item["host"])
            return item["host"]
    return None
