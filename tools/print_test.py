"""End-to-end IPP print test against the HP printer.

Renders an A4 page at 300 dpi with PyMuPDF, encodes JPEG, submits an
IPP Print-Job (document-format: image/jpeg) and reports the job status.

Usage:
    python print_test.py [ip] [--color] [--dpi 300]
"""
import io
import sys
import time
import struct

import pymupdf

import ipp_probe as P

IP = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "192.168.1.100"
COLOR = "--color" in sys.argv
DPI = 300


def make_page_jpeg(dpi=300):
    """Render a test page to JPEG at the requested dpi."""
    w_in, h_in = 8.27, 11.69  # A4
    doc = pymupdf.open()
    page = doc.new_page(width=w_in * 72, height=h_in * 72)
    # header band
    page.draw_rect(pymupdf.Rect(0, 0, page.rect.width, 70), color=None, fill=(0.13, 0.13, 0.13))
    page.insert_text((40, 46), "HP OFFLINE  -  IPP PRINT TEST", fontsize=22, color=(1, 1, 1))
    y = 120
    page.insert_text((40, y), "Printer : HP Ink Tank Wireless 410 series", fontsize=13)
    y += 22
    page.insert_text((40, y), f"Path    : IPP Print-Job  document-format=image/jpeg", fontsize=13)
    y += 22
    page.insert_text((40, y), f"DPI     : {dpi}   Media: iso_a4_210x297mm", fontsize=13)
    y += 22
    page.insert_text((40, y), f"Time    : {time.strftime('%Y-%m-%d %H:%M:%S')}", fontsize=13)
    y += 34
    page.insert_text((40, y), "If you can read this line clearly, the offline pipeline works.", fontsize=11)
    y += 26
    # colour bars
    bars = [(1, 0, 0), (1, 0.5, 0), (1, 1, 0), (0, 0.6, 0), (0, 0.4, 1), (0.6, 0, 1), (0, 0, 0)]
    for i, c in enumerate(bars):
        page.draw_rect(pymupdf.Rect(40 + i * 70, y, 100 + i * 70, y + 45), color=None, fill=c)
    y += 70
    # fine line test
    for i in range(6):
        page.draw_line(pymupdf.Point(40, y + i * 6), pymupdf.Point(540, y + i * 6), color=(0, 0, 0), width=0.6)
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB if COLOR else pymupdf.csGRAY)
    data = pix.tobytes("jpeg", jpg_quality=90)
    return data, pix.width, pix.height


def print_job(ip, jpeg, copies=1, color=False):
    attrs = [
        (P.T_CHARSET, "attributes-charset", ["utf-8"]),
        (P.T_NATURAL_LANGUAGE, "attributes-natural-language", ["en-us"]),
        (P.T_URI, "printer-uri", [f"ipp://{ip}:631/ipp/print"]),
        (P.T_NAME, "requesting-user-name", ["hp-offline"]),
        (P.T_NAME, "job-name", ["HP Offline test page"]),
        (P.T_MIMETYPE, "document-format", ["image/jpeg"]),
    ]
    job_attrs = [
        (P.T_INTEGER, "copies", [copies]),
        (P.T_KEYWORD, "media", ["iso_a4_210x297mm"]),
        (P.T_KEYWORD, "print-color-mode", ["color" if color else "monochrome"]),
        (P.T_ENUM, "print-quality", [4]),
    ]
    (version, status, req_id, groups), raw = P.ipp_call(
        ip, P.OP_PRINT_JOB, attrs, job_attrs, data=jpeg, timeout=90
    )
    return status, groups


def get_job(ip, job_id):
    attrs = [
        (P.T_CHARSET, "attributes-charset", ["utf-8"]),
        (P.T_NATURAL_LANGUAGE, "attributes-natural-language", ["en-us"]),
        (P.T_URI, "printer-uri", [f"ipp://{ip}:631/ipp/print"]),
        (P.T_INTEGER, "job-id", [job_id]),
    ]
    (version, status, req_id, groups), raw = P.ipp_call(ip, P.OP_GET_JOB_ATTRIBUTES, attrs, timeout=30)
    return status, groups


def main():
    print(f"target {IP}  color={COLOR} dpi={DPI}")
    jpeg, w, h = make_page_jpeg(DPI)
    print(f"page raster {w}x{h}px  jpeg {len(jpeg)/1024:.0f} KiB")
    t0 = time.time()
    status, groups = print_job(IP, jpeg, color=COLOR)
    print(f"Print-Job -> 0x{status:04X} {P.STATUS.get(status, '?')}  ({time.time()-t0:.2f}s)")
    job_id = None
    for g in groups:
        for a in g["attrs"]:
            if a["name"] in ("job-id", "job-state", "job-state-reasons", "job-uri", "job-state-message"):
                print(f"  {a['name']:<22} {a['values']}")
            if a["name"] == "job-id":
                job_id = a["values"][0]
    if job_id:
        for i in range(10):
            time.sleep(1.5)
            st, gs = get_job(IP, job_id)
            state = reasons = None
            for g in gs:
                for a in g["attrs"]:
                    if a["name"] == "job-state":
                        state = a["values"][0]
                    if a["name"] == "job-state-reasons":
                        reasons = a["values"]
            print(f"  poll {i}: state={state} reasons={reasons}")
            if state in (7, 8, 9):  # canceled, aborted, completed
                break


if __name__ == "__main__":
    main()
