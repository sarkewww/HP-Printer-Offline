"""页面栅格化：PDF / 图片 → **baseline** JPEG 字节流。

⚠️ 本文件最重要的一条约束
------------------------
PyMuPDF 的 ``pix.tobytes("jpeg")`` 输出的是 **progressive JPEG（SOF2）**，
这台 HP Ink Tank 410 会直接拒收（``0x041B`` + ``document-unprintable-error``）。
因此这里统一走 ``pix → PIL.Image → save(progressive=False, optimize=False)``，
确保输出是 baseline（SOF0）。:func:`is_baseline_jpeg` 用于自检。
"""

from __future__ import annotations

import io
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import get_logger

log = get_logger("hp.render")

#: A4（英寸）
A4_WIDTH_IN = 8.2677
A4_HEIGHT_IN = 11.6929

#: quality 名称 → JPEG 质量
JPEG_QUALITY = {"draft": 72, "normal": 88, "best": 95}

#: quality 名称 → IPP print-quality 枚举（3 draft / 4 normal / 5 best）
PRINT_QUALITY_ENUM = {"draft": 3, "normal": 4, "best": 5}

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"}

_MEDIA_RE = re.compile(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)(in|mm)")


# ---------------------------------------------------------------------------
# 媒体尺寸
# ---------------------------------------------------------------------------


def media_to_inches(media: Optional[str]) -> Tuple[float, float]:
    """把 IPP 媒体名解析成英寸尺寸；无法解析时回退 A4。

    例：``iso_a4_210x297mm`` → (8.27, 11.69)；``na_index-4x6_4x6in`` → (4, 6)。
    """
    if media:
        matches = _MEDIA_RE.findall(media)
        if matches:
            width, height, unit = matches[-1]
            w = float(width)
            h = float(height)
            if unit == "mm":
                w /= 25.4
                h /= 25.4
            if 1.0 <= w <= 20.0 and 1.0 <= h <= 20.0:
                return w, h
    return A4_WIDTH_IN, A4_HEIGHT_IN


def canvas_size(dpi: int, media: Optional[str] = None) -> Tuple[int, int]:
    """给定 dpi 与媒体尺寸，返回画布像素尺寸。"""
    width_in, height_in = media_to_inches(media)
    return int(round(width_in * dpi)), int(round(height_in * dpi))


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _load_pil():
    from PIL import Image, ImageOps  # 延迟导入，未安装时错误更清晰

    return Image, ImageOps


def _load_pymupdf():
    try:
        import pymupdf  # type: ignore

        return pymupdf
    except ImportError:  # pragma: no cover - 旧包名
        import fitz  # type: ignore

        return fitz


