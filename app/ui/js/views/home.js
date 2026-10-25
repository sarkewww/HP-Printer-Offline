/**
 * views/home.js — 首页：打印机概览、耗材、快捷入口、最近作业
 */

import { h, icon, button, chip, section, stateChip, fmt, segmented, stepper, openDialog } from '../components/ui.js';
import { skeleton, skeletonLines, emptyState, banner, skeletonRows } from '../components/feedback.js';
import { jobRow } from '../components/jobs.js';

export const title = '首页';
export const subtitle = (state) =>
  state.printer ? `${state.printer.model || state.printer.name} · ${state.printer.host || ''}` : '尚未注册打印机';

const SUPPLY_STATE_TEXT = {
  ok: '正常',
  low: '偏低',
  empty: '已空',
  unknown: '未知',
};

// 墨仓式打印机只上报两个物理墨仓（K 与 CMY），但界面上按真实墨色拆成 4 条更好看也更好懂。
const INK_COLORS = {
  K: { label: '黑色', color: '#111317' },
  C: { label: '青色', color: '#00A3E0' },
  M: { label: '品红', color: '#E4007F' },
  Y: { label: '黄色', color: '#FFC61A' },
};

function expandChannels(supplies) {
  const out = [];
  for (const item of supplies) {
    const code = String(item.code || '').toUpperCase();
    if (code.includes('CMY')) {
      for (const key of ['C', 'M', 'Y']) {
        out.push({
          ...item,
          key,
          code: key,
          label: INK_COLORS[key].label,
          color: INK_COLORS[key].color,
        });
      }
    } else if (code === 'K' || /black|黑/i.test(item.label || '')) {
      out.push({ ...item, key: 'K', code: 'K', label: INK_COLORS.K.label, color: INK_COLORS.K.color });
    } else {
      out.push(item);
    }
  }
  return out;
}

