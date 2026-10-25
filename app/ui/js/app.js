/**
 * app.js — 应用外壳：哈希路由、全局状态、主题、离线横幅、事件订阅
 */

import { api, assetUrl, connectEvents, isMock } from './api.js';
import { icon } from '../icons.js';
import { h, button, chip, fmt } from './components/ui.js';
import { toast, banner } from './components/feedback.js';
import * as home from './views/home.js';
import * as print from './views/print.js';
import * as scan from './views/scan.js';
import * as printer from './views/printer.js';
import * as history from './views/history.js';
import * as tasks from './views/tasks.js';
import * as settings from './views/settings.js';

const VIEWS = { home, print, scan, tasks, printer, history, settings };

export const state = {
  health: null,
  settings: null,
  printers: [],
  printer: null,
  status: null,
  statusError: '',
  jobs: [],
  scans: [],
  apiOnline: true,
  lastError: '',
  eventMode: 'connecting',
};

/* -------------------------------------------------------------------------- */
/* 极简事件总线                                                                */
/* -------------------------------------------------------------------------- */

function createEmitter() {
  const map = new Map();
  return {
    on(type, fn) {
      if (!map.has(type)) map.set(type, new Set());
      map.get(type).add(fn);
      return () => map.get(type) && map.get(type).delete(fn);
    },
    emit(type, payload) {
      const set = map.get(type);
      if (!set) return;
      set.forEach((fn) => {
        try {
          fn(payload);
        } catch (err) {
          console.error('[bus]', type, err);
        }
      });
    },
  };
}

export const bus = createEmitter();

/* -------------------------------------------------------------------------- */
/* 主题 / 强调色                                                               */
/* -------------------------------------------------------------------------- */

const ACCENTS = {
  hp: { hex: '#0096D6', label: 'HP 青蓝' },
  teal: { hex: '#00695C', label: '湖绿' },
  amber: { hex: '#825500', label: '琥珀' },
  rose: { hex: '#A30058', label: '玫红' },
};

function accentNameFromHex(hex) {
  if (!hex) return 'hp';
  const normalized = String(hex).toUpperCase();
  const found = Object.entries(ACCENTS).find(([, meta]) => meta.hex.toUpperCase() === normalized);
  return found ? found[0] : 'hp';
}

export function applyTheme(theme, { persist = true } = {}) {
  const value = ['light', 'dark', 'system'].includes(theme) ? theme : 'system';
  document.documentElement.dataset.theme = value;
  if (persist) {
    try {
      localStorage.setItem('hp.theme', value);
    } catch {
      /* noop */
    }
  }
  updateThemeButton();
}

export function applyAccent(name, { persist = true } = {}) {
  const value = ACCENTS[name] ? name : 'hp';
  document.documentElement.dataset.accent = value;
  if (persist) {
    try {
      localStorage.setItem('hp.accent', value);
    } catch {
      /* noop */
    }
  }
}

