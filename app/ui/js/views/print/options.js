/**
 * views/print/options.js — 打印选项面板（单张 / 批量共用）
 *
 * 面板直接修改传入的 options 对象；任何变化都通过 onChange 通知调用方，
 * 由调用方负责刷新预览或摘要。
 */

import { h, button, segmented, selectField, stepper, mediaLabel } from '../../components/ui.js';
import {
  COLOR_OPTIONS,
  ORIENTATION_OPTIONS,
  QUALITY_OPTIONS,
  SCALE_OPTIONS,
  mediaChoices,
} from './shared.js';

export function createOptionsPanel({
  options,
  defaults,
  mediaValues,
  onChange,
  showPages = true,
  readyMedia = null,
  subtitle = '这些设置会同时应用到预览与打印结果',
}) {
  let pagesField = null;

  const group = (label, control) =>
    h('div', { class: 'option-group' }, h('span', { class: 'option-label', text: label }), control);

  const orientation = segmented({
    options: ORIENTATION_OPTIONS,
    value: options.orientation,
    block: true,
    ariaLabel: '打印方向',
    onchange: (value) => {
      options.orientation = value;
      changed();
    },
  });

  const scale = segmented({
    options: SCALE_OPTIONS,
    value: options.scale,
    block: true,
    ariaLabel: '缩放方式',
    onchange: (value) => {
      options.scale = value;
      changed();
    },
  });

  const media = selectField({
    label: '纸张尺寸',
    options: mediaChoices(mediaValues),
    value: options.media,
    onchange: (event) => {
      options.media = event.target.value;
      syncMediaHint();
      changed();
    },
  });

  const mediaHint = h('div', { class: 'media-hint', hidden: true });
  const mediaUseReady = button({
    label: '改用当前装纸',
    variant: 'text',
    size: 'sm',
    onclick: () => {
      if (!readyMedia) return;
      options.media = readyMedia;
      media.select.setValue(readyMedia);
      syncMediaHint();
      changed();
    },
  });

  function syncMediaHint() {
    if (!readyMedia) {
      mediaHint.hidden = true;
      return;
    }
    const mismatch = String(options.media || '') !== String(readyMedia);
    // 让后端按「实际装纸」出画布，但按选中尺寸的真实物理大小排版
    options.canvas_media = mismatch ? readyMedia : null;
    mediaHint.hidden = !mismatch;
    if (mismatch) {
      mediaHint.replaceChildren(
        h('span', {
          class: 'media-hint-text',
          text:
            '打印机当前装纸是 ' + mediaLabel(readyMedia) +
            '，与你选择的 ' + mediaLabel(options.media) +
            ' 不一致；打印机会按实际装纸输出。',
        }),
        mediaUseReady
      );
    }
  }
  syncMediaHint();

  const color = segmented({
    options: COLOR_OPTIONS,
    value: options.color,
    block: true,
    ariaLabel: '色彩模式',
    onchange: (value) => {
      options.color = value;
      changed();
    },
  });

  const quality = segmented({
    options: QUALITY_OPTIONS,
    value: options.quality,
    block: true,
    ariaLabel: '打印质量',
    onchange: (value) => {
      options.quality = value;
      changed();
    },
  });

  const copies = stepper({
    label: '份数',
    value: options.copies,
    min: 1,
    max: 99,
    onchange: (value) => {
      options.copies = value;
      changed();
    },
  });

  const pagesSlot = h('div', { class: 'option-group', hidden: true });

  const resetBtn = button({
    label: '恢复默认选项',
    icon: 'refresh',
    variant: 'text',
    size: 'sm',
    onclick: () => {
      reset();
      changed();
    },
  });

  const el = h(
    'aside',
    { class: 'card print-options', 'aria-label': '打印选项' },
    h(
      'div',
      { class: 'print-options-head' },
      h('h2', { class: 'section-title', text: '打印选项' }),
      h('p', { class: 'section-sub', text: subtitle })
    ),
    group('方向', orientation),
    group('缩放', scale),
    media,
    mediaHint,
    group('彩色', color),
    group('质量', quality),
    h('div', { class: 'option-group' }, copies),
    pagesSlot,
    h('div', { class: 'option-group option-group-reset' }, resetBtn)
  );

  function changed() {
    if (typeof onChange === 'function') onChange();
  }

  function renderPages(count) {
    if (pagesField) {
      if (typeof pagesField.destroy === 'function') pagesField.destroy();
      pagesField = null;
    }
    pagesSlot.replaceChildren();
    const total = Number(count) || 0;
    const visible = showPages && total > 1;
    pagesSlot.hidden = !visible;
    if (!visible) {
      options.pages = 'all';
      return;
    }
    const items = [{ value: 'all', label: `全部 ${total} 页` }];
    for (let page = 1; page <= total; page += 1) {
      items.push({ value: String(page), label: `仅第 ${page} 页` });
    }
    pagesField = selectField({
      label: '打印页码',
      options: items,
      value: options.pages === 'all' ? 'all' : String(options.pages),
      onchange: (event) => {
        options.pages = event.target.value;
        changed();
      },
    });
    pagesSlot.append(pagesField);
  }

  function reset() {
    Object.assign(options, {
      ...defaults,
      media: defaults.media,
      canvas_media: null,
      pages: 'all',
    });
    orientation.setValue(options.orientation);
    scale.setValue(options.scale);
    media.select.setValue(options.media);
    syncMediaHint();
    color.setValue(options.color);
    quality.setValue(options.quality);
    copies.setValue(options.copies);
    if (pagesField) pagesField.select.setValue('all');
    options.pages = 'all';
  }

  function destroy() {
    if (pagesField && typeof pagesField.destroy === 'function') pagesField.destroy();
    if (typeof media.destroy === 'function') media.destroy();
  }

  return {
    el,
    setPages: (count) => renderPages(count),
    reset,
    destroy,
  };
}