def file_kind(path: str) -> str:
    """返回 ``pdf`` / ``image`` / ``unknown``。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    # 按内容再猜一次
    try:
        with open(path, "rb") as handle:
            head = handle.read(8)
        if head.startswith(b"%PDF"):
            return "pdf"
        if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8"):
            return "image"
    except OSError:
        pass
    return "unknown"


def is_baseline_jpeg(data: bytes) -> bool:
    """检查是否为 baseline JPEG（存在 SOF0，且不存在 SOF2 渐进标记）。"""
    return b"\xff\xc0" in data and b"\xff\xc2" not in data


def count_pages(path: str) -> int:
    """统计文档页数。PDF 用 PyMuPDF，多帧 TIFF 用 Pillow，其它图片算 1 页。"""
    kind = file_kind(path)
    if kind == "pdf":
        pymupdf = _load_pymupdf()
        with pymupdf.open(path) as doc:
            return max(1, doc.page_count)
    if kind == "image":
        Image, _ = _load_pil()
        try:
            with Image.open(path) as img:
                return max(1, int(getattr(img, "n_frames", 1)))
        except Exception as exc:  # noqa: BLE001
            log.warning("统计图片页数失败 %s: %s", path, exc)
            return 1
    return 1


def parse_page_spec(spec: Optional[str], total: int) -> List[int]:
    """解析 ``"all"`` / ``"1-3,5"`` → 0 基页索引列表。"""
    if not spec or str(spec).strip().lower() in ("all", "*", ""):
        return list(range(total))
    pages: List[int] = []
    for chunk in str(spec).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_text, _, end_text = chunk.partition("-")
            try:
                start = int(start_text)
                end = int(end_text) if end_text else start
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for page in range(start, end + 1):
                if 1 <= page <= total and (page - 1) not in pages:
                    pages.append(page - 1)
        else:
            try:
                page = int(chunk)
            except ValueError:
                continue
            if 1 <= page <= total and (page - 1) not in pages:
                pages.append(page - 1)
    return sorted(pages) or list(range(total))


# ---------------------------------------------------------------------------
# 画布合成
# ---------------------------------------------------------------------------


def _enhance_photo(image):
    """照片打印前的轻量增强（近似 HP PageLift 的 DocEnhance 效果）。

    HP 原实现是 TensorFlow Lite 模型（HPPageLift.UWP.dll 里的 DocEnhance），
    这里用经典图像处理做等效近似：自动色阶 + 提亮阴影 + 轻微饱和 + 轻度锐化。
    只在「自动优化图片」开启时调用；关闭时输出原图。
    """
    Image, ImageOps = _load_pil()
    from PIL import ImageEnhance, ImageFilter

    out = image.convert("RGB")
    # 1) 自动色阶：裁掉 0.3% 极值，拉开对比
    out = ImageOps.autocontrast(out, cutoff=0.3)
    # 2) 提亮阴影：gamma 0.92（>1 会压暗，<1 会提亮）
    lut = [min(255, int(round(255.0 * ((i / 255.0) ** 0.92)))) for i in range(256)]
    out = out.point(lut * 3)
    # 3) 轻微饱和度
    out = ImageEnhance.Color(out).enhance(1.05)
    # 4) 轻度锐化（打印会轻微糊，补一点）
    out = out.filter(ImageFilter.UnsharpMask(radius=1.0, percent=45, threshold=3))
    return out


def _apply_brightness(image, percent: int):
    """按百分比整体提亮/压暗（-100..100）。"""
    try:
        value = int(percent or 0)
    except (TypeError, ValueError):
        value = 0
    if value == 0:
        return image
    gain = 1.0 + value / 100.0
    lut = [max(0, min(255, int(round(i * gain)))) for i in range(256)]
    return image.convert("RGB").point(lut * 3)


def _to_srgb(image):
    """把带 ICC 配置的图片转换到 sRGB。

    不做这一步时，手机拍的 Display P3 / Adobe RGB 图片会被当作 sRGB 直接打，
    颜色会明显偏暗偏灰 —— 这是「打印出来比原图暗」的常见根因。
    """
    icc = None
    try:
        icc = (image.info or {}).get("icc_profile")
    except Exception:  # noqa: BLE001
        icc = None
    if not icc:
        return image
    try:
        from PIL import ImageCms

        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        dst = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(image.convert("RGB"), src, dst, outputMode="RGB")
    except Exception as exc:  # noqa: BLE001
        log.warning("ICC 转换失败，按原色域输出：%s", exc)
        return image


def _srgb_profile_bytes():
    try:
        from PIL import ImageCms

        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:  # noqa: BLE001
        return None


def _flatten(image, monochrome: bool):
    """把任意模式安全地压成 RGB/L。

    关键：带透明通道（RGBA/LA/P+transparency）的图**必须先合成到白底**再转 RGB，
    否则 ``convert("RGB")`` 会直接丢弃 alpha、把透明像素里残留的颜色（常见是纯红）
    原样打出来 —— 既难看又白白烧墨水。
    """
    Image, _ = _load_pil()
    image = _to_srgb(image)
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in (image.info or {})
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    elif image.mode == "CMYK":
        image = image.convert("RGB")
    elif image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return image.convert("L") if monochrome else image.convert("RGB")


def _compose(
    image,
    dpi: int,
    media: Optional[str],
    scale: str,
    monochrome: bool,
    orientation: str = "auto",
    target_media: Optional[str] = None,
):
    """把一页图像按 ``scale`` 合成到目标媒体画布上。"""
    Image, _ = _load_pil()
    target_w, target_h = canvas_size(dpi, media)

    image = _flatten(image, monochrome)

    orientation = (orientation or "auto").lower()
    if orientation == "landscape":
        # 横向：旋转 90°，画布也换成横向
        image = image.rotate(-90, expand=True)
        target_w, target_h = target_h, target_w
    elif orientation == "portrait" and image.width > image.height:
        # 明确要求纵向时，把横图转正
        image = image.rotate(-90, expand=True)

    scale = (scale or "fit").lower()
    src_w, src_h = image.size
    if src_w == target_w and src_h == target_h:
        return image

    if scale == "fill":
        factor = max(target_w / src_w, target_h / src_h)
        new_size = (max(1, int(round(src_w * factor))), max(1, int(round(src_h * factor))))
        resized = image.resize(new_size, Image.LANCZOS)
        left = max(0, (resized.width - target_w) // 2)
        top = max(0, (resized.height - target_h) // 2)
        return resized.crop((left, top, left + target_w, top + target_h))

    if scale == "actual":
        # 不缩放，从左上角开始放置（超出部分裁掉）
        # 注意：Pillow 里 Image.new("RGB", size, 255) 会得到 (255,0,0) 纯红，
        # 必须显式给三元组，否则整页底色变红、狂烧墨水。
        canvas = Image.new("L" if monochrome else "RGB", (target_w, target_h),
                           (255,) if monochrome else (255, 255, 255))
        canvas.paste(image.crop((0, 0, min(src_w, target_w), min(src_h, target_h))), (0, 0))
        return canvas

    # 真实物理尺寸：选中 4x6 但纸盒是 A4 时，把图片放进「4x6 英寸」的框里再居中贴到 A4 画布
    if target_media and target_media != media:
        box_w, box_h = canvas_size(dpi, target_media)
        factor = min(box_w / src_w, box_h / src_h)
        new_size = (max(1, int(round(src_w * factor))), max(1, int(round(src_h * factor))))
        resized = image.resize(new_size, Image.LANCZOS)
        canvas = Image.new("L" if monochrome else "RGB", (target_w, target_h),
                           (255,) if monochrome else (255, 255, 255))
        # 与 HP 一致：小尺寸放在纸张左上角，方便裁切
        canvas.paste(resized, (0, 0))
        return canvas

    # fit（默认）：等比缩放到画布内并居中
    factor = min(target_w / src_w, target_h / src_h)
    new_size = (max(1, int(round(src_w * factor))), max(1, int(round(src_h * factor))))
    resized = image.resize(new_size, Image.LANCZOS)
    canvas = Image.new("L" if monochrome else "RGB", (target_w, target_h),
                       (255,) if monochrome else (255, 255, 255))
    canvas.paste(resized, ((target_w - new_size[0]) // 2, (target_h - new_size[1]) // 2))
    return canvas


def _to_jpeg(image, dpi: int, quality: int) -> bytes:
    buffer = io.BytesIO()
    extra = {}
    if image.mode != "L":
        profile = _srgb_profile_bytes()
        if profile:
            # 带上 sRGB 配置，避免打印机按自己的默认色域解释导致偏暗
            extra["icc_profile"] = profile
    image.save(
        buffer,
        "JPEG",
        quality=int(quality),
        progressive=False,  # 必须：设备拒收 progressive（SOF2）
        optimize=False,
        dpi=(dpi, dpi),
        subsampling=0 if image.mode == "L" else 2,
        **extra,
    )
    data = buffer.getvalue()
    if not is_baseline_jpeg(data):  # pragma: no cover - 理论上不会触发
        log.error("渲染结果不是 baseline JPEG（缺少 SOF0 或含 SOF2）")
    return data


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


def render_pages(
    path: str,
    dpi: int = 300,
    color: str = "auto",
    quality: str = "normal",
    scale: str = "fit",
    media: Optional[str] = None,
    page_spec: Optional[str] = "all",
    orientation: str = "auto",
    canvas_media: Optional[str] = None,
    enhance: bool = False,
    brightness: int = 0,
) -> List[bytes]:
    """把文档渲染为 baseline JPEG 列表（每页一个）。

    参数
    ----
    dpi       : 300 / 600（600 更清晰但更慢）
    color     : ``auto`` / ``color`` → RGB；``monochrome`` → 灰度
    quality   : ``draft`` / ``normal`` / ``best``
    scale     : ``fit`` / ``fill`` / ``actual``
    media     : IPP 媒体名，用于决定画布尺寸（默认 A4）
    page_spec : ``all`` 或 ``1-3,5``
    """
    dpi = int(dpi or 300)
    if dpi < 72:
        dpi = 72
    if dpi > 1200:
        dpi = 1200
    jpeg_quality = JPEG_QUALITY.get((quality or "normal").lower(), 88)
    monochrome = (color or "auto").lower() == "monochrome"

    # 选中尺寸与纸盒实际装纸不同时：按 canvas_media 出画布，按 media 的真实尺寸排版
    target_media = media if (canvas_media and canvas_media != media) else None
    if canvas_media:
        media = canvas_media

    kind = file_kind(path)
    if kind == "unknown":
        raise ValueError("不支持的文件类型：%s" % os.path.basename(path))

    pages: List[bytes] = []
    Image, ImageOps = _load_pil()

    if kind == "pdf":
        pymupdf = _load_pymupdf()
        with pymupdf.open(path) as doc:
            indices = parse_page_spec(page_spec, max(1, doc.page_count))
            colorspace = pymupdf.csGRAY if monochrome else pymupdf.csRGB
            for index in indices:
                page = doc.load_page(index)
                pix = page.get_pixmap(dpi=dpi, colorspace=colorspace, alpha=False)
                mode = "L" if monochrome else "RGB"
                image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
                composed = _compose(image, dpi, media, scale, monochrome, orientation, target_media)
                pages.append(_to_jpeg(composed, dpi, jpeg_quality))
                image.close()
                composed.close()
    else:
        with Image.open(path) as img:
            total = max(1, int(getattr(img, "n_frames", 1)))
            indices = parse_page_spec(page_spec, total)
            for index in indices:
                if total > 1:
                    img.seek(index)
                frame = ImageOps.exif_transpose(img.copy())
                if enhance:
                    frame = _enhance_photo(frame)
                if brightness:
                    frame = _apply_brightness(frame, brightness)
                try:
                    # 小图放大到目标 dpi 的等效尺寸，避免打印出邮票大小
                    width_in = frame.width / 96.0
                    height_in = frame.height / 96.0
                    if width_in < 4.0 and height_in < 4.0:
                        frame = frame.resize(
                            (max(1, int(width_in * dpi)), max(1, int(height_in * dpi))),
                            Image.LANCZOS,
                        )
                    composed = _compose(frame, dpi, media, scale, monochrome, orientation, target_media)
                    pages.append(_to_jpeg(composed, dpi, jpeg_quality))
                    composed.close()
                finally:
                    frame.close()

    if not pages:
        raise ValueError("文档没有可打印的页面")
    return pages


def _placeholder_thumb(max_px: int, label: str = "加密文件") -> bytes:
    """生成占位缩略图（加密 PDF / 损坏文件时用，避免接口 500）。"""
    Image, _ = _load_pil()
    from PIL import ImageDraw

    size = max(80, int(max_px))
    img = Image.new("RGB", (size, int(size * 1.414)), (247, 249, 252))
    draw = ImageDraw.Draw(img)
    draw.rectangle([2, 2, img.width - 3, img.height - 3], outline=(214, 219, 227), width=2)
    cx, cy = img.width // 2, img.height // 2
    draw.rectangle([cx - 18, cy - 6, cx + 18, cy + 22], outline=(120, 128, 140), width=3)
    draw.arc([cx - 13, cy - 24, cx + 13, cy + 4], 180, 360, fill=(120, 128, 140), width=3)
    buffer = io.BytesIO()
    img.save(buffer, "PNG", optimize=True)
    img.close()
    return buffer.getvalue()


def render_thumb(path: str, page: int = 0, max_px: int = 280) -> bytes:
    """生成 PNG 缩略图（用于前端预览）。

    加密 PDF / 损坏文件不能抛异常，否则前端整页报 500；统一返回占位图。
    """
    Image, _ = _load_pil()
    kind = file_kind(path)
    if kind == "pdf":
        pymupdf = _load_pymupdf()
        try:
            with pymupdf.open(path) as doc:
                if getattr(doc, "needs_pass", False):
                    return _placeholder_thumb(max_px, "加密 PDF")
                index = max(0, min(int(page), doc.page_count - 1))
                pdf_page = doc.load_page(index)
                zoom = max_px / max(1.0, pdf_page.rect.width)
                matrix = pymupdf.Matrix(zoom, zoom)
                pix = pdf_page.get_pixmap(matrix=matrix, alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        except Exception as exc:  # noqa: BLE001
            log.warning("PDF 缩略图失败（%s），返回占位图：%s", os.path.basename(path), exc)
            return _placeholder_thumb(max_px)
    else:
        try:
            with Image.open(path) as img:
                total = max(1, int(getattr(img, "n_frames", 1)))
                index = max(0, min(int(page), total - 1))
                if total > 1:
                    img.seek(index)
                image = img.convert("RGB")
        except Exception as exc:  # noqa: BLE001
            log.warning("图片缩略图失败（%s），返回占位图：%s", os.path.basename(path), exc)
            return _placeholder_thumb(max_px)
    try:
        image.thumbnail((max_px, max_px), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "PNG", optimize=True)
        return buffer.getvalue()
    finally:
        image.close()


def thumbnail_bytes(image_bytes: bytes, max_px: int = 280) -> bytes:
    """对内存中的图像字节生成 PNG 缩略图。"""
    Image, _ = _load_pil()
    with Image.open(io.BytesIO(image_bytes)) as img:
        rgb = img.convert("RGB")
    try:
        rgb.thumbnail((max_px, max_px), Image.LANCZOS)
        buffer = io.BytesIO()
        rgb.save(buffer, "PNG", optimize=True)
        return buffer.getvalue()
    finally:
        rgb.close()


def preview_png(
    path: str,
    page: int = 0,
    dpi: int = 150,
    color: str = "auto",
    quality: str = "normal",
    scale: str = "fit",
    media: Optional[str] = None,
    orientation: str = "auto",
    max_px: int = 900,
) -> bytes:
    """按当前打印参数渲染预览（PNG）。

    预览必须和真正送打的一致（方向、缩放、黑白），否则用户看到的是假预览。
    这里用较低 dpi 渲染再缩到 max_px，保证速度。
    """
    pages = render_pages(
        path,
        dpi=dpi,
        color=color,
        quality=quality,
        scale=scale,
        media=media,
        page_spec=str(page + 1),
        orientation=orientation,
    )
    if not pages:
        raise ValueError("没有可预览的页面")
    return thumbnail_bytes(pages[0], max_px=max_px)


def image_dimensions(data: bytes) -> Tuple[int, int]:
    """返回图像像素尺寸；失败时 (0, 0)。"""
    try:
        Image, _ = _load_pil()
        with Image.open(io.BytesIO(data)) as img:
            return img.width, img.height
    except Exception as exc:  # noqa: BLE001
        log.warning("读取图像尺寸失败: %s", exc)
        return 0, 0


def images_to_pdf(images: Sequence[bytes], dpi: int = 300) -> bytes:
    """把多张 JPEG 合成一个 PDF（扫描格式选 pdf 时使用）。"""
    Image, _ = _load_pil()
    frames = []
    try:
        for data in images:
            with Image.open(io.BytesIO(data)) as img:
                frames.append(img.convert("RGB"))
        if not frames:
            raise ValueError("没有图像可合成 PDF")
        buffer = io.BytesIO()
        frames[0].save(buffer, "PDF", resolution=float(dpi), save_all=True, append_images=frames[1:])
        return buffer.getvalue()
    finally:
        for frame in frames:
            frame.close()


def describe(path: str) -> Dict[str, Any]:
    """上传时的文件描述信息。"""
    size = os.path.getsize(path)
    return {"kind": file_kind(path), "pages": count_pages(path), "size": size}