function effectiveDark() {
  const theme = document.documentElement.dataset.theme;
  if (theme === 'dark') return true;
  if (theme === 'light') return false;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function updateThemeButton() {
  const btn = document.getElementById('btn-theme');
  if (!btn) return;
  const theme = document.documentElement.dataset.theme || 'system';
  const name = theme === 'dark' ? 'sun' : theme === 'light' ? 'moon' : 'monitor';
  btn.replaceChildren(icon(name, 20));
  btn.title = theme === 'dark' ? '切换到浅色主题' : theme === 'light' ? '切换到深色主题' : '当前跟随系统主题';
  btn.setAttribute('aria-label', btn.title);
}

/* -------------------------------------------------------------------------- */
/* 路由                                                                        */
/* -------------------------------------------------------------------------- */

const pageTitle = document.getElementById('page-title');
const pageSub = document.getElementById('page-sub');
const viewRoot = document.getElementById('view');

let currentRoute = null;
let currentCleanup = null;
let routeToken = 0;

function routeFromHash() {
  const raw = location.hash.replace(/^#\/?/, '').split('?')[0];
  return VIEWS[raw] ? raw : 'home';
}

export function navigate(route) {
  const target = VIEWS[route] ? route : 'home';
  if (location.hash === `#/${target}`) {
    renderRoute();
  } else {
    location.hash = `#/${target}`;
  }
}

function setActiveNav(route) {
  document.querySelectorAll('.nav-item').forEach((item) => {
    if (item.dataset.route === route) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  });
}

function viewSubtitle(view) {
  if (typeof view.subtitle === 'function') return view.subtitle(state);
  return view.subtitle || '';
}

function updateViewHead() {
  const view = VIEWS[currentRoute] || VIEWS.home;
  if (pageTitle) pageTitle.textContent = view.title;
  if (pageSub) pageSub.textContent = viewSubtitle(view);
}

async function renderRoute() {
  const route = routeFromHash();
  const view = VIEWS[route];
  if (!view) {
    location.hash = '#/home';
    return;
  }

  if (currentCleanup) {
    try {
      currentCleanup();
    } catch (err) {
      console.error('[cleanup]', err);
    }
    currentCleanup = null;
  }

  const token = ++routeToken;
  currentRoute = route;
  setActiveNav(route);
  document.title = `${view.title} · HP Offline`;
  updateViewHead();
  try {
    localStorage.setItem('hp.route', route);
  } catch {
    /* noop */
  }

  viewRoot.innerHTML = '';
  viewRoot.classList.remove('has-actionbar');
  window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });

  const cleanup = await view.mount(viewRoot, ctx);
  if (token !== routeToken) {
    if (typeof cleanup === 'function') cleanup();
    return;
  }
  currentCleanup = typeof cleanup === 'function' ? cleanup : null;
}

/* -------------------------------------------------------------------------- */
/* 顶栏 / 离线横幅                                                             */
/* -------------------------------------------------------------------------- */

function renderOfflineBanner() {
  const slot = document.getElementById('offline-slot');
  if (!slot) return;
  slot.replaceChildren();

  if (state.apiOnline) {
    slot.hidden = true;
    return;
  }

  slot.hidden = false;
  slot.append(
    banner({
      tone: 'error',
      icon: 'cloudOff',
      title: '无法连接本地服务',
      message: state.lastError || '请确认 HP Offline 后端已在 127.0.0.1:8791 运行。界面会保留最后一次数据。',
      action: button({
        label: '重试连接',
        icon: 'refresh',
        variant: 'text',
        onclick: () => retryConnection(),
      }),
    })
  );
}

async function retryConnection() {
  await Promise.allSettled([loadHealth(), refreshPrinters({ silent: true })]);
  if (state.apiOnline) {
    toast('已重新连接本地服务', { tone: 'success' });
    bus.emit('printers', state.printers);
  } else {
    toast('仍然无法连接，请检查后端进程', { tone: 'error' });
  }
}

function updateChrome() {
  const chipBtn = document.getElementById('printer-chip');
  const chipText = document.getElementById('printer-chip-text');
  if (chipBtn && chipText) {
    if (state.printer) {
      chipText.textContent = state.printer.model || state.printer.name || '已注册打印机';
      chipBtn.dataset.online = String(Boolean(state.printer.online));
      chipBtn.title = `${state.printer.name || ''} · ${state.printer.host || ''}`;
    } else {
      chipText.textContent = state.apiOnline ? '未注册打印机' : '服务未连接';
      chipBtn.dataset.online = 'false';
      chipBtn.title = state.apiOnline ? '尚未注册打印机' : '本地服务未连接';
    }
  }

  const calls = state.health && Number.isFinite(Number(state.health.cloud_calls)) ? Number(state.health.cloud_calls) : null;
  const cloud = document.getElementById('cloud-calls');
  if (cloud) cloud.textContent = calls === null ? '— 次公网请求' : `${fmt.number(calls)} 次公网请求`;

  const version = document.getElementById('rail-version');
  if (version) version.textContent = state.health && state.health.version ? `v${state.health.version}` : 'v—';

  const mockSlot = document.getElementById('mock-slot');
  if (mockSlot) {
    mockSlot.replaceChildren();
    if (isMock) {
      mockSlot.append(chip({ label: '模拟数据', tone: 'warning', icon: 'info' }));
    }
  }

  updateThemeButton();
  updateViewHead();
}

