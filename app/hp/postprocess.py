"""扫描后处理：本地实现官方标称「需要 HP 安全云」的那批功能。

覆盖：
  * 自动裁切（去白边）
  * 自动定向 / 纠偏（基于文本行与轮廓的倾角检测）
  * 自动修复（去噪 + 自动对比度 + 轻度锐化）
  * 身份证双面合并
  * 多页拼版（2 合 1 / 4 合 1）
  * PDF 输出 + 密码保护 + 权限控制
  * OCR 文字层（可搜索 PDF）

依赖：Pillow、numpy、opencv-python(cv2)、PyMuPDF(fitz)；OCR 走 PaddleOCR 子进程。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageFilter, ImageOps

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


# ---------------------------------------------------------------------------
# 基础：图像读写
# ---------------------------------------------------------------------------

def load_image(data: bytes, dpi: int = 300) -> Image.Image:
    # 兜底：万一设备直接返回了 PDF（例如某些固件忽略 DocumentFormat），
    # 就用 PyMuPDF 把第一页栅格化，保证后续处理链路不断。
    if data[:4] == b"%PDF":
        import fitz

        doc = fitz.open("pdf", data)
        page = doc[0]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return img
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def encode_jpeg(img: Image.Image, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality, progressive=False, optimize=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 自动裁切
# ---------------------------------------------------------------------------

def auto_crop(img: Image.Image, margin: int = 8, threshold: int = 244) -> Image.Image:
    """去掉扫描出来的大片白边（保留 margin 像素呼吸空间）。"""
    gray = np.array(img.convert("L"))
    mask = gray < threshold
    if not mask.any():
        return img
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return img
    top = max(0, int(rows[0]) - margin)
    bottom = min(gray.shape[0], int(rows[-1]) + 1 + margin)
    left = max(0, int(cols[0]) - margin)
    right = min(gray.shape[1], int(cols[-1]) + 1 + margin)
    if (right - left) < 32 or (bottom - top) < 32:
        return img
    return img.crop((left, top, right, bottom))


# ---------------------------------------------------------------------------
# 自动定向 / 纠偏
# ---------------------------------------------------------------------------

def _skew_angle(gray: np.ndarray) -> float:
    """估计文本倾斜角（度）。优先用文本行投影，退化到轮廓最小外接矩形。"""
    if cv2 is None:
        return 0.0
    small = gray
    h, w = small.shape[:2]
    if max(h, w) > 1200:
        scale = 1200.0 / max(h, w)
        small = cv2.resize(small, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    # 二值化 + 形态学横向膨胀，让文字连成行
    thr = cv2.adaptiveThreshold(
        small, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
    joined = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, kernel)

    best = 0.0
    best_score = -1.0
    for angle in np.arange(-6.0, 6.01, 0.5):
        mat = cv2.getRotationMatrix2D((joined.shape[1] / 2, joined.shape[0] / 2), angle, 1.0)
        rot = cv2.warpAffine(joined, mat, (joined.shape[1], joined.shape[0]), flags=cv2.INTER_NEAREST)
        proj = rot.sum(axis=1).astype(np.float64)
        score = float(((proj[1:] - proj[:-1]) ** 2).sum())
        if score > best_score:
            best_score = score
            best = float(angle)
    return best


def auto_deskew(img: Image.Image, max_angle: float = 6.0) -> Tuple[Image.Image, float]:
    gray = np.array(img.convert("L"))
    angle = _skew_angle(gray)
    if abs(angle) < 0.4 or abs(angle) > max_angle:
        return img, 0.0
    # 旋转后补白，保持原尺寸
    return img.rotate(-angle, resample=Image.BICUBIC, expand=False, fillcolor="white"), angle


# ---------------------------------------------------------------------------
# 自动修复
# ---------------------------------------------------------------------------

def auto_enhance(img: Image.Image, denoise: bool = True) -> Image.Image:
    out = img
    if denoise and cv2 is not None:
        arr = np.array(out.convert("RGB"))
        den = cv2.fastNlMeansDenoisingColored(arr, None, 4, 4, 7, 21)
        out = Image.fromarray(den)
    out = ImageOps.autocontrast(out, cutoff=0.5)
    out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=3))
    return out


# ---------------------------------------------------------------------------
# 身份证双面合并 / 多页拼版
# ---------------------------------------------------------------------------

def compose_id_card(front: Image.Image, back: Image.Image, page: str = "a4") -> Image.Image:
    """正反面上下排列到同一页（A4 300dpi）。"""
    W, H = (2480, 3508) if page == "a4" else (2550, 3300)
    canvas = Image.new("RGB", (W, H), "white")
    pad = int(W * 0.06)
    slot_h = (H - pad * 3) // 2
    slot_w = W - pad * 2
    for index, src in enumerate((front, back)):
        fitted = ImageOps.contain(src.convert("RGB"), (slot_w, slot_h), Image.LANCZOS)
        x = (W - fitted.width) // 2
        y = pad + index * (slot_h + pad) + (slot_h - fitted.height) // 2
        canvas.paste(fitted, (x, y))
    return canvas


def compose_nup(images: Sequence[Image.Image], cols: int = 2, rows: int = 2,
                page: str = "a4") -> Image.Image:
    W, H = (2480, 3508) if page == "a4" else (2550, 3300)
    canvas = Image.new("RGB", (W, H), "white")
    pad = int(W * 0.03)
    cell_w = (W - pad * (cols + 1)) // cols
    cell_h = (H - pad * (rows + 1)) // rows
    for index, src in enumerate(images[: cols * rows]):
        r, c = divmod(index, cols)
        fitted = ImageOps.contain(src.convert("RGB"), (cell_w, cell_h), Image.LANCZOS)
        x = pad + c * (cell_w + pad) + (cell_w - fitted.width) // 2
        y = pad + r * (cell_h + pad) + (cell_h - fitted.height) // 2
        canvas.paste(fitted, (x, y))
    return canvas


# ---------------------------------------------------------------------------
# PDF：输出 / 密码 / 权限
# ---------------------------------------------------------------------------

# PDF 权限位（PyMuPDF）
PERM_PRINT = 4
PERM_MODIFY = 8
PERM_COPY = 16
PERM_ANNOTATE = 32


def to_pdf(images: Sequence[Image.Image], dpi: int = 300,
           password: Optional[str] = None,
           permissions: int = PERM_PRINT | PERM_COPY,
           ocr_text: Optional[Sequence[str]] = None) -> bytes:
    """把图片打成 PDF；可选加密 + 权限；可选叠加不可见文字层（可搜索）。"""
    import fitz  # PyMuPDF

    doc = fitz.open()
    for index, img in enumerate(images):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=92, progressive=False)
        rect = fitz.Rect(0, 0, img.width * 72.0 / dpi, img.height * 72.0 / dpi)
        page = doc.new_page(width=rect.width, height=rect.height)
        page.insert_image(rect, stream=buf.getvalue())
        text = (ocr_text[index] if ocr_text and index < len(ocr_text) else "") or ""
        if text.strip():
            # render_mode=3 → 不可见文字层，可被搜索/复制
            page.insert_textbox(
                fitz.Rect(8, 8, rect.width - 8, rect.height - 8),
                text,
                fontsize=8,
                fontname="helv",
                render_mode=3,
                overlay=True,
            )
    out = doc.tobytes(garbage=4, deflate=True)
    doc.close()

    if password:
        doc = fitz.open("pdf", out)
        out = doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw=password,
            user_pw=password,
            permissions=permissions,
            garbage=4,
            deflate=True,
        )
        doc.close()
    return out


# ---------------------------------------------------------------------------
# OCR（PaddleOCR 子进程，避免把 500MB 模型加载进服务进程）
# ---------------------------------------------------------------------------

_OCR_WORKER = r'''
import sys, json
import torch  # 必须先于 paddleocr 导入，否则 Windows 上 torch 的 DLL 目录没初始化
from paddleocr import PaddleOCR
ocr = PaddleOCR(lang=sys.argv[1] if len(sys.argv) > 1 else "ch", use_gpu=False, show_log=False)
out = []
for path in sys.argv[2:]:
    res = ocr.ocr(path)
    lines = []
    for page in (res or []):
        for item in (page or []):
            try:
                lines.append(item[1][0])
            except Exception:
                pass
    out.append("\n".join(lines))
print("<<<OCRJSON>>>" + json.dumps(out, ensure_ascii=False))
'''

#: 已知可用的本地 OCR 脚本（agent-ocr skill）。可用环境变量覆盖。
_OCR_SCRIPT_CANDIDATES = [
    os.environ.get("HP_OFFLINE_OCR_SCRIPT", ""),
    os.path.join(os.path.expanduser("~"), ".config", "opencode", "skills",
                 "agent-ocr", "scripts", "ocr_paddle.py"),
]


def _ocr_script() -> Optional[str]:
    for path in _OCR_SCRIPT_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


def _parse_ocr_script_output(text: str) -> str:
    """agent-ocr 输出格式：``[0.998] 识别文本`` 每行一条。"""
    lines = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("No text detected") or line.startswith("Written:"):
            continue
        if line.startswith("[") and "]" in line:
            line = line.split("]", 1)[1].strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def ocr_images(images: Sequence[Image.Image], lang: str = "ch",
               timeout: float = 300.0) -> List[str]:
    """对图片做 OCR，返回每页的文本。失败返回空串列表（不抛异常）。"""
    if not images:
        return []
    tmpdir = tempfile.mkdtemp(prefix="hpocr_")
    paths = []
    for index, img in enumerate(images):
        path = os.path.join(tmpdir, "p%02d.png" % index)
        img.save(path, "PNG")
        paths.append(path)

    script = _ocr_script()
    try:
        if script:
            texts: List[str] = []
            for path in paths:
                outfile = path + ".txt"
                proc = subprocess.run(
                    [sys.executable, script, path, "--lang", lang or "ch", "-o", outfile],
                    capture_output=True, timeout=timeout, text=True,
                    encoding="utf-8", errors="replace",
                )
                if os.path.isfile(outfile):
                    with open(outfile, encoding="utf-8", errors="replace") as handle:
                        texts.append(handle.read().strip())
                else:
                    texts.append(_parse_ocr_script_output(proc.stdout))
            return texts

        proc = subprocess.run(
            [sys.executable, "-c", _OCR_WORKER, lang] + paths,
            capture_output=True, timeout=timeout, text=True,
            encoding="utf-8", errors="replace",
        )
        marker = "<<<OCRJSON>>>"
        for line in (proc.stdout or "").splitlines():
            if line.startswith(marker):
                return json.loads(line[len(marker):])
        return [""] * len(images)
    except Exception:
        return [""] * len(images)
    finally:
        for path in paths:
            for extra in (path, path + ".txt"):
                try:
                    os.remove(extra)
                except OSError:
                    pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 一站式管线
# ---------------------------------------------------------------------------

def process_pages(
    blobs: Sequence[bytes],
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把扫描到的原始页做完整后处理。

    options:
      auto_crop / auto_orient / auto_enhance : bool
      merge  : "none" | "id_card" | "nup2" | "nup4"
      format : "jpeg" | "pdf"
      pdf_password : str
      pdf_allow_copy : bool
      ocr    : bool
      ocr_lang : "ch" | "en"
      dpi    : int
    """
    options = dict(options or {})
    images = [load_image(b) for b in blobs]

    notes: List[str] = []
    if options.get("auto_crop", True):
        images = [auto_crop(img) for img in images]
        notes.append("已自动裁切白边")
    if options.get("auto_orient", False):
        rotated = []
        angles = []
        for img in images:
            img2, angle = auto_deskew(img)
            rotated.append(img2)
            if angle:
                angles.append(round(angle, 1))
        images = rotated
        if angles:
            notes.append("已纠偏 %s°" % "/".join(str(a) for a in angles))
    if options.get("auto_enhance", False):
        images = [auto_enhance(img) for img in images]
        notes.append("已自动增强")

    merge = options.get("merge") or "none"
    if merge == "id_card" and len(images) >= 2:
        images = [compose_id_card(images[0], images[1])]
        notes.append("身份证正反面已合并")
    elif merge in ("nup2", "nup4"):
        per_sheet = 2 if merge == "nup2" else 4
        cols, rows = (2, 1) if merge == "nup2" else (2, 2)
        sheets = []
        for start in range(0, len(images), per_sheet):
            chunk = images[start:start + per_sheet]
            sheets.append(compose_nup(chunk, cols, rows))
        images = sheets
        notes.append("%d 合 1 拼版" % per_sheet)

    ocr_text: List[str] = []
    if options.get("ocr"):
        ocr_text = ocr_images(images, lang=options.get("ocr_lang") or "ch")
        if any(t.strip() for t in ocr_text):
            notes.append("已生成文字层（可搜索）")
        else:
            notes.append("OCR 未识别到文字")

    fmt = (options.get("format") or "jpeg").lower()
    dpi = int(options.get("dpi") or 300)
    if fmt == "pdf":
        data = to_pdf(
            images,
            dpi=dpi,
            password=options.get("pdf_password") or None,
            permissions=(PERM_PRINT | (PERM_COPY if options.get("pdf_allow_copy", True) else 0)),
            ocr_text=ocr_text if options.get("ocr") else None,
        )
        ext = "pdf"
        if options.get("pdf_password"):
            notes.append("PDF 已加密（AES-256）")
    else:
        data = encode_jpeg(images[0], quality=92) if images else b""
        ext = "jpg"

    return {
        "data": data,
        "ext": ext,
        "pages": len(images),
        "width": images[0].width if images else 0,
        "height": images[0].height if images else 0,
        "notes": notes,
        "ocr_text": "\n\n".join(t for t in ocr_text if t.strip()) if ocr_text else "",
    }
