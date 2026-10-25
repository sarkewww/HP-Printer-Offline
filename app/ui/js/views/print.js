/**
 * views/print.js — 打印视图编排层
 *
 * 结构：
 *   - 模式切换（单张 / 批量）
 *   - 打印机状态横幅
 *   - 当前模式的工作区（views/print/single.js | batch.js）
 *   - 最近打印（最近 3 个打印作业 + 实时进度）
 *   - 底部操作栏（唯一的提交入口，统一处理 loading / 成功 / 失败）
 */

import { h, icon, button, segmented, stateChip, progressBar, fmt } from '../components/ui.js';
import { banner, emptyState, errorState, skeletonRows } from '../components/feedback.js';
import { createSingleMode } from './print/single.js';
import { createBatchMode } from './print/batch.js';
import { ACTIVE_STATES } from './print/shared.js';

export const title = '打印';
export const subtitle = (state) =>
  state.printer ? `发送至 ${state.printer.model || state.printer.name}` : '尚未注册打印机';

const MODES = [
  { value: 'single', label: '单张打印' },
  { value: 'batch', label: '批量打印' },
];

const MODE_HINT = {
  single: '一次打印一张图片或 PDF，支持逐页预览与图片编辑。',
  batch: '混合多个文件，逐页勾选后一次提交，适合成套资料。',
};