function bindTopbar() {
  const chipBtn = document.getElementById('printer-chip');
  if (chipBtn) chipBtn.addEventListener('click', () => navigate('printer'));

  const refresh = document.getElementById('btn-refresh');
  if (refresh) {
    refresh.addEventListener('click', async () => {
      refresh.classList.add('is-busy');
      refresh.disabled = true;
      await refreshPrinters({ silent: false });
      bus.emit('refresh');
      refresh.classList.remove('is-busy');
      refresh.disabled = false;
    });
  }

  const themeBtn = document.getElementById('btn-theme');
  if (themeBtn) {
    themeBtn.addEventListener('click', async () => {
      const next = effectiveDark() ? 'light' : 'dark';
      applyTheme(next);
      if (state.settings) state.settings.theme = next;
      try {
        await api.patchSettings({ theme: next });
      } catch {
        /* 离线时仅本地生效 */
      }
      bus.emit('theme', next);
    });
  }

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (document.documentElement.dataset.theme === 'system') updateThemeButton();
  });
}

/* -------------------------------------------------------------------------- */
/* 数据加载                                                                    */
/* -------------------------------------------------------------------------- */

async function loadHealth() {
  try {
    state.health = await api.health();
    state.apiOnline = true;
    state.lastError = '';
  } catch (err) {
    state.apiOnline = false;
    state.lastError = err.message;
  }
  updateChrome();
  renderOfflineBanner();
}

async function loadSettings() {
  try {
    state.settings = await api.settings();
    if (state.settings.theme) applyTheme(state.settings.theme);
    if (state.settings.accent) applyAccent(accentNameFromHex(state.settings.accent));
  } catch {
    /* 保留本地持久化主题 */
  }
}

export async function refreshPrinters({ silent = true, refreshStatus = true } = {}) {
  try {
    const data = await api.printers();
    state.printers = Array.isArray(data.printers) ? data.printers : [];
    state.apiOnline = true;
    state.lastError = '';

    const preferredId = state.settings && state.settings.default_printer;
    state.printer =
      state.printers.find((item) => item.is_default) ||
      state.printers.find((item) => item.id === preferredId) ||
      state.printers[0] ||
      null;

    if (state.printer && refreshStatus) {
      try {
        state.status = await api.status(state.printer.id, true);
        state.statusError = '';
      } catch (err) {
        state.statusError = err.message;
      }
    } else if (!state.printer) {
      state.status = null;
    }

    updateChrome();
    renderOfflineBanner();
    bus.emit('printers', state.printers);
    return state.printers;
  } catch (err) {
    state.apiOnline = false;
    state.lastError = err.message;
    updateChrome();
    renderOfflineBanner();
    bus.emit('printers', state.printers);
    if (!silent) toast(err.message, { tone: 'error' });
    return state.printers;
  }
}

export async function refreshStatus({ silent = true } = {}) {
  if (!state.printer) return null;
  try {
    state.status = await api.status(state.printer.id, true);
    state.statusError = '';
    bus.emit('status', state.status);
    updateChrome();
    return state.status;
  } catch (err) {
    state.statusError = err.message;
    if (!silent) toast(err.message, { tone: 'error' });
    bus.emit('status', null);
    return null;
  }
}

/* -------------------------------------------------------------------------- */
/* 事件订阅（SSE → 轮询降级）                                                  */
/* -------------------------------------------------------------------------- */

let stopEvents = null;

