/**
 * views/printer.js — 打印机：设备信息、耗材、能力、维护、手动注册
 */

import {
  h,
  icon,
  button,
  iconButton,
  chip,
  section,
  textField,
  stateChip,
  fmt,
  openDialog,
  confirmDialog,
  mediaLabel,
} from '../components/ui.js';
import { skeleton, skeletonLines, emptyState, banner } from '../components/feedback.js';

export const title = '打印机';
export const subtitle = (state) =>
  state.printer ? `${state.printer.name || state.printer.model} · ${state.printer.host}` : '未注册任何设备';

const MAINTENANCE = [
  { action: 'clean', label: '清洗打印头', icon: 'droplet', desc: '解决断线、缺色' },
  { action: 'calibrate', label: '校准', icon: 'tune', desc: '校正色彩与对齐' },
  { action: 'report', label: '打印报告', icon: 'fileText', desc: '输出设备状态页' },
];

const SOURCE_LABEL = { wsd: 'WSD', mdns: 'mDNS', snmp: 'SNMP', scan: '网段扫描' };

export async function mount(root, ctx) {
  const { api, state, bus, toast } = ctx;

  let loading = !state.status;
  let maintenanceBusy = '';
  let discovering = false;
  let registering = false;

  const bannerSlot = h('div');
  const deviceSlot = h('div', { class: 'printer-col' });
  const suppliesSlot = h('div', { class: 'printer-stack' });
  const manualCard = buildManualCard();
  const sideSlot = h('div', { class: 'printer-col' }, suppliesSlot, manualCard);

  root.append(h('div', { class: 'printer-grid' }, deviceSlot, sideSlot));

  /* ------------------------------------------------------------------ 结构 */

  function paint() {
    bannerSlot.replaceChildren();
    if (state.apiOnline && state.printer && !state.printer.online) {
      bannerSlot.append(
        banner({
          tone: 'warning',
          icon: 'wifi',
          title: '打印机离线',
          message: '无法读取实时状态。请检查电源与 Wi-Fi，或确认 IP 地址是否变化。',
          action: button({
            label: '重试',
            icon: 'refresh',
            variant: 'text',
            onclick: () => ctx.refreshStatus({ silent: false }),
          }),
        })
      );
    }

    deviceSlot.replaceChildren();
    if (!bannerSlot.isConnected) root.prepend(bannerSlot);

    if (!state.printer) {
      deviceSlot.append(noPrinterCard());
      suppliesSlot.replaceChildren(noSuppliesCard());
      return;
    }

    if (loading && !state.status) {
      deviceSlot.append(skeletonCard());
      suppliesSlot.replaceChildren(skeletonCard());
      return;
    }

    deviceSlot.append(deviceCard(), maintenanceCard());
    suppliesSlot.replaceChildren(suppliesCard(), capabilityCard());
  }

  function noPrinterCard() {
    return section({
      title: '尚未注册打印机',
      subtitle: 'HP Offline 只连接局域网内的设备，不会向任何服务器查询。',
      children: emptyState({
        icon: 'print',
        title: '从局域网中添加设备',
        description: '自动发现会使用 mDNS / WSD / SNMP 探测同网段打印机；也可以直接填写 IP 地址。',
        action: h(
          'div',
          { class: 'dropzone-actions' },
          button({
            label: discovering ? '正在搜索…' : '发现打印机',
            icon: 'wifi',
            variant: 'filled',
            disabled: discovering,
            onclick: discover,
          }),
          button({
            label: '手动指定 IP',
            icon: 'link',
            variant: 'outlined',
            onclick: () => {
              const input = manualCard.querySelector('input');
              if (input) input.focus();
            },
          })
        ),
      }),
    });
  }

  function noSuppliesCard() {
    return section({
      title: '墨水余量',
      children: emptyState({
        icon: 'droplet',
        title: '暂无设备',
        description: '注册打印机后可查看墨仓状态。',
      }),
    });
  }

  function deviceCard() {
    const printer = state.printer;
    const status = state.status;
    const alerts = (status && Array.isArray(status.alerts) && status.alerts) || [];

    const head = h(
      'div',
      { class: 'device-head' },
      h(
        'div',
        {},
        h('h2', { class: 'device-name', text: printer.model || printer.name || '未命名打印机' }),
        h('p', { class: 'device-host' }, icon('link', 14), h('span', { text: printer.host || '—' }))
      ),
      h(
        'div',
        { class: 'section-actions' },
        stateChip(printer.state, { kind: 'printer', online: printer.online })
      )
    );

    const info = h(
      'dl',
      { class: 'info-grid' },
      infoRow('型号', printer.model || printer.name || '—', true),
      infoRow('IP 地址', printer.host || '—'),
      infoRow('序列号', printer.serial || '—'),
      infoRow('固件版本', printer.firmware || '—'),
      infoRow('设备 UUID', printer.id || '—'),
      infoRow('队列名称', printer.queue_name || '—'),
      infoRow('主机名', printer.hostname || '—'),
      infoRow('最近在线', printer.last_seen ? fmt.relative(printer.last_seen) : '—', true)
    );

    const actions = h(
      'div',
      { class: 'device-actions' },
      printer.is_default
        ? chip({ label: '默认打印机', tone: 'info', icon: 'check' })
        : button({
            label: '设为默认',
            icon: 'check',
            variant: 'tonal',
            size: 'sm',
            onclick: async () => {
              try {
                await api.setDefaultPrinter(printer.id);
                toast('已设为默认打印机', { tone: 'success' });
                await ctx.refreshPrinters({ silent: true });
              } catch (err) {
                toast(err.message, { tone: 'error' });
              }
            },
          }),
      status && status.media
        ? chip({ label: `纸盒 · ${mediaLabel(status.media.ready)}`, tone: 'neutral', icon: 'fileText' })
        : null,
      h('span', { class: 'spacer' }),
      button({
        label: '移除设备',
        variant: 'text',
        size: 'sm',
        icon: 'trash',
        onclick: async () => {
          const ok = await confirmDialog({
            title: '移除打印机？',
            message: `将从本机移除「${printer.name || printer.model}」，不会影响打印机本身的设置。`,
            confirmLabel: '移除',
            danger: true,
          });
          if (!ok) return;
          try {
            await api.removePrinter(printer.id);
            toast('已移除打印机', { tone: 'success' });
            await ctx.refreshPrinters({ silent: true });
          } catch (err) {
            toast(err.message, { tone: 'error' });
          }
        },
      })
    );

    const alertBlock = alerts.length
      ? h(
          'div',
          { class: 'device-alerts' },
          alerts.map((alert) => chip({ label: alert.message || alert.category || '设备提醒', tone: 'warning', icon: 'warning' }))
        )
      : null;

    return section({
      title: '设备信息',
      actions: iconButton({
        icon: 'refresh',
        label: '刷新设备状态',
        onclick: () => ctx.refreshStatus({ silent: false }),
      }),
      children: h('div', {}, head, alertBlock, h('div', { class: 'divider' }), info, actions),
    });
  }

  function infoRow(label, value, isText = false) {
    return [
      h('dt', { text: label }),
      h('dd', { class: isText ? 'is-text' : '', text: value, title: value }),
    ];
  }

  function capabilityCard() {
    const caps = (state.status && state.status.capabilities) || null;
    if (!caps) {
      return section({
        title: '设备能力',
        children: emptyState({
          icon: 'info',
          title: '暂无能力信息',
          description: state.statusError || '连接恢复后会自动读取设备能力。',
        }),
      });
    }

    return section({
      title: '设备能力',
      subtitle: '来自 eSCL / IPP 能力查询',
      children: h(
        'div',
        { class: 'cap-chips' },
        capChip('彩色', Boolean(caps.color)),
        capChip('双面', Boolean(caps.duplex)),
        capChip('扫描', Boolean(caps.scan)),
        capChip('自动进纸器', Boolean(caps.adf)),
        caps.max_scan_dpi
          ? chip({ label: `最大 ${fmt.number(caps.max_scan_dpi)} dpi`, tone: 'neutral', icon: 'scan' })
          : null
      ),
    });
  }

  function capChip(label, ok) {
    return chip({
      label: `${label}（${ok ? '支持' : '不支持'}）`,
      tone: ok ? 'success' : 'neutral',
      icon: ok ? 'check' : 'close',
    });
  }

  function suppliesCard() {
    const status = state.status;
    const supplies = (status && Array.isArray(status.supplies) && status.supplies) || [];

    if (!supplies.length) {
      return section({
        title: '墨水余量',
        children: emptyState({
          icon: 'droplet',
          title: '设备未上报耗材',
          description: '该机型可能不支持电子墨量查询。',
        }),
      });
    }

    const rows = supplies.map((supply) => {
      const level = Number(supply.level);
      const unknown = !Number.isFinite(level) || level < 0;
      const low = !unknown && (supply.state === 'low' || level <= 20);
      const bar = h('div', {
        class: `supply-bar${unknown ? ' is-unknown' : ''}`,
        role: 'img',
        'aria-label': `${supply.label || '墨水'}：${
          unknown ? '无电子墨量' : `余量 ${Math.round(level)}%`
        }`,
      });
      if (!unknown) {
        const fill = h('span', { style: { width: `${Math.max(2, Math.min(100, level))}%` } });
        fill.style.setProperty('--supply-color', supply.color || 'var(--md-sys-color-primary)');
        bar.append(fill);
      }

      return h(
        'div',
        { class: 'supply-row' },
        h(
          'div',
          { class: 'supply-head' },
          h(
            'span',
            { class: 'supply-name' },
            h('span', { class: 'supply-swatch', style: { background: supply.color || 'transparent' } }),
            h('span', { text: supply.label || '墨水' })
          ),
          h('span', {
            class: 'supply-level',
            text: unknown
              ? `无电子墨量 · ${supply.state === 'low' ? '偏低' : supply.state === 'empty' ? '已空' : '状态正常'}`
              : `${fmt.percent(level)}${low ? ' · 偏低' : ''}`,
          })
        ),
        bar
      );
    });

    return section({
      title: '墨水余量',
      subtitle: `${supplies.length} 个墨仓`,
      children: h(
        'div',
        { class: 'supply-list' },
        rows,
        supplies.some((item) => Number(item.level) < 0)
          ? h(
              'p',
              { class: 'supplies-note' },
              icon('info', 16),
              h('span', { text: '墨仓式机型不提供百分比，仅上报墨仓状态。' })
            )
          : null
      ),
    });
  }

  function maintenanceCard() {
    return section({
      title: '维护',
      subtitle: '指令通过 LEDM 直连打印机执行',
      children: h(
        'div',
        { class: 'maintenance-grid' },
        MAINTENANCE.map((item) =>
          h(
            'button',
            {
              class: 'maintenance-btn',
              type: 'button',
              disabled: Boolean(maintenanceBusy),
              onclick: () => runMaintenance(item),
            },
            icon(item.icon, 20),
            h('span', { text: maintenanceBusy === item.action ? '执行中…' : item.label }),
            h('span', { class: 'maintenance-desc', text: item.desc })
          )
        )
      ),
    });
  }

  function skeletonCard() {
    return h(
      'div',
      { class: 'card skeleton-card' },
      skeleton({ width: '36%', height: 18 }),
      skeletonLines(5),
      skeleton({ width: '46%', height: 32, radius: 16 })
    );
  }

  function buildManualCard() {
    const hostInput = h('input', {
      class: 'field-input is-mono',
      type: 'text',
      placeholder: '192.168.1.100',
      inputmode: 'decimal',
      spellcheck: false,
      'aria-label': '打印机 IP 地址',
    });
    const submitBtn = button({
      label: '注册',
      icon: 'plus',
      variant: 'filled',
      onclick: () => register(hostInput.value),
    });

    hostInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        register(hostInput.value);
      }
    });

    return section({
      title: '手动指定 IP',
      subtitle: 'DHCP 地址变化后，用新地址重新注册即可',
      actions: button({
        label: discovering ? '搜索中…' : '发现设备',
        icon: 'wifi',
        variant: 'text',
        size: 'sm',
        disabled: discovering,
        onclick: discover,
      }),
      children: h(
        'div',
        {},
        h(
          'div',
          { class: 'manual-ip' },
          h(
            'div',
            { class: 'field' },
            h('label', { class: 'field-label', for: 'manual-host', text: 'IP 地址' }),
            h('div', { class: 'field-box' }, hostInput)
          ),
          submitBtn
        ),
        h('p', {
          class: 'field-hint',
          text: '后端会探测 IPP 631 / eSCL 80 / LEDM 80 并保存能力。',
        })
      ),
    });
  }

  /* --------------------------------------------------------------- 行为 */

  async function register(host) {
    const value = String(host || '').trim();
    if (!value) {
      toast('请填写打印机 IP 地址', { tone: 'error' });
      return;
    }
    if (registering) return;
    registering = true;
    try {
      await api.addPrinter(value);
      toast('打印机已注册', { tone: 'success' });
      await ctx.refreshPrinters({ silent: false });
      loading = false;
      paint();
    } catch (err) {
      toast(err.message, { tone: 'error', duration: 6000 });
    } finally {
      registering = false;
    }
  }

  async function runMaintenance(item) {
    if (maintenanceBusy) return;
    maintenanceBusy = item.action;
    paint();
    try {
      const result = await api.maintenance(state.printer.id, item.action);
      toast((result && result.detail) || `${item.label}指令已发送`, { tone: 'success', duration: 5200 });
    } catch (err) {
      toast(err.message, { tone: 'error', duration: 6000 });
    } finally {
      maintenanceBusy = '';
      paint();
    }
  }

  async function discover() {
    if (discovering) return;
    discovering = true;
    paint();
    try {
      const data = await api.discover();
      const found = Array.isArray(data.found) ? data.found : [];
      showFound(found);
    } catch (err) {
      toast(err.message, { tone: 'error', duration: 6000 });
    } finally {
      discovering = false;
      paint();
    }
  }

  function showFound(found) {
    let dialog = null;
    const list = h('div', { class: 'found-list' });

    if (!found.length) {
      list.append(
        emptyState({
          icon: 'wifi',
          title: '未发现打印机',
          description: '确认打印机与电脑在同一网段，或手动填写 IP 地址。',
        })
      );
    }

    found.forEach((device) => {
      const registered = state.printers.some((printer) => printer.host === device.host);
      const addBtn = button({
        label: registered ? '已注册' : '注册',
        variant: registered ? 'text' : 'tonal',
        size: 'sm',
        disabled: registered,
        onclick: async () => {
          addBtn.disabled = true;
          addBtn.replaceChildren(h('span', { class: 'btn-label', text: '注册中…' }));
          try {
            await api.addPrinter(device.host);
            toast(`已添加 ${device.model || device.host}`, { tone: 'success' });
            await ctx.refreshPrinters({ silent: false });
            loading = false;
            paint();
            dialog.close();
          } catch (err) {
            toast(err.message, { tone: 'error' });
            addBtn.disabled = false;
            addBtn.replaceChildren(h('span', { class: 'btn-label', text: '重试' }));
          }
        },
      });

      list.append(
        h(
          'div',
          { class: 'found-row' },
          h('span', { class: 'job-icon job-icon-print' }, icon('print', 18)),
          h(
            'div',
            { class: 'found-info' },
            h('span', { class: 'found-name', text: device.model || '未知型号' }),
            h(
              'span',
              { class: 'found-meta' },
              h('span', { class: 'mono', text: device.host || '—' }),
              device.source ? h('span', { text: ` · ${SOURCE_LABEL[device.source] || device.source}` }) : null
            )
          ),
          addBtn
        )
      );
    });

    dialog = openDialog({
      title: '发现打印机',
      body: h(
        'div',
        {},
        h('p', { class: 'dialog-text', text: `在局域网中发现 ${found.length} 台设备。` }),
        list
      ),
      actions: [button({ label: '关闭', variant: 'text', onclick: () => dialog.close() })],
      width: '540px',
    });
  }

  const offPrinters = bus.on('printers', () => {
    loading = false;
    paint();
  });
  const offStatus = bus.on('status', () => {
    loading = false;
    paint();
  });
  const offRefresh = bus.on('refresh', () => ctx.refreshStatus({ silent: true }));

  paint();
  if (state.printer && !state.status) ctx.refreshStatus({ silent: true });
  else loading = false;

  return () => {
    offPrinters();
    offStatus();
    offRefresh();
  };
}
