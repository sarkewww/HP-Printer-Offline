/**
 * views/history.js — 历史：作业筛选、状态、重新打印、删除扫描记录
 */

import { h, button, fmt, confirmDialog, openDialog, segmented } from '../components/ui.js';
import { skeletonRows, emptyState, errorState } from '../components/feedback.js';
import { jobTable } from '../components/jobs.js';

export const title = '历史';
export const subtitle = '本机作业队列 · 所有记录只保存在这台电脑上';

const FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'print', label: '打印' },
  { value: 'scan', label: '扫描' },
];

export async function mount(root, ctx) {
  const { api, state, bus, toast } = ctx;

  let jobs = [];
  let filter = 'all';
  let loading = true;
  let error = '';
  let lastLoadedAt = null;

  const tableSlot = h('div', { class: 'history-body' });
  const summary = h('span', { class: 'history-summary', text: '正在读取作业记录…' });
  const filterBar = h('div', { class: 'filters', role: 'group', 'aria-label': '作业类型筛选' });
  const filterButtons = new Map();

  FILTERS.forEach((item) => {
    const count = h('span', { class: 'filter-count', text: '0' });
    const btn = h(
      'button',
      {
        class: 'filter-chip md-ripple',
        type: 'button',
        'aria-pressed': String(item.value === filter),
        onclick: () => {
          if (filter === item.value) return;
          filter = item.value;
          filterButtons.forEach((node, value) => node.setAttribute('aria-pressed', String(value === filter)));
          renderTable();
        },
      },
      h('span', { text: item.label }),
      count
    );
    filterButtons.set(item.value, btn);
    filterBar.append(btn);
  });

  const card = h(
    'section',
    { class: 'card history-card', 'aria-label': '作业历史' },
    h('div', { class: 'history-toolbar' }, filterBar, summary),
    tableSlot
  );

  root.append(card);

  function counts() {
    return {
      all: jobs.length,
      print: jobs.filter((job) => job.kind === 'print').length,
      scan: jobs.filter((job) => job.kind === 'scan').length,
    };
  }

  function paintCounts() {
    const map = counts();
    filterButtons.forEach((btn, value) => {
      const label = btn.querySelector('.filter-count');
      if (label) label.textContent = fmt.number(map[value] || 0);
    });
  }

  function renderTable() {
    tableSlot.replaceChildren();

    if (loading) {
      tableSlot.append(h('div', { style: { padding: '24px' } }, skeletonRows(5)));
      summary.textContent = '正在读取作业记录…';
      return;
    }

    if (error) {
      tableSlot.append(
        errorState({
          title: '无法读取作业记录',
          message: error,
          retry: load,
        })
      );
      summary.textContent = '读取失败';
      return;
    }

    const visible = filter === 'all' ? jobs : jobs.filter((job) => job.kind === filter);

    summary.textContent = lastLoadedAt
      ? `共 ${fmt.number(visible.length)} 条记录 · 更新于 ${fmt.time(lastLoadedAt)}`
      : `共 ${fmt.number(visible.length)} 条记录`;

    if (!visible.length) {
      tableSlot.append(
        emptyState({
          icon: 'history',
          title: filter === 'all' ? '还没有作业记录' : `没有${filter === 'print' ? '打印' : '扫描'}作业`,
          description: '完成一次打印或扫描后，记录会显示在这里。',
          action: button({
            label: filter === 'scan' ? '去扫描' : '去打印',
            icon: filter === 'scan' ? 'scan' : 'print',
            variant: 'tonal',
            onclick: () => ctx.navigate(filter === 'scan' ? 'scan' : 'print'),
          }),
        })
      );
      return;
    }

    tableSlot.append(jobTable(visible, { onReprint: reprint, onDelete: deleteScan, onCancel: cancelJob, onDetail: showDetails }));
  }

  function showDetails(job) {
    let tab = 'basic';
    const body = h('div', { class: 'job-detail' });
    const tabs = segmented({
      options: [
        { value: 'basic', label: '基础信息' },
        { value: 'advanced', label: '高级参数' },
      ],
      value: tab,
      ariaLabel: '作业详情视图',
      onchange: (value) => {
        tab = value;
        renderBody();
      },
    });
    const options = job.options || {};
    const printer =
      (Array.isArray(state.printers) ? state.printers.find((item) => item.id === job.printer_id) : null) ||
      state.printer ||
      {};
    const stateText = {
      queued: '排队中',
      preparing: '准备中',
      sending: '发送中',
      printing: '打印中',
      paused: '已暂停',
      done: '已完成',
      error: '失败',
      canceled: '已取消',
    }[job.state] || job.state;
    const colorText = { auto: '自动', color: '彩色', monochrome: '黑白' }[options.color] || options.color || '默认';
    const qualityText = { draft: '草稿', normal: '标准', best: '最佳' }[options.quality] || options.quality || '默认';
    const scaleText = { fit: '适应页面', fill: '铺满页面', actual: '原始大小' }[options.scale] || options.scale || '默认';
    const orientationText = { auto: '自动', portrait: '纵向', landscape: '横向' }[options.orientation] || options.orientation || '自动';
    const elapsed = job.updated_at && job.created_at ? `${Math.max(0, job.updated_at - job.created_at)} 秒` : '—';
    const basicRows = [
      ['任务名称', job.title || '未命名任务'],
      ['类型', { print: '打印', scan: '扫描', copy: '复印' }[job.kind] || job.kind],
      ['状态', stateText],
      ['打印机', printer.name || printer.model || job.printer_id || '—'],
      ['页数', `${job.pages_sent || 0} / ${job.pages_total || 0} 页`],
      ['份数', `${options.copies || 1} 份`],
      ['色彩', colorText],
      ['纸张', options.media || '默认纸张'],
      ['质量', qualityText],
      ['缩放', scaleText],
      ['方向', orientationText],
      ['提交时间', fmt.dateTime(job.created_at)],
      ['最后更新', fmt.dateTime(job.updated_at)],
      ['耗时', elapsed],
      ['结果说明', job.message || '—'],
    ];
    const advancedRows = [
      ['作业 ID', `#${job.id}`],
      ['打印机 ID', job.printer_id || '—'],
      ['打印机地址', printer.host || '—'],
      ['IPP 作业 ID', job.ipp_job_id ? `#${job.ipp_job_id}` : '—'],
      ['进度', job.progress != null ? `${Math.round(Number(job.progress) * 100)}%` : '—'],
      ['源文件 token', (job.files || options.tokens || []).join(', ') || '—'],
      ['创建时间戳', String(job.created_at || '—')],
      ['更新时间戳', String(job.updated_at || '—')],
      ['错误详情', job.error || '—'],
      ['完整参数', JSON.stringify(options, null, 2)],
    ];
    function kv(rows) {
      return h(
        'dl',
        { class: 'detail-grid' },
        rows.map(([label, value]) => [
          h('dt', { text: label }),
          h('dd', { text: String(value ?? '—') }),
        ])
      );
    }
    function renderBody() {
      body.replaceChildren(
        h('div', { class: 'detail-tabs' }, tabs),
        h(
          'div',
          { class: `detail-pane${tab === 'advanced' ? ' is-advanced' : ''}` },
          tab === 'basic' ? kv(basicRows) : kv(advancedRows)
        )
      );
    }
    renderBody();
    const dialog = openDialog({
      title: `作业详情 #${job.id}`,
      body,
      actions: [button({ label: '关闭', variant: 'filled', onclick: () => dialog.close() })],
    });
  }
  async function load() {
    loading = true;
    error = '';
    renderTable();
    try {
      const data = await api.jobs({ limit: 100 });
      jobs = Array.isArray(data.jobs) ? data.jobs : [];
      lastLoadedAt = Math.floor(Date.now() / 1000);
      loading = false;
      error = '';
    } catch (err) {
      loading = false;
      error = err.message;
    }
    paintCounts();
    renderTable();
  }

  async function reprint(job) {
    if (!state.printer) {
      toast('尚未注册打印机', { tone: 'error' });
      ctx.navigate('printer');
      return;
    }
    if (!state.printer.online) {
      toast('打印机离线，无法重新提交', { tone: 'error' });
      return;
    }
    const files = Array.isArray(job.files) && job.files.length
      ? job.files
      : (job.options && Array.isArray(job.options.tokens) ? job.options.tokens : []);
    if (!files.length) {
      toast('该作业没有保留源文件，无法重新打印', { tone: 'error' });
      return;
    }
    try {
      await api.print({
        printer_id: state.printer.id,
        files,
        options: {
          copies: 1,
          color: 'auto',
          quality: 'normal',
          dpi: 300,
          media: (state.status && state.status.media && state.status.media.ready) || 'iso_a4_210x297mm',
          scale: 'fit',
          pages: 'all',
          orientation: 'auto',
        },
      });
      toast('已按默认选项重新提交打印', { tone: 'success' });
      ctx.refreshStatus({ silent: true });
    } catch (err) {
      toast(err.message, { tone: 'error', duration: 6000 });
    }
  }

  async function cancelJob(job) {
    try {
      await api.cancelJob(job.id);
      const index = jobs.findIndex((item) => item.id === job.id);
      if (index >= 0) jobs[index] = { ...jobs[index], state: 'canceled', message: '已取消' };
      renderTable();
      toast('已请求取消作业', { tone: 'success' });
    } catch (err) {
      toast(err.message, { tone: 'error', duration: 6000 });
    }
  }

  async function deleteScan(job) {
    const ok = await confirmDialog({
      title: '删除扫描记录？',
      message: '将删除该扫描件及其记录，文件会从保存目录中移除。此操作不可撤销。',
      confirmLabel: '删除',
      danger: true,
    });
    if (!ok) return;

    try {
      const data = await api.scans(100);
      const scan = (Array.isArray(data.scans) ? data.scans : []).find((item) => item.job_id === job.id);
      if (!scan) {
        toast('找不到对应的扫描文件，可能已被删除', { tone: 'error' });
        return;
      }
      await api.deleteScan(scan.id);
      jobs = jobs.filter((item) => item.id !== job.id);
      paintCounts();
      renderTable();
      toast('已删除扫描记录', { tone: 'success' });
    } catch (err) {
      toast(err.message, { tone: 'error', duration: 6000 });
    }
  }

  const offJob = bus.on('job', (job) => {
    const index = jobs.findIndex((item) => item.id === job.id);
    if (index >= 0) jobs[index] = { ...jobs[index], ...job };
    else jobs.unshift(job);
    paintCounts();
    renderTable();
  });
  const offJobs = bus.on('jobs', (list) => {
    if (!Array.isArray(list)) return;
    jobs = list;
    loading = false;
    error = '';
    paintCounts();
    renderTable();
  });
  const offRefresh = bus.on('refresh', load);

  renderTable();
  load();

  return () => {
    offJob();
    offJobs();
    offRefresh();
  };
}
