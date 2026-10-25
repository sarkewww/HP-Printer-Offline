/**
 * views/print/edit.js — 图片编辑（纯前端画布 + 实时预览）
 *
 * 管线：
 *   原图 File → <img> 解码 → 预览画布实时重绘（旋转 / 翻转 / 亮度 / 对比度 / 裁剪）
 *   → 应用时用全分辨率画布重新渲染 → canvas.toBlob('image/png') → File
 *   → ctx.api.upload([file]) → 新 token → onApply(next, { restored:false })
 *
 * 裁剪与旋转的顺序：**先旋转 / 翻转，再居中裁剪**。
 * 即先把原图画进一张「显示方向」的中间画布（旋转 90° 时宽高互换、水平翻转按屏幕方向镜像），
 * 再在这张中间画布上按 CROP_RATIOS 居中裁剪。这样裁剪比例始终是用户看到的那个方向
 * （旋转 90° 后选 4:3 得到的仍是横向 4:3），预览与最终应用结果完全一致。
 */

import { h, icon, button, iconButton, selectField, slider } from '../../components/ui.js';
import { spinner } from '../../components/feedback.js';
import { CROP_OPTIONS } from './shared.js';

const CROP_RATIOS = {
  '1:1': 1,
  '4:3': 4 / 3,
  '3:2': 3 / 2,
  '16:9': 16 / 9,
};

/** 预览画布最长边（px）：只影响预览性能，不影响应用时的输出分辨率 */
const PREVIEW_MAX_PX = 1200;

const HINT_READY = '拖动滑块或点击旋转，预览会立即更新；点「应用编辑」后预览与打印都会使用编辑结果。';
const HINT_IDLE = '编辑在本地画布完成，应用后会重新上传并刷新预览。';

