/**
 * views/print/shared.js — 打印视图共用常量、预览地址与拖放区域
 *
 * 预览地址必须与后端打印管线使用同一组参数，这样「所见即所印」。
 */

import { assetUrl } from '../../api.js';
import { h, icon, mediaLabel } from '../../components/ui.js';

/** 真机支持且允许用户选择的纸张（不做能力猜测） */
export const MEDIA_VALUES = [
  'iso_a4_210x297mm',
  'na_letter_8.5x11in',
  'na_legal_8.5x14in',
  'iso_a5_148x210mm',
  'na_index-4x6_4x6in',
  'na_5x7_5x7in',
  'om_small-photo_100x150mm',
];

export const DEFAULT_OPTIONS = {
  copies: 1,
  color: 'auto',
  quality: 'normal',
  dpi: 300,
  media: 'iso_a4_210x297mm',
  scale: 'fit',
  orientation: 'auto',
  pages: 'all',
  auto_enhance: true,
};

export const ORIENTATION_OPTIONS = [
  { value: 'auto', label: '自动' },
  { value: 'portrait', label: '纵向' },
  { value: 'landscape', label: '横向' },
];

export const SCALE_OPTIONS = [
  { value: 'fit', label: '适应' },
  { value: 'fill', label: '铺满' },
  { value: 'actual', label: '原始' },
];

export const COLOR_OPTIONS = [
  { value: 'color', label: '彩色' },
  { value: 'monochrome', label: '黑白' },
  { value: 'auto', label: '自动' },
];

export const QUALITY_OPTIONS = [
  { value: 'draft', label: '草稿' },
  { value: 'normal', label: '标准' },
  { value: 'best', label: '最佳' },
];

export const CROP_OPTIONS = [
  { value: 'original', label: '原图比例' },
  { value: '1:1', label: '1 : 1' },
  { value: '4:3', label: '4 : 3' },
  { value: '3:2', label: '3 : 2' },
  { value: '16:9', label: '16 : 9' },
];

export const ACTIVE_STATES = new Set(['queued', 'preparing', 'sending', 'printing']);
export const TERMINAL_STATES = new Set(['done', 'error', 'canceled']);

const COLOR_LABEL = { auto: '自动色彩', color: '彩色', monochrome: '黑白' };
const QUALITY_LABEL = { draft: '草稿质量', normal: '标准质量', best: '最佳质量' };
const ORIENTATION_LABEL = { auto: '自动方向', portrait: '纵向', landscape: '横向' };
const SCALE_LABEL = { fit: '适应纸张', fill: '铺满纸张', actual: '原始尺寸' };

export function makeOptions(media) {
  return { ...DEFAULT_OPTIONS, media: media || DEFAULT_OPTIONS.media };
}

export function defaultMedia(state) {
  const ready = state && state.status && state.status.media && state.status.media.ready;
  return MEDIA_VALUES.includes(ready) ? ready : DEFAULT_OPTIONS.media;
}

export function mediaChoices(values = MEDIA_VALUES) {
  return values.map((value) => ({ value, label: mediaLabel(value) }));
}

/**
 * 构造与打印管线一致的预览地址。
 * mock 模式下后端没有预览接口，退回上传返回的 data-URI 缩略图。
 */
export function previewUrl({ token, page = 0, options = {}, maxPx = 1100, mock = false, thumbs = null }) {
  if (!token) return '';
  if (mock) return (thumbs && thumbs[page]) || '';
  const params = new URLSearchParams();
  params.set('dpi', '150');
  params.set('color', options.color || 'auto');
  params.set('quality', options.quality || 'normal');
  params.set('scale', options.scale || 'fit');
  if (options.media) params.set('media', options.media);
  params.set('orientation', options.orientation || 'auto');
  params.set('max_px', String(maxPx));
  return assetUrl(`/api/print/thumb/${encodeURIComponent(token)}/${page}?${params.toString()}`);
}

/** 把 0 基页码数组压成后端可识别的 "1-3,5" 形式 */
export function compressPages(pages) {
  const numbers = Array.from(new Set(pages))
    .map((page) => Number(page) + 1)
    .sort((a, b) => a - b);
  if (!numbers.length) return 'all';
  const parts = [];
  let start = numbers[0];
  let prev = numbers[0];
  for (let i = 1; i < numbers.length; i += 1) {
    const value = numbers[i];
    if (value === prev + 1) {
      prev = value;
      continue;
    }
    parts.push(start === prev ? String(start) : `${start}-${prev}`);
    start = value;
    prev = value;
  }
  parts.push(start === prev ? String(start) : `${start}-${prev}`);
  return parts.join(',');
}

export function describeOptions(options) {
  return [
    `${options.copies} 份`,
    COLOR_LABEL[options.color] || options.color,
    QUALITY_LABEL[options.quality] || options.quality,
    mediaLabel(options.media),
    ORIENTATION_LABEL[options.orientation] || options.orientation,
    SCALE_LABEL[options.scale] || options.scale,
  ].join(' · ');
}

const ACCEPT = 'application/pdf,image/jpeg,image/png,image/webp,image/bmp,image/tiff';
const EXT_PATTERN = /\.(pdf|jpe?g|png|webp|bmp|tiff?)$/i;

export function isSupportedFile(file) {
  if (!file) return false;
  if (/^(application\/pdf|image\/)/i.test(file.type || '')) return true;
  return EXT_PATTERN.test(file.name || '');
}

/**
 * 可点击、可键盘操作、可拖放的选文件区域。
 * 用真正的 <button>，因此 Enter / Space 原生可用。
 */
export function createDropzone({ multiple = false, title, hint, meta, onFiles, compact = false }) {
  const input = h('input', {
    type: 'file',
    multiple,
    accept: ACCEPT,
    class: 'visually-hidden',
    tabindex: '-1',
    'aria-hidden': 'true',
  });

  const zone = h(
    'button',
    {
      class: `dropzone${compact ? ' is-compact' : ''}`,
      type: 'button',
      'aria-label': multiple ? '选择要打印的文件，可多选' : '选择要打印的文件',
    },
    h('span', { class: 'dropzone-icon', 'aria-hidden': 'true' }, icon('upload', 26)),
    h('span', { class: 'dropzone-title', text: title }),
    h('span', { class: 'dropzone-hint', text: hint }),
    meta ? h('span', { class: 'dropzone-meta', text: meta }) : null
  );

  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', (event) => {
    // 先快照成数组再清空 input：部分 Chromium 版本在 value='' 后会让
    // 之前取到的 FileList 同步变空，导致文件被静默丢弃。
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (files.length) onFiles(files);
  });

  ['dragenter', 'dragover'].forEach((type) => {
    zone.addEventListener(type, (event) => {
      event.preventDefault();
      event.stopPropagation();
      zone.classList.add('is-dragover');
    });
  });
  ['dragleave', 'dragend'].forEach((type) => {
    zone.addEventListener(type, (event) => {
      event.preventDefault();
      if (event.relatedTarget && zone.contains(event.relatedTarget)) return;
      zone.classList.remove('is-dragover');
    });
  });
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    event.stopPropagation();
    zone.classList.remove('is-dragover');
    const files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length) onFiles(files);
  });

  const el = h('div', { class: 'dropzone-wrap' }, zone, input);
  return {
    el,
    zone,
    input,
    setBusy(busy) {
      zone.disabled = Boolean(busy);
    },
  };
}
