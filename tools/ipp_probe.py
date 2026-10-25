"""Minimal IPP client (stdlib only) - probe an IPP printer.

Usage:
    python ipp_probe.py 192.168.1.100
"""
import sys
import socket
import struct
import urllib.request
import xml.etree.ElementTree as ET

# ---- IPP tag values -------------------------------------------------------
OP_GET_PRINTER_ATTRIBUTES = 0x000B
OP_PRINT_JOB = 0x0002
OP_GET_JOBS = 0x000A
OP_GET_JOB_ATTRIBUTES = 0x0009

TAG_OPERATION_ATTRS = 0x01
TAG_JOB_ATTRS = 0x02
TAG_END_ATTRS = 0x03

# value tags
T_CHARSET = 0x47
T_NATURAL_LANGUAGE = 0x48
T_KEYWORD = 0x44
T_URI = 0x45
T_NAME = 0x42
T_TEXT = 0x41
T_INTEGER = 0x21
T_BOOLEAN = 0x22
T_ENUM = 0x23
T_RESOLUTION = 0x32
T_RANGE = 0x33
T_BEG_COLLECTION = 0x34
T_END_COLLECTION = 0x37
T_MIMETYPE = 0x49

STATUS = {
    0x0000: "successful-ok",
    0x0001: "successful-ok-ignored-or-substituted-attributes",
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


def _enc_value(tag, value):
    """Encode a single attribute VALUE (length + payload, NO tag byte).

    The value-tag is written once by _enc_attr() before the attribute name.
    """
    if isinstance(value, str):
        raw = value.encode("utf-8")
    elif isinstance(value, int):
        if tag == T_INTEGER or tag == T_ENUM:
            raw = struct.pack(">i", value)
        elif tag == T_BOOLEAN:
            raw = bytes([1 if value else 0])
        else:
            raw = struct.pack(">i", value)
    elif isinstance(value, tuple) and tag == T_RESOLUTION:
        raw = struct.pack(">iib", value[0], value[1], value[2])
    elif isinstance(value, tuple) and tag == T_RANGE:
        raw = struct.pack(">ii", value[0], value[1])
    else:
        raw = bytes(value)
    return struct.pack(">H", len(raw)) + raw


def _enc_attr(tag, name, values):
    """Encode one attribute.

    Layout per RFC 8010: value-tag | name-length | name | value-length | value
    Additional values repeat the value-tag with a zero-length name.
    """
    out = b""
    name_b = name.encode("utf-8")
    for i, v in enumerate(values):
        out += struct.pack(">B", tag)
        if i == 0:
            out += struct.pack(">H", len(name_b)) + name_b
        else:
            out += struct.pack(">H", 0)
        out += _enc_value(tag, v)
    return out


def build_request(operation, attributes, job_attributes=None, data=b""):
    """attributes: list of (tag, name, [values])"""
    body = struct.pack(">BBHI", 2, 0, operation, 1)
    body += bytes([TAG_OPERATION_ATTRS])
    for tag, name, values in attributes:
        body += _enc_attr(tag, name, values)
    if job_attributes:
        body += bytes([TAG_JOB_ATTRS])
        for tag, name, values in job_attributes:
            body += _enc_attr(tag, name, values)
    body += bytes([TAG_END_ATTRS])
    return body + data


def parse_response(raw):
    version = raw[0:2]
    status = struct.unpack(">H", raw[2:4])[0]
    req_id = struct.unpack(">I", raw[4:8])[0]
    i = 8
    groups = []
    cur = None
    name = None
    tag = None
    while i < len(raw):
        t = raw[i]
        i += 1
        if t in (TAG_OPERATION_ATTRS, TAG_JOB_ATTRS, 0x04, 0x05):
            cur = {"tag": t, "attrs": []}
            groups.append(cur)
            name = None
            continue
        if t == TAG_END_ATTRS:
            break
        if t <= 0x0F:
            continue
        # value tag
        if i + 2 > len(raw):
            break
        nlen = struct.unpack(">H", raw[i:i + 2])[0]
        i += 2
        if nlen:
            name = raw[i:i + nlen].decode("utf-8", "replace")
            i += nlen
        if i + 2 > len(raw):
            break
        vlen = struct.unpack(">H", raw[i:i + 2])[0]
        i += 2
        val = raw[i:i + vlen]
        i += vlen
        decoded = _decode_value(t, val)
        if cur is None:
            continue
        # find existing attribute with this name in current group
        if name:
            cur["attrs"].append({"name": name, "tag": t, "values": [decoded]})
        else:
            if cur["attrs"]:
                cur["attrs"][-1]["values"].append(decoded)
    return version, status, req_id, groups


def _decode_value(t, val):
    if t in (T_CHARSET, T_NATURAL_LANGUAGE, T_KEYWORD, T_URI, T_NAME, T_TEXT, T_MIMETYPE):
        return val.decode("utf-8", "replace")
    if t == T_INTEGER:
        return struct.unpack(">i", val)[0] if len(val) == 4 else int.from_bytes(val, "big")
    if t == T_BOOLEAN:
        return bool(val[0]) if val else None
    if t == T_ENUM:
        return struct.unpack(">i", val)[0] if len(val) == 4 else int.from_bytes(val, "big")
    if t == T_RESOLUTION:
        if len(val) >= 9:
            x, y, u = struct.unpack(">iib", val[:9])
            return {"x": x, "y": y, "units": u}
        return val.hex()
    if t == T_RANGE:
        if len(val) == 8:
            a, b = struct.unpack(">ii", val)
            return {"low": a, "high": b}
        return val.hex()
    if t in (T_BEG_COLLECTION, T_END_COLLECTION):
        return "<collection>"
    return val.decode("utf-8", "replace") if all(32 <= c < 127 for c in val) else val.hex()


def ipp_call(ip, operation, attributes, job_attributes=None, data=b"", path="/ipp/print", timeout=20):
    url = f"http://{ip}:631{path}"
    body = build_request(operation, attributes, job_attributes, data)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/ipp")
    req.add_header("Content-Length", str(len(body)))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return parse_response(raw), raw


def base_attrs(ip, extra_requested=None):
    attrs = [
        (T_CHARSET, "attributes-charset", ["utf-8"]),
        (T_NATURAL_LANGUAGE, "attributes-natural-language", ["en-us"]),
        (T_URI, "printer-uri", [f"ipp://{ip}:631/ipp/print"]),
    ]
    return attrs


def get_printer_attributes(ip, requested=None):
    attrs = base_attrs(ip)
    if requested:
        attrs.append((T_KEYWORD, "requested-attributes", requested))
    (version, status, req_id, groups), raw = ipp_call(ip, OP_GET_PRINTER_ATTRIBUTES, attrs)
    return version, status, groups, raw


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.100"
    version, status, groups, raw = get_printer_attributes(ip)
    print(f"IPP version={version.hex()} status=0x{status:04X} ({STATUS.get(status, '?')}) raw={len(raw)}B")
    for g in groups:
        print(f"--- group tag 0x{g['tag']:02X} ---")
        for a in g["attrs"]:
            vals = a["values"]
            if len(vals) > 12:
                vals = vals[:12] + [f"... ({len(a['values'])} total)"]
            print(f"  {a['name']:<38} = {vals}")
    # dump raw to file for offline inspection
    with open("ipp_attrs_raw.bin", "wb") as f:
        f.write(raw)
    print("\nraw saved -> ipp_attrs_raw.bin")


if __name__ == "__main__":
    main()