export async function mount(root, ctx) {
  let mode = 'single';
  let submitting = false;
  let destroyed = false;
  let recent = [];
  let recentLoading = true;
  let recentError = '';

  const controllers = {};
  root.classList.add('has-actionbar');

  /* ---------------------------------------------------------------- 结构 */

  const bannerSlot = h('div', { class: 'banner-slot' });

  const modeSeg = segmented({
    options: MODES,
    value: mode,
    ariaLabel: '打印模式',
    onchange: (value) => setMode(value),
  });

  const modeHint = h('p', { class: 'print-mode-hint', text: MODE_HINT[mode] });

  const modeBar = h(
    'div',
    { class: 'print-modebar' },
    h(
      'div',
      { class: 'print-modebar-text' },
      h('h2', { class: 'print-modebar-title', text: '打印方式' }),
      modeHint
    ),
    modeSeg
  );

  const modeSlot = h('div', { class: 'print-mode-slot' });
  const recentSlot = h('div', { class: 'recent-print-slot' });

  const barTitle = h('span', { class: 'action-bar-title', text: '尚未选择文件' });
  const barSub = h('span', { class: 'action-bar-sub', text: '' });

  const clearBtn = button({
    label: '清空',
    variant: 'text',
    size: 'sm',
    icon: 'trash',
    onclick: () => {
      const active = controllers[mode];
      if (active && typeof active.reset === 'function') active.reset();
    },
  });

  const printBtn = button({
    label: '打印',
    icon: 'print',
    variant: 'filled',
    onclick: submit,
  });

  const actionBar = h(
    'div',
    { class: 'action-bar', role: 'region', 'aria-label': '打印操作' },
    h('div', { class: 'action-bar-info' }, barTitle, barSub),
    h('div', { class: 'action-bar-actions' }, clearBtn, printBtn)
  );

  root.append(
    h('div', { class: 'print-page' }, bannerSlot, modeBar, modeSlot, recentSlot),
    actionBar
  );

  /* ---------------------------------------------------------------- 模式 */

  function ensureController(name) {
    if (controllers[name]) return controllers[name];
    const factory = name === 'single' ? createSingleMode : createBatchMode;
    const controller = factory({ ctx, onChange: paint });
    controller.el.hidden = name !== mode;
    controllers[name] = controller;
    modeSlot.append(controller.el);
    return controller;
  }

  function setMode(next) {
    if (next === mode) return;
    mode = next;
    modeSeg.setValue(next);
    modeHint.textContent = MODE_HINT[next];
    ensureController(next);
    Object.entries(controllers).forEach(([name, controller]) => {
      controller.el.hidden = name !== next;
    });
    paint();
  }

  /* ---------------------------------------------------------------- 横幅 */

  function paintBanner() {
    bannerSlot.replaceChildren();
    if (!ctx.state.apiOnline) return;
    if (!ctx.state.printer) {
      bannerSlot.append(
        banner({
          tone: 'info',
          icon: 'print',
          title: '尚未注册打印机',
          message: '先注册局域网打印机，才能提交打印作业。',
          action: button({
            label: '去注册',
            variant: 'text',
            icon: 'arrowRight',
            onclick: () => ctx.navigate('printer'),
          }),
        })
      );
    } else if (!ctx.state.printer.online) {
      bannerSlot.append(
        banner({
          tone: 'warning',
          icon: 'warning',
          title: '打印机当前离线',
          message: '作业无法提交。请检查设备电源与网络后重试。',
          action: button({
            label: '重试',
            icon: 'refresh',
            variant: 'text',
            onclick: () => ctx.refreshStatus({ silent: false }),
          }),
        })
      );
    }
  }

  /* ------------------------------------------------------------ 操作栏 */

  function paint() {
    if (destroyed) return;
    const active = controllers[mode];
    if (!active) return;

    const summary = active.summary();
    barTitle.textContent = summary.title;
    barSub.textContent = summary.sub;

    const canPrint = active.canSubmit() && !submitting;
    printBtn.disabled = !canPrint;
    printBtn.replaceChildren(
      submitting ? h('span', { class: 'spinner', style: { width: '18px', height: '18px' }, 'aria-hidden': 'true' }) : icon('print', 19),
      h('span', { class: 'btn-label', text: submitting ? '正在提交…' : active.submitLabel() })
    );
    clearBtn.hidden = !active.hasContent() || submitting;
  }

  async function submit() {
    const active = controllers[mode];
    if (!active || submitting || !active.canSubmit()) return;

    submitting = true;
    if (typeof active.setBusy === 'function') active.setBusy(true);
    paint();

    try {
      const result = await active.submit();
      const ids = result && Array.isArray(result.jobIds) ? result.jobIds : [];
      const message = ids.length > 1
        ? `已提交 ${ids.length} 个打印作业：${ids.map((id) => `#${id}`).join('、')}`
        : `已提交打印作业 #${ids[0] ?? '—'}`;
      ctx.toast(message, { tone: 'success', duration: 6000 });

      // 成功后才清空；两个模式都恢复到初始状态，避免残留旧文件
      Object.values(controllers).forEach((controller) => {
        if (controller && typeof controller.reset === 'function') controller.reset();
      });
      ctx.refreshStatus({ silent: true });
      ctx.navigate('tasks');
    } catch (err) {
      // 失败时保留用户已选文件与选项，仅提示后端返回的信息
      ctx.toast(err.message || '打印提交失败', { tone: 'error', duration: 6000 });
    } finally {
      submitting = false;
      if (!destroyed) {
        if (active && typeof active.setBusy === 'function') active.setBusy(false);
        paint();
      }
    }
  }

  /* ---------------------------------------------------------- 最近打印 */

  function recentRow(job) {
    const active = ACTIVE_STATES.has(job.state);
    const pct = Math.round((Number(job.progress) || 0) * 100);
    return h(
      'div',
      { class: 'recent-row' },
      h('span', { class: `job-icon job-icon-${job.kind || 'print'}` }, icon('print', 18)),
      h(
        'div',
        { class: 'recent-main' },
        h(
          'div',
          { class: 'recent-line' },
          h('span', { class: 'recent-title', text: job.title || '打印作业', title: job.title || '' }),
          stateChip(job.state, { kind: 'print' })
        ),
        h(
          'div',
          { class: 'recent-meta' },
          h('span', { text: `${fmt.pages(job.pages_total)} · ${fmt.relative(job.created_at)}` }),
          active ? h('span', { class: 'recent-pct', text: `${pct}%` }) : null
        ),
        active ? progressBar(job.progress || 0, { label: '打印进度' }) : null
      )
    );
  }

  function paintRecent() {
    const body = h('div', { class: 'recent-body' });

    if (recentLoading) {
      body.append(h('div', { class: 'recent-loading' }, skeletonRows(3)));
    } else if (recentError) {
      body.append(
        errorState({
          title: '无法读取最近打印',
          message: recentError,
          retry: loadRecent,
        })
      );
    } else if (!recent.length) {
      body.append(
        emptyState({
          icon: 'print',
          title: '还没有打印记录',
          description: '提交第一个打印作业后，这里会显示实时进度。',
          action: button({
            label: '刷新',
            icon: 'refresh',
            variant: 'tonal',
            onclick: () => loadRecent(),
          }),
        })
      );
    } else {
      recent.forEach((job) => body.append(recentRow(job)));
    }

    recentSlot.replaceChildren(
      h(
        'section',
        { class: 'card recent-print-card', 'aria-label': '最近打印' },
        h(
          'div',
          { class: 'section-head' },
          h(
            'div',
            { class: 'section-heading' },
            h('h2', { class: 'section-title', text: '最近打印' }),
            h('p', { class: 'section-sub', text: '最近 3 个打印作业的实时状态' })
          ),
          h(
            'div',
            { class: 'section-actions' },
            button({
              label: '查看全部',
              icon: 'arrowRight',
              variant: 'text',
              size: 'sm',
              onclick: () => ctx.navigate('history'),
            })
          )
        ),
        body
      )
    );
  }

  async function loadRecent() {
    recentLoading = true;
    recentError = '';
    paintRecent();
    try {
      const data = await ctx.api.jobs({ limit: 8, kind: 'print' });
      recent = (Array.isArray(data.jobs) ? data.jobs : []).slice(0, 3);
    } catch (err) {
      recentError = err.message || '本地服务未返回数据';
    } finally {
      recentLoading = false;
      paintRecent();
    }
  }

  /* ---------------------------------------------------------------- 事件 */

  const offJob = ctx.bus.on('job', (job) => {
    if (!job || job.kind !== 'print') return;
    const index = recent.findIndex((item) => item.id === job.id);
    if (index >= 0) recent[index] = { ...recent[index], ...job };
    else recent.unshift(job);
    recent = recent.slice(0, 3);
    paintRecent();
  });

  const offJobs = ctx.bus.on('jobs', (list) => {
    if (!Array.isArray(list)) return;
    recent = list.filter((job) => job.kind === 'print').slice(0, 3);
    recentLoading = false;
    recentError = '';
    paintRecent();
  });

  const offPrinters = ctx.bus.on('printers', () => {
    paintBanner();
    paint();
  });
  const offStatus = ctx.bus.on('status', () => paint());

  /* ---------------------------------------------------------------- 启动 */

  ensureController(mode);
  paintBanner();
  paintRecent();
  paint();
  loadRecent();

  return () => {
    destroyed = true;
    offJob();
    offJobs();
    offPrinters();
    offStatus();
    Object.values(controllers).forEach((controller) => {
      if (controller && typeof controller.destroy === 'function') controller.destroy();
    });
    root.classList.remove('has-actionbar');
  };
}
