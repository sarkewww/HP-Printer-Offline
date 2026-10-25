/**
 * views/print/batch.js — 批量打印：多文件 → 逐页列表 → 勾选后按文件分组提交
 */

import { h, icon, button, iconButton, fmt } from '../../components/ui.js';
import { emptyState, spinner } from '../../components/feedback.js';
import { createOptionsPanel } from './options.js';
import {
  MEDIA_VALUES,
  compressPages,
  createDropzone,
  defaultMedia,
  describeOptions,
  isSupportedFile,
  makeOptions,
  previewUrl,
} from './shared.js';

const KEY_SEP = '::';

export function createBatchMode({ ctx, onChange }) {
  const defaults = makeOptions(defaultMedia(ctx.state));
  const state = {
    options: makeOptions(defaultMedia(ctx.state)),
    files: [],
    selected: new Set(),
    uploading: false,
    busy: false,
  };

  const optionsPanel = createOptionsPanel({
    options: state.options,
    defaults,
    mediaValues: MEDIA_VALUES,
    showPages: false,
    subtitle: '全局选项会应用到所有勾选的页面',
    onChange: () => {
      refreshThumbs();
      paint();
    },
  });

  const drop = createDropzone({
    multiple: true,
    title: '把多个文件拖到这里',
    hint: '支持 PDF 与图片混合批量打印',
    meta: '文件只在本机临时处理，不会上传到任何服务器',
    onFiles: handleFiles,
  });

  /* ---------------------------------------------------------------- 结构 */

  const countChip = h('span', { class: 'chip chip-neutral' }, h('span', { text: '0 / 0 页' }));

  const selectAllBtn = button({
    label: '全选',
    variant: 'outlined',
    size: 'sm',
    onclick: () => selectAll(),
  });
  const selectNoneBtn = button({
    label: '取消全选',
    variant: 'text',
    size: 'sm',
    onclick: () => selectNone(),
  });
  const oddBtn = button({
    label: '仅奇数页',
    variant: 'text',
    size: 'sm',
    onclick: () => selectParity(1),
  });
  const evenBtn = button({
    label: '仅偶数页',
    variant: 'text',
    size: 'sm',
    onclick: () => selectParity(0),
  });

  const quickBar = h(
    'div',
    { class: 'batch-quick', role: 'group', 'aria-label': '页面快捷选择' },
    selectAllBtn,
    selectNoneBtn,
    oddBtn,
    evenBtn
  );

  const uploadNotice = h('div', { class: 'batch-uploading', hidden: true });

  const listSlot = h('div', { class: 'batch-list' });

  const clearAllBtn = button({
    label: '移除全部',
    icon: 'trash',
    variant: 'text',
    size: 'sm',
    onclick: () => reset(),
  });

  const card = h(
    'section',
    { class: 'card batch-card', 'aria-label': '页面列表' },
    h(
      'div',
      { class: 'section-head' },
      h(
        'div',
        { class: 'section-heading' },
        h('h2', { class: 'section-title', text: '页面列表' }),
        h('p', {
          class: 'section-sub',
          text: '每个文件按页展开，勾选需要打印的页面；缩略图按当前纸张生成',
        })
      ),
      h('div', { class: 'section-actions' }, countChip, clearAllBtn)
    ),
    drop.el,
    quickBar,
    uploadNotice,
    listSlot
  );

  const sumSelected = h('strong', { text: '0 / 0 页' });
  const sumCopies = h('strong', { text: '1 份' });
  const sumTotal = h('strong', { text: '0 页' });

  const summaryCard = h(
    'section',
    { class: 'card batch-summary', 'aria-label': '批量打印摘要' },
    h('div', { class: 'batch-summary-row' }, h('span', { text: '已选页面' }), sumSelected),
    h('div', { class: 'batch-summary-row' }, h('span', { text: '份数' }), sumCopies),
    h('div', { class: 'batch-summary-row is-strong' }, h('span', { text: '预计打印' }), sumTotal)
  );

  const el = h(
    'div',
    { class: 'print-workspace print-batch' },
    card,
    h('div', { class: 'print-side' }, optionsPanel.el, summaryCard)
  );

  /* ---------------------------------------------------------------- 列表 */

  function filePages(file) {
    return Math.max(1, Number(file.pages) || 1);
  }

  function totalPages() {
    return state.files.reduce((sum, file) => sum + filePages(file), 0);
  }

  function selectedPagesOf(file) {
    const pages = filePages(file);
    let count = 0;
    for (let page = 0; page < pages; page += 1) {
      if (state.selected.has(`${file.token}${KEY_SEP}${page}`)) count += 1;
    }
    return count;
  }

  function pageRow(file, page) {
    const key = `${file.token}${KEY_SEP}${page}`;
    const checked = state.selected.has(key);

    const input = h('input', {
      class: 'page-check',
      type: 'checkbox',
      checked,
      'aria-label': `${file.name} 第 ${page + 1} 页`,
    });
    input.addEventListener('change', () => {
      if (input.checked) state.selected.add(key);
      else state.selected.delete(key);
      paint();
    });

    const thumbUrl = previewUrl({
      token: file.token,
      page,
      options: state.options,
      maxPx: 200,
      mock: ctx.isMock,
      thumbs: file.thumbs,
    });

    const thumb = h('span', { class: 'page-thumb' });
    if (thumbUrl) {
      const img = h('img', {
        class: 'page-thumb-img',
        src: thumbUrl,
        alt: '',
        loading: 'lazy',
        decoding: 'async',
      });
      img.addEventListener('error', () => {
        img.replaceWith(h('span', { class: 'page-thumb-fallback' }, icon('fileText', 16)));
      });
      thumb.append(img);
    } else {
      thumb.append(h('span', { class: 'page-thumb-fallback' }, icon('fileText', 16)));
    }

    return h(
      'label',
      { class: `page-row${checked ? '' : ' is-unchecked'}`, dataset: { key } },
      input,
      thumb,
      h(
        'span',
        { class: 'page-info' },
        h('span', { class: 'page-name', text: `第 ${page + 1} 页` }),
        h('span', { class: 'page-file', text: file.name })
      )
    );
  }

  function fileBlock(file) {
    const pages = filePages(file);
    const selected = selectedPagesOf(file);

    const toggleBtn = h('button', {
      class: 'batch-toggle',
      type: 'button',
      text: selected >= pages ? '取消本文件' : '选择本文件',
      onclick: () => toggleFile(file),
    });

    const rows = h('div', { class: 'batch-pages' });
    for (let page = 0; page < pages; page += 1) rows.append(pageRow(file, page));

    return h(
      'div',
      { class: 'batch-file', dataset: { token: file.token } },
      h(
        'div',
        { class: 'batch-file-head' },
        h(
          'span',
          { class: `job-icon job-icon-${file.kind === 'pdf' ? 'print' : 'scan'}` },
          icon(file.kind === 'pdf' ? 'fileText' : 'image', 18)
        ),
        h(
          'span',
          { class: 'batch-file-text' },
          h('span', { class: 'batch-file-name', text: file.name, title: file.name }),
          h('span', {
            class: 'batch-file-meta',
            text: `${file.kind === 'pdf' ? 'PDF' : '图片'} · ${fmt.pages(pages)} · ${fmt.bytes(file.size)}`,
          })
        ),
        h('div', { class: 'batch-file-actions' }, toggleBtn, iconButton({
          icon: 'close',
          label: `移除 ${file.name}`,
          size: 18,
          onclick: () => removeFile(file),
        }))
      ),
      rows
    );
  }

  function renderList() {
    listSlot.replaceChildren();
    if (!state.files.length) {
      listSlot.append(
        emptyState({
          icon: 'upload',
          title: '还没有选择文件',
          description: '拖入文件或点击上方按钮，支持 PDF 与图片混合批量打印。',
        })
      );
      return;
    }
    state.files.forEach((file) => listSlot.append(fileBlock(file)));
  }

  /** 选项变化后就地刷新缩略图，避免整表重建导致闪烁 */
  function refreshThumbs() {
    listSlot.querySelectorAll('.batch-file').forEach((block) => {
      const file = state.files.find((item) => item.token === block.dataset.token);
      if (!file) return;
      block.querySelectorAll('.page-row').forEach((row) => {
        const page = Number(String(row.dataset.key || '').split(KEY_SEP)[1]);
        if (!Number.isFinite(page)) return;
        const img = row.querySelector('.page-thumb-img');
        if (!img) return;
        const url = previewUrl({
          token: file.token,
          page,
          options: state.options,
          maxPx: 200,
          mock: ctx.isMock,
          thumbs: file.thumbs,
        });
        if (url && img.getAttribute('src') !== url) img.src = url;
      });
    });
  }

  /* ---------------------------------------------------------------- 选择 */

  function selectAll() {
    state.selected.clear();
    state.files.forEach((file) => {
      const pages = filePages(file);
      for (let page = 0; page < pages; page += 1) state.selected.add(`${file.token}${KEY_SEP}${page}`);
    });
    // 只同步勾选状态，不重建列表：重建会让每一页的缩略图重新请求一次。
    paint();
  }

  function selectNone() {
    state.selected.clear();
    paint();
  }

  function selectParity(parity) {
    state.selected.clear();
    state.files.forEach((file) => {
      const pages = filePages(file);
      for (let page = 0; page < pages; page += 1) {
        if ((page + 1) % 2 === parity) state.selected.add(`${file.token}${KEY_SEP}${page}`);
      }
    });
    paint();
  }

  function toggleFile(file) {
    const pages = filePages(file);
    const allSelected = selectedPagesOf(file) >= pages;
    for (let page = 0; page < pages; page += 1) {
      const key = `${file.token}${KEY_SEP}${page}`;
      if (allSelected) state.selected.delete(key);
      else state.selected.add(key);
    }
    paint();
    paint();
  }

  function removeFile(file) {
    state.files = state.files.filter((item) => item.token !== file.token);
    const prefix = `${file.token}${KEY_SEP}`;
    Array.from(state.selected).forEach((key) => {
      if (key.startsWith(prefix)) state.selected.delete(key);
    });
    renderList();
    paint();
  }

  /* ---------------------------------------------------------------- 上传 */

  async function handleFiles(fileListLike) {
    const incoming = Array.from(fileListLike || []);
    if (!incoming.length) return;
    const supported = incoming.filter(isSupportedFile);
    if (!supported.length) {
      ctx.toast('没有可用的文件，请选择 PDF 或图片', { tone: 'error' });
      return;
    }
    if (supported.length !== incoming.length) {
      ctx.toast(`已忽略 ${incoming.length - supported.length} 个不支持的文件`, { tone: 'warning' });
    }

    state.uploading = true;
    paint();

    try {
      const data = await ctx.api.upload(supported);
      const uploaded = Array.isArray(data.files) ? data.files : [];
      uploaded.forEach((file) => {
        state.files.push(file);
        const pages = filePages(file);
        for (let page = 0; page < pages; page += 1) {
          state.selected.add(`${file.token}${KEY_SEP}${page}`);
        }
      });
      renderList();
      paint();
      ctx.toast(`已添加 ${uploaded.length} 个文件`, { tone: 'success' });
    } catch (err) {
      ctx.toast(err.message || '上传失败', { tone: 'error', duration: 6000 });
    } finally {
      state.uploading = false;
      paint();
    }
  }

  /* ---------------------------------------------------------------- 状态 */

  function canSubmit() {
    const printer = ctx.state.printer;
    return Boolean(
      state.files.length &&
        state.selected.size &&
        !state.uploading &&
        !state.busy &&
        printer &&
        printer.online
    );
  }

  function paint() {
    const total = totalPages();
    const selected = state.selected.size;
    const copies = state.options.copies;

    countChip.firstElementChild.textContent = `${selected} / ${total} 页`;
    sumSelected.textContent = `${selected} / ${total} 页`;
    sumCopies.textContent = `${copies} 份`;
    sumTotal.textContent = `${selected * copies} 页`;

    const hasFiles = state.files.length > 0;
    [selectAllBtn, selectNoneBtn, oddBtn, evenBtn].forEach((btn) => {
      btn.disabled = !hasFiles;
    });
    clearAllBtn.hidden = !hasFiles;

    uploadNotice.hidden = !state.uploading;
    if (state.uploading) {
      uploadNotice.replaceChildren(spinner(18, '正在上传'), h('span', { text: '正在上传文件并解析页数…' }));
    }

    listSlot.querySelectorAll('.page-row').forEach((row) => {
      const key = row.dataset.key;
      const input = row.querySelector('.page-check');
      const on = state.selected.has(key);
      if (input) input.checked = on;
      row.classList.toggle('is-unchecked', !on);
    });

    listSlot.querySelectorAll('.batch-file').forEach((block) => {
      const file = state.files.find((item) => item.token === block.dataset.token);
      if (!file) return;
      const toggle = block.querySelector('.batch-toggle');
      if (toggle) {
        toggle.textContent = selectedPagesOf(file) >= filePages(file) ? '取消本文件' : '选择本文件';
      }
      block.classList.toggle('is-empty-selection', selectedPagesOf(file) === 0);
    });

    if (typeof onChange === 'function') onChange();
  }

  /* ---------------------------------------------------------------- 提交 */

  function summary() {
    const total = totalPages();
    const selected = state.selected.size;
    if (!state.files.length) {
      return { title: '尚未选择文件', sub: '添加文件后逐页勾选，即可一次提交批量打印' };
    }
    return {
      title: `已选 ${selected} / ${total} 页`,
      sub: `预计 ${selected * state.options.copies} 页 · ${describeOptions(state.options)}`,
    };
  }

  async function submit() {
    if (!state.files.length) throw new Error('请先添加要打印的文件');
    if (!state.selected.size) throw new Error('请至少勾选一页');
    const printer = ctx.state.printer;
    if (!printer) throw new Error('尚未注册打印机');
    if (!printer.online) throw new Error('打印机当前离线，无法提交打印');

    const groups = new Map();
    state.selected.forEach((key) => {
      const [token, page] = key.split(KEY_SEP);
      if (!groups.has(token)) groups.set(token, []);
      groups.get(token).push(Number(page));
    });

    const jobIds = [];
    const submittedTokens = [];
    for (const [token, pages] of groups) {
      try {
        const result = await ctx.api.print({
          printer_id: printer.id,
          files: [token],
          options: {
            copies: state.options.copies,
            color: state.options.color,
            quality: state.options.quality,
            dpi: state.options.dpi,
            media: state.options.media,
            scale: state.options.scale,
            pages: compressPages(pages),
            orientation: state.options.orientation,
          },
        });
        jobIds.push(result.job_id);
        submittedTokens.push({ token, pages });
      } catch (err) {
        if (jobIds.length) {
          // 已经提交成功的分组必须从勾选里移除，否则用户重试会把它们再打一遍。
          submittedTokens.forEach((done) => {
            done.pages.forEach((page) => state.selected.delete(`${done.token}${KEY_SEP}${page}`));
          });
          renderList();
          paint();
          const partial = new Error(
            `已提交 ${jobIds.length} 个作业（#${jobIds.join('、')}），后续提交失败：${err.message}。已成功的分组已从勾选移除，重试只会提交剩余部分。`
          );
          partial.jobIds = jobIds;
          throw partial;
        }
        throw err;
      }
    }

    return { jobIds };
  }

  function reset() {
    state.files = [];
    state.selected.clear();
    state.uploading = false;
    state.busy = false;
    optionsPanel.reset();
    renderList();
    drop.setBusy(false);
    paint();
  }

  function setBusy(busy) {
    state.busy = Boolean(busy);
    drop.setBusy(busy);
    paint();
  }

  function destroy() {
    optionsPanel.destroy();
  }

  renderList();
  paint();

  return {
    el,
    canSubmit,
    submitLabel: () => (state.selected.size ? `打印 ${state.selected.size} 页` : '打印'),
    summary,
    hasContent: () => state.files.length > 0,
    submit,
    reset,
    setBusy,
    destroy,
  };
}
