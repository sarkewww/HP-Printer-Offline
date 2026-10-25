/**
 * views/scan.js — 扫描：参数面板、预览画布、扫描动画、最近扫描
 */

import {
  h,
  icon,
  button,
  segmented,
  selectField,
  slider,
  switchControl,
  textField,
  fmt,
  openDialog,
} from '../components/ui.js';
import { emptyState, banner, spinner } from '../components/feedback.js';

export const title = '扫描';
export const subtitle = (state) =>
  state.printer ? `使用 ${state.printer.model || state.printer.name} 的扫描单元` : '尚未注册打印机';

const COLOR_MODES = [
  { value: 'RGB24', label: '彩色' },
  { value: 'Grayscale8', label: '灰度' },
  { value: 'BlackAndWhite1', label: '黑白' },
];

const INTENTS = [
  { value: 'Document', label: '文档' },
  { value: 'Photo', label: '照片' },
  { value: 'TextAndGraphic', label: '图文混合' },
];

const ACTIVE_STATES = new Set(['queued', 'preparing', 'sending', 'printing']);

export async function mount(root, ctx) {
  const { api, state, bus, toast } = ctx;

  const capabilities = (state.status && state.status.capabilities) || {};
  const maxDpi = Number(capabilities.max_scan_dpi) || 1200;
  const dpiOptions = [75, 150, 300, 600, 1200].filter((dpi) => dpi <= maxDpi);
  if (!dpiOptions.length) dpiOptions.push(300);

  const availableColors = Array.isArray(capabilities.scan_color_modes) && capabilities.scan_color_modes.length
    ? COLOR_MODES.filter((mode) => capabilities.scan_color_modes.includes(mode.value))
    : COLOR_MODES;
  const colorOptions = availableColors.length ? availableColors : COLOR_MODES;

  const formats = Array.isArray(capabilities.scan_formats) ? capabilities.scan_formats : ['image/jpeg', 'application/pdf'];
  const canPdf = formats.includes('application/pdf');

  const options = {
    color_mode: colorOptions[0].value,
    dpi: dpiOptions.includes(300) ? 300 : dpiOptions[dpiOptions.length - 1],
    format: 'jpeg',
    intent: 'Document',
    brightness: 1000,
    contrast: 1000,
    auto_crop: true,
  };

  let scans = [];
  let currentScan = null;
  let scanJob = null;
  let scansError = '';

  /* ------------------------------------------------------------------ 结构 */

  const bannerSlot = h('div');
  const stage = h('div', { class: 'preview-stage' });
  const toolbarMeta = h('span', { class: 'preview-toolbar-meta', text: '—' });
  const fileMeta = h('span', { class: 'preview-filemeta', text: '尚无扫描件' });
  const scanBtn = button({
    label: '开始扫描',
    icon: 'scan',
    variant: 'filled',
    class: 'btn-block',
    onclick: startScan,
  });
  const saveBtn = button({ label: '另存为', icon: 'download', variant: 'tonal', size: 'sm', onclick: saveAs });
  const revealBtn = button({ label: '打开文件夹', icon: 'folder', variant: 'text', size: 'sm', onclick: reveal });
  const rescanBtn = button({ label: '重新扫描', icon: 'refresh', variant: 'text', size: 'sm', onclick: startScan });
  const recentStrip = h('div', { class: 'scan-recent' });

  const optionsCard = h('aside', { class: 'card scan-options', 'aria-label': '扫描选项' });
  // PDF 密码：只有选了 PDF 才显示（JPEG 加密没有意义）
  const pdfPasswordField = textField({
    label: 'PDF 密码',
    placeholder: '留空则不加密',
    value: options.pdf_password || '',
    type: 'password',
    hint: '加密在本地完成，密码不会离开这台电脑',
    // textField 的 oninput 直接挂在原生 input 上，收到的是原生事件
    oninput: (event) => {
      options.pdf_password = event.target.value;
    },
  });
  pdfPasswordField.hidden = options.format !== 'pdf';
  optionsCard.append(
    h('h2', { class: 'section-title', text: '扫描选项' }),
    h('span', { class: 'option-label', text: '色彩模式' }),
    segmented({
      options: colorOptions,
      value: options.color_mode,
      ariaLabel: '色彩模式',
      onchange: (value) => {
        options.color_mode = value;
        paintMeta();
      },
    }),
    selectField({
      label: '扫描分辨率',
      options: dpiOptions.map((dpi) => ({ value: dpi, label: `${dpi} dpi` })),
      value: options.dpi,
      onchange: (event) => {
        options.dpi = Number(event.target.value);
        paintMeta();
      },
    }),
    h('span', { class: 'option-label', text: '文件格式' }),
    segmented({
      options: [
        { value: 'jpeg', label: 'JPEG' },
        ...(canPdf ? [{ value: 'pdf', label: 'PDF' }] : []),
      ],
      value: options.format,
      ariaLabel: '文件格式',
      onchange: (value) => {
        options.format = value;
        // PDF 密码只在 PDF 下才有意义；切回 JPEG 时 model 与输入框的显示值都要清空，
        // 否则再次切到 PDF 会看到旧密码仍留在框里（但实际已不会被提交）。
        pdfPasswordField.hidden = value !== 'pdf';
        if (value !== 'pdf') {
          options.pdf_password = '';
          pdfPasswordField.input.value = '';
        }
        paintMeta();
      },
    }),
    selectField({
      label: '扫描意图',
      options: INTENTS,
      value: options.intent,
      onchange: (event) => {
        options.intent = event.target.value;
      },
    }),
    slider({
      label: '亮度',
      min: 500,
      max: 1500,
      step: 50,
      value: options.brightness,
      format: (value) => `${Math.round((value / 1000) * 100)}%`,
      oninput: (value) => {
        options.brightness = value;
      },
    }),
    slider({
      label: '对比度',
      min: 500,
      max: 1500,
      step: 50,
      value: options.contrast,
      format: (value) => `${Math.round((value / 1000) * 100)}%`,
      oninput: (value) => {
        options.contrast = value;
      },
    }),
    switchControl({
      label: '自动裁切',
      description: '去除页面四周的白边',
      checked: options.auto_crop,
      onchange: (value) => {
        options.auto_crop = value;
      },
    }),
    switchControl({
      label: '自动纠偏',
      description: '把歪斜的页面转正（本地检测倾角）',
      checked: !!options.auto_orient,
      onchange: (value) => {
        options.auto_orient = value;
      },
    }),
    switchControl({
      label: '自动增强',
      description: '去噪、提升对比度、轻度锐化',
      checked: !!options.auto_enhance,
      onchange: (value) => {
        options.auto_enhance = value;
      },
    }),
    switchControl({
      label: 'OCR 文字层',
      description: '本地识别文字，生成可搜索 PDF（不经云端）',
      checked: !!options.ocr,
      onchange: (value) => {
        options.ocr = value;
      },
    }),
    pdfPasswordField,
    scanBtn
  );

  const previewCard = h(
    'section',
    { class: 'card scan-preview-card', 'aria-label': '扫描预览' },
    h(
      'div',
      { class: 'preview-toolbar' },
      h('span', { class: 'preview-toolbar-title' }, icon('image', 18), h('span', { text: '预览' })),
      toolbarMeta
    ),
    stage,
    h(
      'div',
      { class: 'preview-footer' },
      h('div', { class: 'preview-actions' }, saveBtn, revealBtn, rescanBtn),
      fileMeta
    ),
    recentStrip
  );

  root.append(h('div', { class: 'scan-grid' }, optionsCard, h('div', { class: 'scan-preview-col' }, bannerSlot, previewCard)));

  /* --------------------------------------------------------------- 渲染 */

  function paintBanner() {
    bannerSlot.replaceChildren();
    if (!state.apiOnline) return;
    if (!state.printer) {
      bannerSlot.append(
        banner({
          tone: 'info',
          icon: 'scan',
          title: '尚未注册打印机',
          message: '扫描需要先注册一台支持 eSCL 的局域网打印机。',
          action: button({ label: '去注册', variant: 'text', icon: 'arrowRight', onclick: () => ctx.navigate('printer') }),
        })
      );
    } else if (!state.printer.online) {
      bannerSlot.append(
        banner({
          tone: 'warning',
          icon: 'warning',
          title: '打印机当前离线',
          message: '扫描单元不可用，连接恢复后可重新扫描。',
          action: button({
            label: '重试',
            icon: 'refresh',
            variant: 'text',
            onclick: () => ctx.refreshStatus({ silent: false }),
          }),
        })
      );
    } else if (capabilities.scan === false) {
      bannerSlot.append(
        banner({
          tone: 'warning',
          icon: 'info',
          title: '此设备不支持扫描',
          message: '后端未检测到 eSCL 扫描能力。',
        })
      );
    }
  }

  function paintStage() {
    stage.replaceChildren();

    if (scanJob && ACTIVE_STATES.has(scanJob.state)) {
      const progress = Math.round((Number(scanJob.progress) || 0) * 100);
      stage.append(
        h(
          'div',
          { class: 'scan-overlay' },
          h('span', { class: 'scan-line' }),
          spinner(30, '正在扫描'),
          h('span', { class: 'scan-overlay-text', text: scanJob.message || '正在扫描…' }),
          h('span', { class: 'scan-overlay-progress', text: `${progress}%` })
        )
      );
      return;
    }

    if (!currentScan) {
      if (scansError) {
        stage.append(
          emptyState({
            icon: 'warning',
            title: '无法读取扫描记录',
            description: scansError,
            tone: 'error',
            action: button({ label: '重试', icon: 'refresh', variant: 'tonal', onclick: () => loadScans() }),
          })
        );
        return;
      }
      stage.append(
        h(
          'div',
          { class: 'scan-empty' },
          h('div', { class: 'empty-icon' }, icon('scan', 28)),
          h('p', { class: 'empty-title', text: '尚无扫描件' }),
          h('p', { class: 'empty-desc', text: '在左侧设置参数，然后点击「开始扫描」。' })
        )
      );
      return;
    }

    const isPdf = currentScan.format === 'pdf';
    const src = isPdf
      ? ctx.assetUrl(currentScan.thumb || `/api/scans/${currentScan.id}/thumb`)
      : currentScan.file || ctx.assetUrl(`/api/scans/${currentScan.id}/file`);

    const image = h('img', {
      class: 'preview-page',
      src,
      alt: `扫描件预览：${baseName(currentScan.path) || '未命名'}`,
    });
    image.addEventListener('error', () => {
      stage.replaceChildren(
        emptyState({
          icon: 'image',
          title: '无法加载预览',
          description: '文件可能已被移动或删除，可尝试重新扫描。',
          tone: 'error',
        })
      );
    });
    stage.append(image);
  }

  function paintFooter() {
    const hasScan = Boolean(currentScan);
    saveBtn.disabled = !hasScan || Boolean(scanJob && ACTIVE_STATES.has(scanJob.state));
    revealBtn.disabled = !hasScan;
    rescanBtn.disabled = Boolean(scanJob && ACTIVE_STATES.has(scanJob.state));

    if (!currentScan) {
      fileMeta.textContent = '尚无扫描件';
      return;
    }

    const dims =
      currentScan.width && currentScan.height
        ? `${fmt.number(currentScan.width)} × ${fmt.number(currentScan.height)} px`
        : '';
    fileMeta.textContent = [dims, fmt.bytes(currentScan.size), fmt.dateTime(currentScan.created_at)]
      .filter(Boolean)
      .join(' · ');
    fileMeta.title = currentScan.path || '';
  }

  function paintMeta() {
    toolbarMeta.textContent = `${options.dpi} dpi · ${options.format.toUpperCase()} · ${
      colorOptions.find((item) => item.value === options.color_mode)?.label || '彩色'
    }`;
  }

  function paintRecent() {
    recentStrip.replaceChildren();
    if (!scans.length) {
      recentStrip.hidden = true;
      return;
    }
    recentStrip.hidden = false;
    recentStrip.append(h('span', { class: 'scan-recent-label', text: '最近' }));
    scans.slice(0, 8).forEach((scan) => {
      const btn = h('button', {
        class: 'scan-thumb-btn',
        type: 'button',
        'aria-pressed': String(Boolean(currentScan && currentScan.id === scan.id)),
        'aria-label': `预览 ${fmt.dateTime(scan.created_at)} 的扫描件`,
        title: scan.path || '',
        onclick: () => {
          currentScan = scan;
          paintStage();
          paintFooter();
          paintRecent();
        },
      });
      btn.append(
        h('img', {
          src: ctx.assetUrl(scan.thumb || `/api/scans/${scan.id}/thumb`),
          alt: '',
          loading: 'lazy',
        })
      );
      recentStrip.append(btn);
    });
  }

  function paintAll() {
    paintBanner();
    paintMeta();
    paintStage();
    paintFooter();
    paintRecent();
    updateScanButton();
  }

  function updateScanButton() {
    const busy = Boolean(scanJob && ACTIVE_STATES.has(scanJob.state));
    const enabled = Boolean(state.printer && state.printer.online && capabilities.scan !== false && !busy);
    scanBtn.disabled = !enabled;
    scanBtn.replaceChildren(
      icon('scan', 19),
      h('span', { class: 'btn-label', text: busy ? '正在扫描…' : '开始扫描' })
    );
  }

  /* --------------------------------------------------------------- 行为 */

  async function loadScans({ silent = false } = {}) {
    try {
      const data = await api.scans(20);
      scans = Array.isArray(data.scans) ? data.scans : [];
      scansError = '';
      if (!currentScan && scans.length) currentScan = scans[0];
      paintAll();
    } catch (err) {
      scansError = err.message;
      if (!silent) toast(err.message, { tone: 'error' });
      paintStage();
      paintRecent();
    }
  }

  async function startScan() {
    if (!state.printer || !state.printer.online) {
      toast('打印机离线，无法开始扫描', { tone: 'error' });
      return;
    }
    if (scanJob && ACTIVE_STATES.has(scanJob.state)) return;

    scanJob = {
      id: null,
      state: 'queued',
      progress: 0,
      message: '正在连接扫描单元',
      pages_total: 1,
    };
    paintStage();
    paintFooter();
    updateScanButton();

    try {
      const result = await api.scan({
        printer_id: state.printer.id,
        options: {
          color_mode: options.color_mode,
          dpi: options.dpi,
          format: options.format,
          intent: options.intent,
          brightness: options.brightness,
          contrast: options.contrast,
          auto_crop: options.auto_crop,
          auto_orient: Boolean(options.auto_orient),
          auto_enhance: Boolean(options.auto_enhance),
          ocr: Boolean(options.ocr),
          // 密码只在 PDF 下提交，避免 JPEG 扫描把无用密码写进任务记录
          ...(options.format === 'pdf' && options.pdf_password
            ? { pdf_password: options.pdf_password }
            : {}),
        },
      });
      scanJob = { ...scanJob, id: result.job_id };
      toast('扫描任务已开始', { tone: 'success' });
      // 防止作业在响应返回前就已结束而错过 SSE 事件
      checkJobOnce(result.job_id);
    } catch (err) {
      scanJob = null;
      paintStage();
      paintFooter();
      updateScanButton();
      toast(err.message, { tone: 'error', duration: 6000 });
    }
  }

  async function checkJobOnce(jobId) {
    try {
      const job = await api.job(jobId);
      if (!scanJob || scanJob.id !== jobId) return;
      scanJob = { ...scanJob, ...job };
      handleJobState(job);
    } catch {
      /* 忽略：以 SSE 事件为准 */
    }
  }

  function handleJobState(job) {
    if (!scanJob || (scanJob.id && job.id !== scanJob.id)) return;
    const wasActive = ACTIVE_STATES.has(scanJob.state);
    scanJob = { ...scanJob, ...job };
    paintStage();
    paintFooter();
    updateScanButton();

    if (!wasActive) return;

    if (job.state === 'done') {
      onScanDone(job);
    } else if (job.state === 'error' || job.state === 'canceled') {
      toast(job.message || (job.state === 'canceled' ? '扫描已取消' : '扫描失败'), {
        tone: job.state === 'error' ? 'error' : 'default',
        duration: 6000,
      });
      setTimeout(() => {
        if (scanJob && scanJob.id === job.id) {
          scanJob = null;
          paintStage();
          updateScanButton();
        }
      }, 1200);
    }
  }

  async function onScanDone(job) {
    try {
      const data = await api.scans(20);
      scans = Array.isArray(data.scans) ? data.scans : [];
      const found = scans.find((item) => item.job_id === job.id) || scans[0] || null;
      if (found) {
        currentScan = found;
        toast('扫描完成，文件已保存到本机', { tone: 'success' });
      } else {
        toast('扫描完成，但未找到输出文件', { tone: 'error' });
      }
      paintAll();
    } catch (err) {
      toast(`扫描完成，读取结果失败：${err.message}`, { tone: 'error', duration: 6000 });
    } finally {
      setTimeout(() => {
        if (scanJob && scanJob.id === job.id) {
          scanJob = null;
          paintStage();
          paintFooter();
          updateScanButton();
        }
      }, 1500);
      ctx.refreshStatus({ silent: true });
    }
  }

  function saveAs() {
    if (!currentScan) return;
    const href = currentScan.file || ctx.assetUrl(`/api/scans/${currentScan.id}/file`);
    const name = baseName(currentScan.path) || `scan_${currentScan.id}.${currentScan.format === 'pdf' ? 'pdf' : 'jpg'}`;
    const link = h('a', { href, download: name, class: 'visually-hidden' });
    document.body.append(link);
    link.click();
    setTimeout(() => link.remove(), 1000);
    toast(`已开始下载 ${name}`, { tone: 'success' });
  }

  async function reveal() {
    if (!currentScan || !currentScan.path) {
      toast('该扫描记录没有文件路径', { tone: 'error' });
      return;
    }
    try {
      await navigator.clipboard.writeText(currentScan.path);
      toast('已复制文件路径，可在资源管理器中打开', { tone: 'success' });
    } catch {
      let dialog = null;
      dialog = openDialog({
        title: '文件位置',
        body: h(
          'div',
          {},
          h('p', { class: 'dialog-text', text: '复制下面的路径，在资源管理器中打开：' }),
          h('p', { class: 'mono', style: { marginTop: '12px', wordBreak: 'break-all' }, text: currentScan.path })
        ),
        actions: [button({ label: '关闭', variant: 'text', onclick: () => dialog.close() })],
      });
    }
  }

  const offJob = bus.on('job', (job) => {
    if (!scanJob || job.id !== scanJob.id) return;
    handleJobState(job);
  });
  const offPrinters = bus.on('printers', () => {
    paintBanner();
    updateScanButton();
  });
  const offStatus = bus.on('status', () => {
    paintBanner();
    updateScanButton();
  });
  const offRefresh = bus.on('refresh', () => loadScans({ silent: true }));

  paintAll();
  loadScans({ silent: true });

  return () => {
    offJob();
    offPrinters();
    offStatus();
    offRefresh();
  };
}

function baseName(path) {
  if (!path) return '';
  const parts = String(path).split(/[\\/]/);
  return parts[parts.length - 1] || '';
}