export function createImageEditor({ ctx, onApply, onBusyChange }) {
  let uploaded = null;
  let originalFile = null;
  let sourceImage = null;
  let objectUrl = '';
  let busy = false;
  let dirty = false;
  let applied = false;
  let ready = false;
  let destroyed = false;
  let loadSeq = 0;
  let rafId = 0;
  let tempCache = null; // { key, canvas } —— 显示方向（旋转 + 翻转）的中间画布缓存

  const edit = {
    rotation: 0,
    flipH: false,
    brightness: 100,
    contrast: 100,
    crop: 'original',
  };

  /* ------------------------------------------------------------------ 元素 */

  const status = h('p', {
    class: 'edit-status',
    role: 'status',
    'aria-live': 'polite',
    text: HINT_IDLE,
  });

  // 应用失败时的完整错误信息（后端返回的 message 原样显示，不只 toast）
  const alertText = h('span', { class: 'edit-alert-text' });
  const alertBox = h(
    'div',
    { class: 'edit-alert', role: 'alert', hidden: true },
    h('span', { class: 'edit-alert-icon', 'aria-hidden': 'true' }, icon('warning', 18)),
    alertText
  );

  const canvas = h('canvas', {
    class: 'edit-canvas',
    role: 'img',
    'aria-label': '编辑效果预览',
    width: 1,
    height: 1,
    hidden: true,
  });

  const loadErrorText = h('p', { class: 'edit-error-text' });
  const retryBtn = button({
    label: '重试',
    icon: 'refresh',
    variant: 'tonal',
    size: 'sm',
    onclick: () => loadSource(),
  });
  const loadErrorBox = h(
    'div',
    { class: 'edit-error', role: 'alert', hidden: true },
    h('span', { class: 'edit-error-icon', 'aria-hidden': 'true' }, icon('warning', 20)),
    loadErrorText,
    retryBtn
  );

  const canvasWrap = h('div', { class: 'edit-canvas-wrap' }, canvas, loadErrorBox);

  const rotateBadge = h('span', {
    class: 'edit-rotate-badge',
    text: '0°',
    'aria-hidden': 'true',
  });

  const rotateBtn = iconButton({
    icon: 'rotate',
    label: '旋转 90 度',
    size: 18,
    onclick: rotate,
  });

  const flipBtn = iconButton({
    icon: 'flipHorizontal',
    label: '水平翻转',
    size: 18,
    onclick: () => {
      edit.flipH = !edit.flipH;
      flipBtn.classList.toggle('is-active', edit.flipH);
      flipBtn.setAttribute('aria-pressed', String(edit.flipH));
      markDirty();
      schedulePaint();
    },
  });
  flipBtn.setAttribute('aria-pressed', 'false');

  const brightness = slider({
    label: '亮度',
    ariaLabel: '亮度',
    min: 50,
    max: 150,
    step: 5,
    value: edit.brightness,
    format: (value) => `${value}%`,
    oninput: (value) => {
      edit.brightness = value;
      markDirty();
      schedulePaint();
    },
  });

  const contrast = slider({
    label: '对比度',
    ariaLabel: '对比度',
    min: 50,
    max: 150,
    step: 5,
    value: edit.contrast,
    format: (value) => `${value}%`,
    oninput: (value) => {
      edit.contrast = value;
      markDirty();
      schedulePaint();
    },
  });

  const crop = selectField({
    label: '裁剪比例',
    options: CROP_OPTIONS,
    value: edit.crop,
    onchange: (event) => {
      edit.crop = event.target.value;
      markDirty();
      schedulePaint();
    },
  });

  const applyBtn = button({
    label: '应用编辑',
    icon: 'check',
    variant: 'tonal',
    onclick: applyEdit,
    disabled: true,
  });

  const resetBtn = button({
    label: '重置编辑',
    icon: 'refresh',
    variant: 'text',
    size: 'sm',
    onclick: resetEditor,
  });

  const el = h(
    'section',
    { class: 'card edit-panel', 'aria-label': '图片编辑', hidden: true },
    h(
      'div',
      { class: 'edit-head' },
      h('div', { class: 'section-heading' }, h('h2', { class: 'section-title', text: '图片编辑' })),
      h('span', { class: 'edit-badge', text: '仅图片' })
    ),
    canvasWrap,
    h(
      'div',
      { class: 'edit-tools' },
      rotateBtn,
      rotateBadge,
      flipBtn,
      h('span', { class: 'edit-tools-hint', text: '旋转 / 翻转' })
    ),
    h('div', { class: 'edit-sliders' }, brightness, contrast),
    crop,
    h('div', { class: 'edit-actions' }, applyBtn, resetBtn),
    alertBox,
    status
  );

  /* ------------------------------------------------------------------ 状态 */

  function setBusy(next) {
    busy = next;
    applyBtn.disabled = busy || !ready || !sourceImage;
    resetBtn.disabled = busy;
    rotateBtn.disabled = busy;
    flipBtn.disabled = busy;
    brightness.input.disabled = busy;
    contrast.input.disabled = busy;
    // 应用期间禁止改裁剪：否则「已应用」的图片和用户刚改出的画布会不一致。
    if (crop && typeof crop.setDisabled === 'function') crop.setDisabled(busy);
    applyBtn.replaceChildren(
      busy ? spinner(17, '正在应用编辑') : icon('check', 19),
      h('span', { class: 'btn-label', text: busy ? '正在应用…' : '应用编辑' })
    );
    if (typeof onBusyChange === 'function') onBusyChange(busy);
  }

  function markDirty() {
    dirty = true;
    alertBox.hidden = true;
    if (ready) status.textContent = '有未应用的调整，画布已是最终效果，点「应用编辑」写入预览。';
  }

  function syncRotationUI() {
    rotateBadge.textContent = `${edit.rotation}°`;
    rotateBtn.title = `旋转 90°（当前 ${edit.rotation}°）`;
    rotateBtn.setAttribute('aria-label', `旋转 90 度，当前 ${edit.rotation} 度`);
    rotateBtn.classList.toggle('is-active', edit.rotation !== 0);
  }

  function rotate() {
    edit.rotation = (edit.rotation + 90) % 360;
    syncRotationUI();
    markDirty();
    schedulePaint();
  }

  function resetState() {
    edit.rotation = 0;
    edit.flipH = false;
    edit.brightness = 100;
    edit.contrast = 100;
    edit.crop = 'original';
    brightness.setValue(100);
    contrast.setValue(100);
    crop.select.setValue('original');
    flipBtn.classList.remove('is-active');
    flipBtn.setAttribute('aria-pressed', 'false');
    syncRotationUI();
  }

  function resetEditor() {
    if (busy) return;
    resetState();
    dirty = false;
    alertBox.hidden = true;
    if (ready) status.textContent = HINT_READY;
    schedulePaint();
    // 已经应用过编辑时，用最初的 token 恢复原图（uploaded 始终保存原图描述符）
    if (applied && uploaded) onApply(uploaded, { restored: true });
    applied = false;
  }

  /* ------------------------------------------------------------------ 渲染 */

  function cropRatio(name) {
    return CROP_RATIOS[name] || null;
  }

  /**
   * 生成「显示方向」的整幅中间画布：先水平翻转（屏幕方向），再顺时针旋转。
   * 旋转 / 翻转未变化时复用缓存，滑块与裁剪只重绘最终画布。
   */
  function buildDisplayCanvas() {
    const image = sourceImage;
    if (!image) throw new Error('图片尚未读取完成');
    const nw = image.naturalWidth || image.width;
    const nh = image.naturalHeight || image.height;
    if (!nw || !nh) throw new Error('无法读取该图片的尺寸');

    const rotation = ((edit.rotation % 360) + 360) % 360;
    const key = `${nw}x${nh}|${rotation}|${edit.flipH ? 1 : 0}`;
    if (tempCache && tempCache.key === key) return tempCache.canvas;

    const swap = rotation % 180 !== 0;
    const width = swap ? nh : nw;
    const height = swap ? nw : nh;

    const temp = document.createElement('canvas');
    temp.width = Math.max(1, Math.round(width));
    temp.height = Math.max(1, Math.round(height));
    const tctx = temp.getContext('2d');
    if (!tctx) throw new Error('当前浏览器不支持画布编辑');

    tctx.save();
    tctx.translate(temp.width / 2, temp.height / 2);
    // 水平翻转放在旋转之前：镜像轴始终是屏幕的竖轴，符合「翻转我看到的图」的直觉
    if (edit.flipH) tctx.scale(-1, 1);
    tctx.rotate((rotation * Math.PI) / 180); // 正值 = 顺时针（画布 y 轴向下）
    tctx.drawImage(image, -nw / 2, -nh / 2, nw, nh);
    tctx.restore();

    tempCache = { key, canvas: temp };
    return temp;
  }

  /**
   * 把当前编辑效果画进 target。
   * @param {HTMLCanvasElement} target
   * @param {number} maxPx 最长边上限；0 表示全分辨率（应用时使用）
   */
  function paintCanvas(target, maxPx = 0) {
    const display = buildDisplayCanvas();
    const dw = display.width;
    const dh = display.height;

    // 先旋转 / 翻转（display 已是显示方向），再在显示方向上居中裁剪
    const ratio = cropRatio(edit.crop);
    let sx = 0;
    let sy = 0;
    let sw = dw;
    let sh = dh;
    if (ratio) {
      if (dw / dh > ratio) {
        sw = dh * ratio;
        sx = (dw - sw) / 2;
      } else {
        sh = dw / ratio;
        sy = (dh - sh) / 2;
      }
    }

    const scale = maxPx > 0 ? Math.min(1, maxPx / Math.max(sw, sh)) : 1;
    const outW = Math.max(1, Math.round(sw * scale));
    const outH = Math.max(1, Math.round(sh * scale));

    target.width = outW;
    target.height = outH;
    const tctx = target.getContext('2d');
    if (!tctx) throw new Error('当前浏览器不支持画布编辑');

    tctx.save();
    tctx.clearRect(0, 0, outW, outH);
    if ('filter' in tctx) {
      tctx.filter = `brightness(${edit.brightness}%) contrast(${edit.contrast}%)`;
    }
    tctx.drawImage(display, sx, sy, sw, sh, 0, 0, outW, outH);
    tctx.restore();
    return target;
  }

  /** requestAnimationFrame 合并：滑块连续拖动时每帧最多重绘一次 */
  function schedulePaint() {
    if (destroyed || rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = 0;
      paintPreview();
    });
  }

  function paintPreview() {
    if (!ready || !sourceImage) return;
    try {
      paintCanvas(canvas, PREVIEW_MAX_PX);
      canvas.hidden = false;
      loadErrorBox.hidden = true;
    } catch (err) {
      showLoadError(err.message || '无法渲染该图片');
    }
  }

  function renderBlob() {
    return new Promise((resolve, reject) => {
      try {
        const full = document.createElement('canvas');
        paintCanvas(full, 0);
        full.toBlob(
          (blob) => {
            if (blob) resolve(blob);
            else reject(new Error('无法生成编辑后的图片，可能是图片尺寸过大'));
          },
          'image/png'
        );
      } catch (err) {
        reject(err);
      }
    });
  }

  /* ------------------------------------------------------------------ 应用 */

  async function applyEdit() {
    if (busy || !sourceImage) return;
    setBusy(true);
    alertBox.hidden = true;
    status.textContent = '正在生成编辑后的图片…';
    try {
      const blob = await renderBlob();
      const baseName = (originalFile && originalFile.name ? originalFile.name : 'image').replace(/\.[^.]+$/, '');
      const editedFile = new File([blob], `${baseName}-edited.png`, { type: 'image/png' });
      const data = await ctx.api.upload([editedFile]);
      if (destroyed) return; // 视图已卸载，别再回调父组件
      const next = Array.isArray(data && data.files) ? data.files[0] : null;
      if (!next) throw new Error('上传编辑结果失败：服务器没有返回文件信息');
      applied = true;
      dirty = false;
      status.textContent = '已应用编辑，预览与打印都会使用编辑后的图片。';
      onApply(next, { restored: false });
    } catch (err) {
      const message = (err && err.message) || '应用编辑失败';
      alertText.textContent = message;
      alertBox.hidden = false;
      status.textContent = message;
      if (ctx && typeof ctx.toast === 'function') {
        ctx.toast(message, { tone: 'error', duration: 6000 });
      }
    } finally {
      setBusy(false);
    }
  }

  /* ------------------------------------------------------------------ 载入 */

  function showLoadError(message) {
    ready = false;
    sourceImage = null;
    canvas.hidden = true;
    loadErrorBox.hidden = false;
    loadErrorText.textContent = message;
    applyBtn.disabled = true;
    status.textContent = message;
  }

  function releaseImage() {
    // 让所有在途的解码回调失效，避免旧图的 onload 覆盖新图状态
    loadSeq += 1;
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = '';
    }
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
    sourceImage = null;
    tempCache = null;
    ready = false;
    applyBtn.disabled = true;
  }

  function loadSource() {
    if (!originalFile) return;
    releaseImage();
    loadErrorBox.hidden = true;
    alertBox.hidden = true;
    canvas.hidden = true;

    const seq = loadSeq;
    objectUrl = URL.createObjectURL(originalFile);
    const image = new Image();
    image.decoding = 'async';
    image.onload = () => {
      if (seq !== loadSeq) return; // 已被更新的文件取代
      if (!image.naturalWidth || !image.naturalHeight) {
        showLoadError('无法读取该图片，可能是格式不支持');
        return;
      }
      sourceImage = image;
      ready = true;
      loadErrorBox.hidden = true;
      applyBtn.disabled = busy;
      status.textContent = HINT_READY;
      schedulePaint();
    };
    image.onerror = () => {
      if (seq !== loadSeq) return;
      showLoadError('无法读取该图片，可能是格式不支持');
    };
    image.src = objectUrl;
  }

  function setFile(fileDescriptor, file) {
    uploaded = fileDescriptor || null;
    originalFile = file || null;
    releaseImage();
    resetState();
    dirty = false;
    applied = false;
    alertBox.hidden = true;
    loadErrorBox.hidden = true;
    status.textContent = HINT_IDLE;

    const isImage = Boolean(fileDescriptor && fileDescriptor.kind === 'image');
    if (!isImage || !originalFile) {
      el.hidden = true;
      canvas.hidden = true;
      return;
    }

    el.hidden = false;
    loadSource();
  }

  function clear() {
    releaseImage();
    uploaded = null;
    originalFile = null;
    dirty = false;
    applied = false;
    resetState();
    el.hidden = true;
    canvas.hidden = true;
    loadErrorBox.hidden = true;
    alertBox.hidden = true;
    status.textContent = HINT_IDLE;
  }

  applyBtn.replaceChildren(icon('check', 19), h('span', { class: 'btn-label', text: '应用编辑' }));
  syncRotationUI();

  function destroy() {
    destroyed = true;
    releaseImage();
    // crop 是 selectField，菜单会挂到 document.body 上，必须显式销毁，
    // 否则视图卸载后会在 body 里留下孤儿菜单和 pointerdown 监听。
    if (crop && typeof crop.destroy === 'function') crop.destroy();
  }

  return { el, setFile, clear, setBusy, destroy };
}

/** 兼容旧命名：对外签名保持 createEditor({ ctx, onApply, onBusyChange }) */
export { createImageEditor as createEditor };