function subscribeEvents() {
  if (stopEvents) stopEvents();
  stopEvents = connectEvents((type, payload) => {
    if (type === 'job') {
      const index = state.jobs.findIndex((job) => job.id === payload.id);
      if (index >= 0) state.jobs[index] = { ...state.jobs[index], ...payload };
      else state.jobs.unshift(payload);
      bus.emit('job', payload);
    } else if (type === 'jobs') {
      state.jobs = Array.isArray(payload) ? payload : [];
      bus.emit('jobs', state.jobs);
    } else if (type === 'printer') {
      refreshPrinters({ silent: true, refreshStatus: true });
    } else if (type === 'mode') {
      state.eventMode = payload.mode;
      if (payload.mode === 'polling') {
        toast('实时连接中断，已切换为 3 秒轮询', { id: 'event-mode', duration: 5000 });
      }
    }
  });
}

/* -------------------------------------------------------------------------- */
/* 交互细节                                                                    */
/* -------------------------------------------------------------------------- */

function bindRipple() {
  document.addEventListener('pointerdown', (event) => {
    const target = event.target.closest('.btn, .icon-btn, .nav-item, .quick-tile, .md-ripple, .filter-chip');
    if (!target || target.disabled) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const rect = target.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 1.15;
    const ripple = document.createElement('span');
    ripple.className = 'ripple';
    ripple.style.width = `${size}px`;
    ripple.style.height = `${size}px`;
    ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${event.clientY - rect.top - size / 2}px`;
    if (getComputedStyle(target).position === 'static') target.style.position = 'relative';
    target.append(ripple);
    setTimeout(() => ripple.remove(), 560);
  });
}

function injectStaticIcons() {
  const brand = document.getElementById('brand-mark');
  if (brand) brand.append(icon('print', 22));

  const seal = document.querySelector('.cloud-seal-icon');
  if (seal) seal.append(icon('cloudOff', 20));

  document.querySelectorAll('.nav-item[data-icon]').forEach((item) => {
    const holder = item.querySelector('.nav-icon');
    if (holder) holder.append(icon(item.dataset.icon, 21));
  });

  updateThemeButton();
}

function bindNav() {
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.addEventListener('click', () => {
      // 交给 hashchange 处理；此处只负责滚动复位
      window.scrollTo({ top: 0 });
    });
  });
}

/* -------------------------------------------------------------------------- */
/* 导出上下文                                                                  */
/* -------------------------------------------------------------------------- */

export const ctx = {
  state,
  api,
  bus,
  toast,
  navigate,
  assetUrl,
  isMock,
  refreshPrinters,
  refreshStatus,
  applyTheme,
  applyAccent,
  accents: ACCENTS,
  effectiveDark,
  reloadRoute: () => renderRoute(),
};

/* -------------------------------------------------------------------------- */
/* 启动                                                                        */
/* -------------------------------------------------------------------------- */

async function boot() {
  injectStaticIcons();
  bindTopbar();
  bindNav();
  bindRipple();

  const storedRoute = (() => {
    try {
      return localStorage.getItem('hp.route');
    } catch {
      return null;
    }
  })();
  if (!location.hash) {
    location.hash = `#/${VIEWS[storedRoute] ? storedRoute : 'home'}`;
  }
  window.addEventListener('hashchange', () => renderRoute());

  await Promise.allSettled([loadHealth(), loadSettings()]);
  await refreshPrinters({ silent: true });
  await renderRoute();
  subscribeEvents();

  setInterval(loadHealth, 30000);
  document.getElementById('app').removeAttribute('aria-busy');
}

boot().catch((err) => {
  console.error('[boot]', err);
  const root = document.getElementById('view');
  if (root) {
    root.innerHTML = '';
    root.append(
      banner({
        tone: 'error',
        icon: 'warning',
        title: '界面初始化失败',
        message: err && err.message ? err.message : '请刷新页面重试。',
      })
    );
  }
});
