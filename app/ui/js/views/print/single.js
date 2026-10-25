/**
 * views/print/single.js — 单张打印：大预览 + 选项面板 + 图片编辑
 */

import { h, icon, button, iconButton, chip, fmt } from '../../components/ui.js';
import { createOptionsPanel } from './options.js';
import { createImageEditor } from './edit.js';
import {
  MEDIA_VALUES,
  createDropzone,
  defaultMedia,
  describeOptions,
  isSupportedFile,
  makeOptions,
  previewUrl,
} from './shared.js';

export function createSingleMode({ ctx, onChange }) {
  const defaults = makeOptions(defaultMedia(ctx.state));
  const state = {
    options: makeOptions(defaultMedia(ctx.state)),
    file: null,
    edited: false,
    page: 0,
    uploading: false,
    busy: false,
    previewLoading: false,
    previewError: '',
  };

  let previewTimer = null;
  let previewSeq = 0;
  let lastPages = state.options.pages;

  const optionsPanel = createOptionsPanel({
    options: state.options,
    defaults,
    mediaValues: MEDIA_VALUES,
    onChange: () => {
      syncPageFromOptions();
      paint();
      schedulePreview();
    },
  });

  const editor = createImageEditor({
    ctx,
    onApply: (uploaded, { restored }) => {
      state.file = uploaded;
      state.edited = !restored;
      state.page = 0;
      paint();
      refreshPreview({ immediate: true });
    },
    onBusyChange: (busy) => {
      state.busy = busy;
      paint();
    },
  });

  const drop = createDropzone({
    multiple: false,
    title: '把图片或 PDF 拖到这里',
    hint: '支持 PDF、JPG、PNG、WEBP、BMP、TIFF',
    meta: '文件只在本机临时处理，不会上传到任何服务器',
    onFiles: handleFiles,
  });

  /* ---------------------------------------------------------------- 结构 */

  const fileTitle = h('span', { class: 'preview-title-text', text: '打印预览' });
  const fileMeta = h('span', { class: 'preview-sub', text: '尚未选择文件' });
  const pageLabel = h('span', { class: 'preview-page-label', text: '' });

  const prevBtn = iconButton({
    icon: 'chevronLeft',
    label: '上一页',
    size: 18,
    onclick: () => goPage(-1),
  });
  const nextBtn = iconButton({
    icon: 'chevronRight',
    label: '下一页',
    size: 18,
    onclick: () => goPage(1),
  });
  const refreshBtn = iconButton({
    icon: 'refresh',
    label: '重新生成预览',
    size: 18,
    onclick: () => refreshPreview({ immediate: true }),
  });
  const replaceBtn = button({
    label: '更换文件',
    icon: 'folder',
    variant: 'text',
    size: 'sm',
    onclick: () => drop.input.click(),
  });

  const previewImg = h('img', {
    class: 'preview-image',
    alt: '打印预览',
    decoding: 'async',
    hidden: true,
  });

  const errorText = h('p', { class: 'preview-error-text' });
  const previewErrorBox = h(
    'div',
    { class: 'preview-error', hidden: true },
    h('span', { class: 'preview-error-icon' }, icon('warning', 22)),
    errorText,
    button({
      label: '重试',
      icon: 'refresh',
      variant: 'tonal',
      size: 'sm',
      onclick: () => refreshPreview({ immediate: true }),
    })
  );

  const previewEmpty = h('div', { class: 'preview-empty' }, drop.el);
  const shimmer = h('div', { class: 'preview-shimmer', 'aria-hidden': 'true' });

  const stage = h(
    'div',
    { class: 'preview-stage is-empty' },
    previewEmpty,
    previewImg,
    previewErrorBox,
    shimmer
  );

  const footChips = h('div', { class: 'preview-chips' });
  const statusText = h('span', {
    class: 'preview-status',
    role: 'status',
    'aria-live': 'polite',
    text: '',
  });

  const card = h(
    'section',
    { class: 'card preview-card', 'aria-label': '打印预览' },
    h(
      'div',
      { class: 'preview-toolbar' },
      h('div', { class: 'preview-heading' }, fileTitle, fileMeta),
      h('div', { class: 'preview-tools' }, prevBtn, pageLabel, nextBtn, refreshBtn, replaceBtn)
    ),
    stage,
    h('div', { class: 'preview-foot' }, footChips, statusText)
  );

  const el = h(
    'div',
    { class: 'print-workspace print-single' },
    card,
    h('div', { class: 'print-side' }, optionsPanel.el, editor.el)
  );

  /* ---------------------------------------------------------------- 拖放 */

  ['dragenter', 'dragover'].forEach((type) => {
    card.addEventListener(type, (event) => {
      event.preventDefault();
      card.classList.add('is-dragover');
    });
  });
  ['dragleave', 'dragend'].forEach((type) => {
    card.addEventListener(type, (event) => {
      event.preventDefault();
      if (event.relatedTarget && card.contains(event.relatedTarget)) return;
      card.classList.remove('is-dragover');
    });
  });
  card.addEventListener('drop', (event) => {
    event.preventDefault();
    card.classList.remove('is-dragover');
    const files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length) handleFiles(files);
  });

  /* ---------------------------------------------------------------- 状态 */

  function totalPages() {
    return state.file ? Math.max(1, Number(state.file.pages) || 1) : 0;
  }

  /** 页码范围选中具体某页时，预览同步跳到该页（仅响应页码变化本身） */
  function syncPageFromOptions() {
    if (state.options.pages === lastPages) return;
    lastPages = state.options.pages;
    const pages = totalPages();
    const wanted = Number(state.options.pages);
    if (!pages || !Number.isFinite(wanted)) return;
    const next = Math.min(pages, Math.max(1, Math.trunc(wanted))) - 1;
    if (next !== state.page) state.page = next;
  }

  function canSubmit() {
    const printer = ctx.state.printer;
    return Boolean(
      state.file &&
        !state.uploading &&
        !state.busy &&
        printer &&
        printer.online
    );
  }

  function paint() {
    const hasFile = Boolean(state.file);
    const pages = totalPages();
    const showNav = hasFile && pages > 1;

    previewEmpty.hidden = hasFile;
    previewImg.hidden = !hasFile || Boolean(state.previewError);
    stage.classList.toggle('is-empty', !hasFile);
    card.classList.toggle('has-file', hasFile);

    prevBtn.hidden = !showNav;
    nextBtn.hidden = !showNav;
    pageLabel.hidden = !showNav;
    refreshBtn.hidden = !hasFile;
    replaceBtn.hidden = !hasFile;
    pageLabel.textContent = showNav ? `${state.page + 1} / ${pages}` : '';

    fileTitle.textContent = hasFile ? state.file.name : '打印预览';
    fileMeta.textContent = hasFile
      ? `${state.file.kind === 'pdf' ? 'PDF' : '图片'} · ${fmt.pages(pages)} · ${fmt.bytes(state.file.size)}`
      : '尚未选择文件';

    const chips = [];
    if (hasFile) {
      chips.push(
        chip({
          label: state.file.kind === 'pdf' ? 'PDF' : '图片',
          tone: 'neutral',
          icon: state.file.kind === 'pdf' ? 'fileText' : 'image',
        })
      );
      chips.push(chip({ label: fmt.pages(pages), tone: 'neutral' }));
      chips.push(chip({ label: fmt.bytes(state.file.size), tone: 'neutral' }));
      if (state.edited) chips.push(chip({ label: '已编辑', tone: 'tertiary', icon: 'check' }));
    }
    footChips.replaceChildren(...chips);

    if (state.uploading) statusText.textContent = '正在上传文件…';
    else if (state.previewError) statusText.textContent = state.previewError;
    else if (hasFile) {
      statusText.textContent = state.edited
        ? `已编辑，预览与打印都使用编辑后的图片 · ${describeOptions(state.options)}`
        : describeOptions(state.options);
    } else statusText.textContent = '';

    if (typeof onChange === 'function') onChange();
  }

  /* ---------------------------------------------------------------- 上传 */

  async function handleFiles(fileListLike) {
    const incoming = Array.from(fileListLike || []);
    if (!incoming.length) return;
    // 编辑后正在上传时禁止换文件，否则「应用编辑」的回调会覆盖掉新选的文件。
    if (state.busy) {
      ctx.toast('正在应用编辑，请稍候再更换文件', { tone: 'warning' });
      return;
    }
    if (incoming.length > 1) {
      ctx.toast('单张打印一次只接受一个文件，已使用第一个', { tone: 'warning' });
    }
    const file = incoming[0];
    if (!isSupportedFile(file)) {
      ctx.toast('不支持的文件类型，请选择 PDF 或图片', { tone: 'error' });
      return;
    }

    state.uploading = true;
    state.previewError = '';
    previewErrorBox.hidden = true;
    stage.classList.remove('is-error');
    paint();

    try {
      const data = await ctx.api.upload([file]);
      const uploaded = Array.isArray(data.files) ? data.files[0] : null;
      if (!uploaded) throw new Error('上传未返回文件信息');
    state.file = uploaded;
    state.edited = false;
    state.page = 0;
    // 必须先归位页码范围，再重建下拉框：否则换文件后下拉框会显示上一份文件的
    // 页码（例如「第 3 页」），而实际提交的是「全部页」。
    state.options.pages = 'all';
    optionsPanel.setPages(Number(uploaded.pages) || 1);
    lastPages = 'all';
      editor.setFile(uploaded, file);
      paint();
      refreshPreview({ immediate: true });
    } catch (err) {
      ctx.toast(err.message || '上传失败', { tone: 'error', duration: 6000 });
    } finally {
      state.uploading = false;
      paint();
    }
  }

  /* ---------------------------------------------------------------- 预览 */

  function schedulePreview() {
    if (!state.file) return;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => refreshPreview(), 250);
  }

  function refreshPreview({ immediate = false } = {}) {
    if (!state.file) return;
    if (immediate) clearTimeout(previewTimer);

    const url = previewUrl({
      token: state.file.token,
      page: state.page,
      options: state.options,
      maxPx: 1200,
      mock: ctx.isMock,
      thumbs: state.file.thumbs,
    });

    if (!url) {
      showPreviewError('该文件没有可用的预览图');
      return;
    }

    const seq = ++previewSeq;
    state.previewLoading = true;
    state.previewError = '';
    previewErrorBox.hidden = true;
    stage.classList.remove('is-error');
    stage.classList.add('is-loading');
    stage.setAttribute('aria-busy', 'true');
    statusText.textContent = state.edited ? '已编辑，正在重新生成预览…' : '正在生成预览…';

    const probe = new Image();
    probe.decoding = 'async';
    probe.onload = () => {
      if (seq !== previewSeq) return;
      previewImg.src = url;
      previewImg.hidden = false;
      state.previewLoading = false;
      state.previewError = '';
      stage.classList.remove('is-loading', 'is-error');
      stage.removeAttribute('aria-busy');
      previewErrorBox.hidden = true;
      paint();
    };
    probe.onerror = () => {
      if (seq !== previewSeq) return;
      state.previewLoading = false;
      stage.classList.remove('is-loading');
      stage.removeAttribute('aria-busy');
      showPreviewError('预览生成失败，请重试');
    };
    probe.src = url;
  }

  function showPreviewError(message) {
    state.previewError = message;
    previewImg.hidden = true;
    previewErrorBox.hidden = false;
    errorText.textContent = message;
    stage.classList.add('is-error');
    statusText.textContent = message;
    paint();
  }

  function goPage(delta) {
    const pages = totalPages();
    if (pages <= 1) return;
    const next = Math.max(0, Math.min(pages - 1, state.page + delta));
    if (next === state.page) return;
    state.page = next;
    paint();
    refreshPreview({ immediate: true });
  }

  /* ---------------------------------------------------------------- 提交 */

  function summary() {
    if (!state.file) {
      return { title: '尚未选择文件', sub: '选择一张图片或一个 PDF 后即可预览并打印' };
    }
    return {
      title: state.file.name,
      sub: `${fmt.pages(totalPages())} · ${describeOptions(state.options)}`,
    };
  }

  async function submit() {
    if (!state.file) throw new Error('请先选择要打印的文件');
    const printer = ctx.state.printer;
    if (!printer) throw new Error('尚未注册打印机');
    if (!printer.online) throw new Error('打印机当前离线，无法提交打印');

    const result = await ctx.api.print({
      printer_id: printer.id,
      files: [state.file.token],
      options: {
        copies: state.options.copies,
        color: state.options.color,
        quality: state.options.quality,
        dpi: state.options.dpi,
        media: state.options.media,
        scale: state.options.scale,
        pages: state.options.pages || 'all',
        orientation: state.options.orientation,
      },
    });
    return { jobIds: [result.job_id] };
  }

  function reset() {
    clearTimeout(previewTimer);
    previewSeq += 1;
    state.file = null;
    state.edited = false;
    state.page = 0;
    state.uploading = false;
    state.busy = false;
    state.previewLoading = false;
    state.previewError = '';
    previewImg.removeAttribute('src');
    previewImg.hidden = true;
    previewErrorBox.hidden = true;
    stage.classList.remove('is-loading', 'is-error');
    stage.removeAttribute('aria-busy');
    optionsPanel.reset();
    optionsPanel.setPages(0);
    lastPages = 'all';
    editor.clear();
    drop.setBusy(false);
    paint();
  }

  function setBusy(busy) {
    state.busy = Boolean(busy);
    drop.setBusy(busy);
    paint();
  }

  function destroy() {
    clearTimeout(previewTimer);
    previewSeq += 1;
    if (editor && typeof editor.destroy === 'function') editor.destroy();
    else editor.clear();
    optionsPanel.destroy();
  }

  paint();

  return {
    el,
    canSubmit,
    submitLabel: () => '打印',
    summary,
    hasContent: () => Boolean(state.file),
    submit,
    reset,
    setBusy,
    destroy,
  };
}