export async function mount(root, ctx) {
  const { api, state, bus, navigate, toast } = ctx;

  let disposed = false;
  let jobs = [];
  let jobsError = '';
  let shortcuts = [];
  let shortcutBusy = false;

  const wrap = h('div', { class: 'view-home' });
  root.append(wrap);
  paintSkeleton();

  function paintSkeleton() {
    wrap.replaceChildren(
      h(
        'div',
        { class: 'home-grid' },
        h(
          'div',
          { class: 'card skeleton-card', style: { minHeight: '250px' } },
          skeleton({ width: '24%', height: 12 }),
          skeleton({ width: '58%', height: 26 }),
          skeletonLines(2),
          skeleton({ width: '46%', height: 36, radius: 999 })
        ),
        h('div', { class: 'card skeleton-card' }, skeleton({ width: '38%', height: 18 }), skeletonLines(4)),
        h(
          'div',
          { class: 'quick-card' },
          ...[0, 1, 2, 3].map(() =>
            h(
              'div',
              { class: 'card', style: { padding: '18px', display: 'grid', gap: '12px' } },
              skeleton({ width: 40, height: 40, radius: 12 }),
              skeleton({ width: '52%', height: 14 }),
              skeleton({ width: '70%', height: 11 })
            )
          )
        ),
        h('div', { class: 'card skeleton-card' }, skeleton({ width: '38%', height: 18 }), skeletonRows(3))
      )
    );
  }

  async function loadShortcuts() {
    try {
      const res = await api.shortcuts();
      if (disposed) return;
      shortcuts = (res && res.shortcuts) || [];
      paint();
    } catch (err) {
      // 快捷方式读取失败不影响首页其它内容
    }
  }

  function paint() {
    if (disposed) return;
    const printer = state.printer;
    const status = state.status;
    const online = Boolean(printer && printer.online);

    wrap.replaceChildren();

    if (printer && (!online || (status && status.online === false))) {
      wrap.append(
        banner({
          tone: 'warning',
          icon: 'warning',
          title: '打印机当前离线',
          message: '请检查电源与 Wi-Fi 连接。历史记录与打印队列仍可查看。',
          action: button({
            label: '重试',
            icon: 'refresh',
            variant: 'text',
            onclick: () => ctx.refreshStatus({ silent: false }),
          }),
        })
      );
    } else if (state.statusError && printer) {
      wrap.append(
        banner({
          tone: 'error',
          icon: 'warning',
          title: '无法读取打印机状态',
          message: state.statusError,
          action: button({
            label: '重试',
            icon: 'refresh',
            variant: 'text',
            onclick: () => ctx.refreshStatus({ silent: false }),
          }),
        })
      );
    }

    wrap.append(
      h(
        'div',
        { class: 'home-grid' },
        heroCard(printer, status, online),
        suppliesCard(status, online),
        quickCard(),
        recentCard()
      )
    );
  }

  function heroCard(printer, status, online) {
    const card = h('article', { class: 'hero' });

    if (!printer) {
      card.append(
        h(
          'div',
          { class: 'hero-top' },
          h(
            'div',
            {},
            h('span', { class: 'eyebrow', text: '当前打印机' }),
            h('h2', { class: 'hero-name', text: '尚未注册打印机' }),
            h('p', {
              class: 'hero-host',
              text: '在本机局域网中搜索，或手动填写 IP 地址。',
            })
          )
        ),
        h(
          'div',
          { class: 'hero-actions' },
          button({
            label: '发现打印机',
            icon: 'wifi',
            variant: 'filled',
            onclick: () => navigate('printer'),
          }),
          button({
            label: '手动指定 IP',
            icon: 'link',
            variant: 'outlined',
            onclick: () => navigate('printer'),
          })
        )
      );
      return card;
    }

    const stateText = status && status.state_message ? status.state_message : '';
    const counters = (status && status.counters) || {};
    const cloudCalls = state.health && Number.isFinite(Number(state.health.cloud_calls)) ? Number(state.health.cloud_calls) : null;

    card.append(
      h(
        'div',
        { class: 'hero-top' },
        h(
          'div',
          {},
          h('span', { class: 'eyebrow', text: '当前打印机' }),
          h('h2', { class: 'hero-name', text: printer.model || printer.name || '未命名打印机' }),
          h(
            'p',
            { class: 'hero-host' },
            icon('link', 15),
            h('span', { text: printer.host || '—' }),
            h('span', { class: 'dot-sep', text: '·' }),
            h('span', { text: 'IPP 631' }),
            h('span', { class: 'dot-sep', text: '·' }),
            h('span', { text: printer.queue_name || '—' })
          )
        ),
        h(
          'div',
          { class: 'hero-badges' },
          stateChip(printer.state, { kind: 'printer', online: printer.online }),
          h(
            'span',
            { class: 'zero-cloud', title: '本应用不发起任何公网请求' },
            icon('cloudOff', 15),
            h('span', { text: `零云端 · ${cloudCalls === null ? '—' : fmt.number(cloudCalls)} 次公网请求` })
          )
        )
      ),
      h(
        'div',
        { class: 'hero-metrics' },
        metric('累计页数', counters.total_pages !== undefined ? fmt.number(counters.total_pages) : '—', true),
        metric('扫描页数', counters.scan_pages !== undefined ? fmt.number(counters.scan_pages) : '—', true),
        metric('当前状态', stateText || (online ? '就绪' : '离线'), false)
      ),
      h(
        'div',
        { class: 'hero-actions' },
        button({
          label: '打印文档',
          icon: 'print',
          variant: 'filled',
          onclick: () => navigate('print'),
        }),
        button({
          label: '扫描',
          icon: 'scan',
          variant: 'outlined',
          onclick: () => navigate('scan'),
        }),
        button({
          label: '打印机详情',
          iconEnd: 'chevronRight',
          variant: 'text',
          onclick: () => navigate('printer'),
        })
      )
    );

    card.append(icon('print', 240, 'hero-watermark'));
    return card;
  }

  function metric(label, value, mono) {
    return h(
      'div',
      { class: 'hero-metric' },
      h('span', { class: 'metric-label', text: label }),
      h('span', { class: `metric-value${mono ? ' is-mono' : ''}`, text: value })
    );
  }

  function suppliesCard(status, online) {
    const supplies = (status && Array.isArray(status.supplies) && status.supplies) || [];
    const channels = expandChannels(supplies);
    const anyUnknown = channels.some((item) => Number(item.level) < 0);

    const body = channels.length
      ? h(
          'div',
          {},
          h('div', { class: 'tanks' }, channels.map(tank)),
          anyUnknown
            ? h(
                'p',
                { class: 'supplies-note' },
                icon('info', 16),
                h('span', { text: '墨仓式 · 无电子墨量，设备仅上报墨仓状态，不提供百分比。' })
              )
            : null
        )
      : emptyState({
          icon: 'droplet',
          title: online ? '设备未上报耗材信息' : '打印机离线',
          description: online ? '此打印机可能不支持耗材查询。' : '连接恢复后会自动读取墨水余量。',
        });

    return section({
      title: '墨水余量',
      subtitle: channels.length ? `共 ${channels.length} 色` : undefined,
      actions: status && status.media ? chip({ label: mediaShort(status.media.ready), tone: 'neutral' }) : null,
      children: body,
      class: 'supplies-card',
    });
  }

  function tank(supply) {
    const level = Number(supply.level);
    const unknown = !Number.isFinite(level) || level < 0;
    const low = !unknown && (supply.state === 'low' || level <= 20);
    const stateText = SUPPLY_STATE_TEXT[supply.state] || (unknown ? '未知' : '正常');

    const value = h('span', {
      class: `tank-value${unknown ? ' is-unknown' : ''}`,
      text: unknown ? stateText : fmt.percent(level),
    });

    const track = h('div', {
      class: 'tank-track',
      role: 'img',
      'aria-label': `${supply.label || '墨水'}：${
        unknown ? `墨仓式，无电子墨量，状态${stateText}` : `余量 ${Math.round(level)}%`
      }`,
    });

    if (!unknown) {
      const fill = h('div', { class: 'tank-fill', style: { height: `${Math.max(2, Math.min(100, level))}%` } });
      fill.style.setProperty('--tank-color', supply.color || 'var(--md-sys-color-primary)');
      track.append(fill);
    } else {
      // 设备不报百分比：用带斜纹的半透明色块表示“有墨但无电子计量”，
      // 颜色仍按真实墨色区分，避免灰扑扑一片。
      const fill = h('div', { class: 'tank-fill is-decorative', style: { height: '34%' } });
      fill.style.setProperty('--tank-color', supply.color || 'var(--md-sys-color-primary)');
      track.append(fill);
    }

    const wrap = h(
      'div',
      { class: `tank${low ? ' is-low' : ''}${unknown ? ' is-unknown' : ''}` },
      value,
      track,
      h('span', { class: 'tank-label', text: supply.label || '墨水' }),
      low ? h('span', { class: 'tank-state', text: '余量偏低' }) : null
    );
    wrap.style.setProperty('--tank-color', supply.color || 'var(--md-sys-color-primary)');
    return wrap;
  }

  function quickCard() {
    return h(
      'div',
      { class: 'quick-card' },
      quickTile({
        icon: 'fileText',
        title: '打印文档',
        sub: 'PDF · 图片 · 多文件',
        onclick: () => navigate('print'),
      }),
      quickTile({
        icon: 'image',
        title: '打印照片',
        sub: '4 × 6 · L 尺寸',
        onclick: () => navigate('print'),
      }),
      quickTile({
        icon: 'scan',
        title: '扫描',
        sub: 'JPEG / PDF · 最高 1200 dpi',
        onclick: () => navigate('scan'),
      }),
      quickTile({
        icon: 'copy',
        title: '复印',
        sub: '彩色 / 黑白 · 本机完成',
        onclick: startCopy,
      }),
      quickTile({
        icon: 'wrench',
        title: '维护',
        sub: '清洗 · 校准 · 状态报告',
        onclick: () => navigate('printer'),
      }),
      ...shortcuts.map((item) =>
        quickTile({
          icon: item.icon || 'scan',
          title: item.name,
          sub: `快捷方式 · ${(item.steps || []).map((s) => ({ save: '保存', email: '邮件', print: '打印' }[s] || s)).join(' → ')}`,
          onclick: () => startShortcut(item),
        })
      )
    );
  }

  async function startShortcut(item) {
    if (shortcutBusy) {
      toast('正在执行上一个快捷方式，请稍候', { tone: 'warning' });
      return;
    }
    if (!state.printer) {
      toast('尚未选择打印机', { tone: 'error' });
      return;
    }
    shortcutBusy = true;
    toast(`正在运行「${item.name}」…`, { duration: 5000 });
    try {
      const res = await api.runShortcut(item.id);
      const errs = (res && res.errors) || [];
      toast(
        errs.length ? `完成，但 ${errs.length} 个步骤失败：${errs[0]}` : `「${item.name}」执行完成`,
        { tone: errs.length ? 'warning' : 'success', duration: 7000 }
      );
      navigate('tasks');
    } catch (err) {
      toast(err.message || '快捷方式执行失败', { tone: 'error', duration: 8000 });
    } finally {
      shortcutBusy = false;
    }
  }

  function startCopy() {
    const printer = state.printer;
    if (!printer) {
      toast('尚未选择打印机', { tone: 'error' });
      return;
    }
    if (!printer.online) {
      toast('打印机离线，无法复印', { tone: 'error' });
      return;
    }

    const opts = { color: 'color', copies: 1 };
    const colorPick = segmented({
      options: [
        { value: 'color', label: '彩色' },
        { value: 'monochrome', label: '黑白' },
      ],
      value: opts.color,
      ariaLabel: '复印颜色',
      onchange: (value) => {
        opts.color = value;
      },
    });
    const copiesPick = stepper({
      label: '份数',
      value: opts.copies,
      min: 1,
      max: 9,
      onchange: (value) => {
        opts.copies = value;
      },
    });

    let dialog = null;
    dialog = openDialog({
      title: '复印',
      body: h(
        'div',
        { class: 'copy-dialog' },
        h('p', { class: 'copy-hint', text: '把原件放在扫描仪玻璃板上，点「开始复印」。打印机会先扫描再打印，全程离线。' }),
        h('div', { class: 'copy-field' }, h('span', { class: 'option-label', text: '颜色' }), colorPick),
        h('div', { class: 'copy-field' }, copiesPick)
      ),
      actions: [
        button({ label: '取消', variant: 'text', onclick: () => dialog.close() }),
        button({
          label: '开始复印',
          icon: 'copy',
          variant: 'filled',
          onclick: async () => {
            dialog.close();
            toast('正在扫描原件…完成后会自动打印', { duration: 6000 });
            try {
              const res = await api.copy({
                printer_id: printer.id,
                options: { copies: opts.copies, color: opts.color, dpi: 300 },
              });
              toast(`复印已提交：扫描 #${res.scan_job} → 打印 #${res.print_job}`, { tone: 'success' });
              navigate('tasks');
            } catch (err) {
              toast(err.message || '复印失败', { tone: 'error', duration: 8000 });
            }
          },
        }),
      ],
    });
  }

  function quickTile({ icon: iconName, title: label, sub, onclick }) {
    return h(
      'button',
      { class: 'quick-tile', type: 'button', onclick },
      h(
        'span',
        { class: 'quick-tile-top' },
        h('span', { class: 'quick-icon' }, icon(iconName, 21)),
        h('span', { class: 'quick-arrow' }, icon('arrowRight', 18))
      ),
      h('span', { class: 'quick-title', text: label }),
      h('span', { class: 'quick-sub', text: sub })
    );
  }

  function recentCard() {
    const actions = button({
      label: '查看全部',
      variant: 'text',
      size: 'sm',
      iconEnd: 'chevronRight',
      onclick: () => navigate('history'),
    });

    let body;
    if (jobsError) {
      body = emptyState({
        icon: 'warning',
        title: '无法读取作业记录',
        description: jobsError,
        tone: 'error',
        action: button({ label: '重试', icon: 'refresh', variant: 'tonal', onclick: loadJobs }),
      });
    } else if (!jobs.length) {
      body = emptyState({
        icon: 'history',
        title: '暂无作业记录',
        description: '打印或扫描完成后，作业会显示在这里。',
        action: button({ label: '去打印', icon: 'print', variant: 'tonal', onclick: () => navigate('print') }),
      });
    } else {
      body = h(
        'div',
        { class: 'job-list' },
        jobs.slice(0, 4).map((job) => jobRow(job, { onclick: () => navigate('history') }))
      );
    }

    return section({
      title: '最近作业',
      actions,
      children: body,
      class: 'recent-card',
    });
  }

  async function loadJobs() {
    try {
      const data = await api.jobs({ limit: 6 });
      jobs = Array.isArray(data.jobs) ? data.jobs : [];
      jobsError = '';
    } catch (err) {
      jobsError = err.message;
    }
    paint();
  }

  const offPrinters = bus.on('printers', paint);
  const offStatus = bus.on('status', paint);
  const offJob = bus.on('job', (job) => {
    const index = jobs.findIndex((item) => item.id === job.id);
    if (index >= 0) {
      jobs[index] = { ...jobs[index], ...job };
      paint();
    } else if (job.state === 'done' || job.state === 'error') {
      loadJobs();
    }
  });
  const offRefresh = bus.on('refresh', loadJobs);

  paint();
  loadJobs();
  loadShortcuts();

  return () => {
    disposed = true;
    offPrinters();
    offStatus();
    offJob();
    offRefresh();
  };
}

function mediaShort(media) {
  if (!media) return '纸张：—';
  if (media.includes('a4')) return 'A4';
  if (media.includes('letter')) return 'Letter';
  if (media.includes('4x6')) return '4 × 6 in';
  if (media.includes('photo-l')) return 'L 照片';
  return media;
}
