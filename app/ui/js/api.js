/**
 * api.js — 本地后端（127.0.0.1:8791）的薄封装
 *
 * 设计要点：
 *  - 所有请求都指向本机回环地址，绝不访问公网。
 *  - 统一错误信息：优先使用后端返回的中文 message。
 *  - SSE 断线自动重连（指数退避 1s → 15s），连续失败后降级为 3s 轮询 /api/jobs。
 *  - 演示模式：URL 加 ?mock=1 时使用内置夹具（仅用于离线截图/开发），
 *    标记写入 sessionStorage，站内跳转后保持；?mock=0 关闭。
 */

const MOCK_FLAG_KEY = 'hp.mock';
const urlParams = new URLSearchParams(location.search);
if (urlParams.get('mock') === '1') sessionStorage.setItem(MOCK_FLAG_KEY, '1');
if (urlParams.get('mock') === '0') sessionStorage.removeItem(MOCK_FLAG_KEY);

export const isMock = sessionStorage.getItem(MOCK_FLAG_KEY) === '1';

// 后端同源提供静态页面，因此默认用 location.origin —— 端口改了也不用改代码。
// 只有从 file:// 或其它源打开时才回落到默认端口。
const DEFAULT_ORIGIN = 'http://127.0.0.1:8791';
export const API_ORIGIN =
  location.protocol === 'http:' || location.protocol === 'https:' ? location.origin : DEFAULT_ORIGIN;
export const API_BASE = `${API_ORIGIN}/api`;

/** 把后端返回的相对路径（缩略图等）转成可用的绝对地址 */
export function assetUrl(path) {
  if (!path) return '';
  if (/^(data:|blob:|https?:)/i.test(path)) return path;
  return API_ORIGIN + (path.startsWith('/') ? path : `/${path}`);
}

const enc = encodeURIComponent;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class ApiError extends Error {
  constructor(message, { status = 0, code = '' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

async function request(path, { method = 'GET', body, timeout = 15000 } = {}) {
  if (isMock) return mockRequest(path, { method, body });

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;

  try {
    const res = await fetch(API_BASE + path, {
      method,
      headers: isForm || body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: isForm ? body : body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: 'no-store',
    });

    if (!res.ok) {
      let message = `请求失败（HTTP ${res.status}）`;
      let code = '';
      try {
        const data = await res.json();
        if (data && data.message) message = data.message;
        if (data && data.error) code = data.error;
      } catch {
        /* 非 JSON 错误体，保留默认文案 */
      }
      throw new ApiError(message, { status: res.status, code });
    }

    if (res.status === 204) return null;
    const type = res.headers.get('content-type') || '';
    if (!type.includes('json')) return res;
    return await res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err.name === 'AbortError') throw new ApiError('请求超时，本地服务未响应', { code: 'timeout' });
    throw new ApiError('无法连接本地服务（127.0.0.1:8791），请确认后端已启动', { code: 'network' });
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => request('/health', { timeout: 4000 }),
  printers: () => request('/printers'),
  status: (id, refresh = true) => request(`/printers/${enc(id)}/status?refresh=${refresh ? 1 : 0}`, { timeout: 20000 }),
  discover: () => request('/printers/discover', { method: 'POST', timeout: 45000 }),
  addPrinter: (host) => request('/printers', { method: 'POST', body: { host }, timeout: 30000 }),
  removePrinter: (id) => request(`/printers/${enc(id)}`, { method: 'DELETE' }),
  setDefaultPrinter: (id) => request(`/printers/${enc(id)}/default`, { method: 'POST' }),
  maintenance: (id, action) =>
    request(`/printers/${enc(id)}/maintenance`, { method: 'POST', body: { action }, timeout: 45000 }),

  upload: (fileList) => {
    const form = new FormData();
    Array.from(fileList).forEach((file) => form.append('files', file, file.name));
    return request('/print/upload', { method: 'POST', body: form, timeout: 120000 });
  },
  print: (payload) => request('/print', { method: 'POST', body: payload }),
  job: (id) => request(`/jobs/${id}`),
  jobs: ({ limit = 50, kind = '' } = {}) =>
    request(`/jobs?limit=${limit}${kind ? `&kind=${enc(kind)}` : ''}`),
  cancelJob: (id) => request(`/jobs/${id}/cancel`, { method: 'POST' }),
  pauseJob: (id) => request(`/jobs/${id}/pause`, { method: 'POST' }),
  resumeJob: (id) => request(`/jobs/${id}/resume`, { method: 'POST' }),
  retryJob: (id) => request(`/jobs/${id}/retry`, { method: 'POST', timeout: 60000 }),

  scan: (payload) => request('/scan', { method: 'POST', body: payload, timeout: 45000 }),
  copy: (payload) => request('/copy', { method: 'POST', body: payload, timeout: 150000 }),
  emailScan: (id, payload) =>
    request(`/scans/${id}/email`, { method: 'POST', body: payload || {}, timeout: 60000 }),
  shortcuts: () => request('/shortcuts'),
  addShortcut: (payload) => request('/shortcuts', { method: 'POST', body: payload }),
  runShortcut: (id) => request(`/shortcuts/${id}/run`, { method: 'POST', timeout: 240000 }),
  deleteShortcut: (id) => request(`/shortcuts/${id}`, { method: 'DELETE' }),
  scans: (limit = 50) => request(`/scans?limit=${limit}`),
  deleteScan: (id) => request(`/scans/${id}`, { method: 'DELETE' }),

  settings: () => request('/settings'),
  patchSettings: (patch) => request('/settings', { method: 'PATCH', body: patch }),
  browseDir: () => request('/settings/browse-dir', { method: 'POST' }),
};

/* ==========================================================================
   SSE 客户端
   ========================================================================== */

/**
 * 订阅后端事件。返回取消订阅函数。
 * @param {(type: string, payload: any) => void} handler
 *   type: 'job' | 'jobs' | 'printer' | 'mode'
 */
export function connectEvents(handler) {
  if (isMock) {
    const off = mockSubscribe(handler);
    return () => {
      off();
    };
  }

  let closed = false;
  let source = null;
  let retryTimer = null;
  let pollTimer = null;
  let polling = false;
  let attempt = 0;

  const emit = (type, payload) => {
    if (!closed) handler(type, payload);
  };

  function startPolling() {
    if (polling || closed) return;
    polling = true;
    emit('mode', { mode: 'polling' });
    pollTimer = setInterval(async () => {
      try {
        const data = await api.jobs({ limit: 50 });
        emit('jobs', data.jobs || []);
      } catch {
        /* 轮询失败静默重试 */
      }
    }, 3000);
  }

  function stopPolling() {
    if (!polling) return;
    polling = false;
    clearInterval(pollTimer);
    pollTimer = null;
  }

  function scheduleReconnect() {
    if (closed) return;
    const delay = Math.min(1000 * 2 ** attempt, 15000);
    attempt += 1;
    if (attempt >= 3) startPolling();
    clearTimeout(retryTimer);
    retryTimer = setTimeout(open, delay);
  }

  function open() {
    if (closed) return;
    try {
      source = new EventSource(`${API_BASE}/events`);
    } catch {
      scheduleReconnect();
      return;
    }

    source.onopen = () => {
      attempt = 0;
      stopPolling();
      emit('mode', { mode: 'sse' });
    };

    source.onerror = () => {
      try {
        source.close();
      } catch {
        /* noop */
      }
      source = null;
      scheduleReconnect();
    };

    source.addEventListener('job', (event) => {
      try {
        emit('job', JSON.parse(event.data));
      } catch {
        /* 忽略损坏的事件 */
      }
    });

    source.addEventListener('printer', (event) => {
      try {
        emit('printer', JSON.parse(event.data));
      } catch {
        /* 忽略损坏的事件 */
      }
    });
  }

  open();

  return () => {
    closed = true;
    clearTimeout(retryTimer);
    stopPolling();
    if (source) source.close();
  };
}

/* ==========================================================================
   演示夹具（?mock=1）—— 字段严格对齐 docs/api.md
   ========================================================================== */

const MOCK_KEY = '00000000-0000-0000-0000-000000000000';
const INK_UNKNOWN = urlParams.get('ink') === 'unknown';
const listeners = new Set();
let jobSeq = 120;

function emit(type, payload) {
  listeners.forEach((fn) => {
    try {
      fn(type, payload);
    } catch {
      /* noop */
    }
  });
}

function mockSubscribe(handler) {
  const fn = (type, payload) => handler(type, payload);
  listeners.add(fn);
  return () => listeners.delete(fn);
}

const nowSec = () => Math.floor(Date.now() / 1000);

const MOCK = {
  printer: {
    id: MOCK_KEY,
    name: 'HP Ink Tank Wireless 410 series',
    queue_name: 'HPSERIAL',
    model: 'Ink Tank Wireless 410 series',
    host: '192.168.1.100',
    serial: '000000000010',
    firmware: 'KEP1FN2020AR',
    online: true,
    state: 'idle',
    state_reason: '',
    is_default: true,
    last_seen: nowSec() - 18,
  },
  status: {
    id: MOCK_KEY,
    online: true,
    state: 'idle',
    state_message: '就绪',
    alerts: INK_UNKNOWN ? [] : [{ category: 'supplyLow', message: '三色墨水余量偏低' }],
    supplies: [
      {
        key: 'black',
        label: '黑色墨水',
        color: '#1a1a1a',
        level: INK_UNKNOWN ? -1 : 72,
        state: 'ok',
        kind: 'ink',
      },
      {
        key: 'color',
        label: '三色墨水',
        color: '#0096d6',
        level: INK_UNKNOWN ? -1 : 41,
        state: INK_UNKNOWN ? 'ok' : 'low',
        kind: 'ink',
      },
    ],
    media: { ready: 'iso_a4_210x297mm', tray: 'InputTray1' },
    counters: { total_pages: 1203, scan_pages: 88, jam_events: 0 },
    capabilities: {
      color: true,
      duplex: false,
      scan: true,
      adf: false,
      max_scan_dpi: 1200,
      scan_color_modes: ['BlackAndWhite1', 'Grayscale8', 'RGB24'],
      scan_formats: ['image/jpeg', 'application/pdf'],
      media: ['iso_a4_210x297mm', 'na_letter_8.5x11in', 'na_index-4x6', 'oe_photo-l_3.5x5in'],
    },
  },
  settings: {
    theme: 'system',
    accent: '#0096D6',
    language: 'zh-CN',
    save_dir: 'C:\Users\user\\Pictures\\HP Offline',
    auto_discover: true,
    poll_interval: 10,
    default_printer: MOCK_KEY,
    offline_mode: true,
  },
  jobs: [],
  scans: [],
};

function escXml(str) {
  return String(str).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
}

function svgData(svg) {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function pageSvg(title, page, total) {
  const lines = Array.from({ length: 13 }, (_, i) => {
    const w = i % 5 === 4 ? 300 : 500;
    return `<rect x="52" y="${168 + i * 36}" width="${w}" height="9" rx="4" fill="#DCE0E3"/>`;
  }).join('');
  return svgData(
    `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="330" viewBox="0 0 620 877">
      <rect width="620" height="877" fill="#ffffff"/>
      <rect width="620" height="58" fill="#00658B"/>
      <text x="52" y="38" font-family="Microsoft YaHei, sans-serif" font-size="20" fill="#ffffff">HP Offline · 本地打印</text>
      <text x="52" y="118" font-family="Microsoft YaHei, sans-serif" font-size="30" font-weight="600" fill="#191C1E">${escXml(String(title).replace(/\.[^.]+$/, ''))}</text>
      <rect x="52" y="136" width="132" height="5" fill="#0096D6"/>
      ${lines}
      <rect x="52" y="650" width="516" height="1" fill="#C5C7CA"/>
      <text x="52" y="690" font-family="Microsoft YaHei, sans-serif" font-size="17" fill="#44474A">局域网直连 · 未经过任何云服务</text>
      <text x="52" y="826" font-family="Microsoft YaHei, sans-serif" font-size="16" fill="#75777B">第 ${page} / ${total} 页</text>
    </svg>`
  );
}

function scanSvg() {
  const lines = Array.from({ length: 16 }, (_, i) => {
    const w = i % 6 === 5 ? 360 : 640;
    return `<rect x="96" y="${330 + i * 38}" width="${w}" height="10" rx="5" fill="#D5D9DC"/>`;
  }).join('');
  return svgData(
    `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1273" viewBox="0 0 900 1273">
      <rect width="900" height="1273" fill="#ffffff"/>
      <text x="96" y="128" font-family="Microsoft YaHei, sans-serif" font-size="38" font-weight="600" fill="#191C1E">扫描测试页</text>
      <text x="96" y="176" font-family="Microsoft YaHei, sans-serif" font-size="20" fill="#5D6062">HP Ink Tank Wireless 410 · 300 dpi · 彩色</text>
      <rect x="96" y="204" width="708" height="2" fill="#191C1E"/>
      <rect x="96" y="248" width="330" height="22" rx="4" fill="#00658B" opacity="0.14"/>
      <rect x="96" y="288" width="520" height="14" rx="4" fill="#B9BDC0"/>
      ${lines}
      <rect x="96" y="990" width="708" height="132" rx="6" fill="#F2F4F6" stroke="#C5C7CA"/>
      <text x="120" y="1034" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#44474A">设备</text>
      <text x="120" y="1068" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#44474A">分辨率</text>
      <text x="120" y="1102" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#44474A">色彩模式</text>
      <text x="300" y="1034" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#191C1E">Ink Tank Wireless 410 series</text>
      <text x="300" y="1068" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#191C1E">300 dpi · 2480 × 3508 px</text>
      <text x="300" y="1102" font-family="Microsoft YaHei, sans-serif" font-size="18" fill="#191C1E">RGB24 · JPEG</text>
      <text x="96" y="1210" font-family="Microsoft YaHei, sans-serif" font-size="16" fill="#75777B">扫描时间 2026-10-24 17:55 · 仅保存于本机</text>
    </svg>`
  );
}

function seedJobs() {
  const t = nowSec();
  MOCK.jobs = [
    {
      id: 118,
      kind: 'print',
      printer_id: MOCK_KEY,
      title: '季度报告.pdf',
      state: 'done',
      progress: 1,
      pages_total: 3,
      pages_sent: 3,
      message: '已完成',
      error: null,
      created_at: t - 12 * 60,
      files: ['u_mock_report'],
    },
    {
      id: 117,
      kind: 'scan',
      printer_id: MOCK_KEY,
      title: '扫描件',
      state: 'done',
      progress: 1,
      pages_total: 1,
      pages_sent: 1,
      message: '已完成',
      error: null,
      created_at: t - 68 * 60,
      files: [],
    },
    {
      id: 116,
      kind: 'print',
      printer_id: MOCK_KEY,
      title: '产品手册.pdf',
      state: 'error',
      progress: 0.42,
      pages_total: 8,
      pages_sent: 3,
      message: '进纸盒缺纸',
      error: 'media_empty',
      created_at: t - 3 * 3600,
      files: ['u_mock_manual'],
    },
    {
      id: 115,
      kind: 'print',
      printer_id: MOCK_KEY,
      title: '合同扫描件.pdf',
      state: 'done',
      progress: 1,
      pages_total: 5,
      pages_sent: 5,
      message: '已完成',
      error: null,
      created_at: t - 26 * 3600,
      files: ['u_mock_contract'],
    },
    {
      id: 114,
      kind: 'scan',
      printer_id: MOCK_KEY,
      title: '身份证扫描',
      state: 'done',
      progress: 1,
      pages_total: 1,
      pages_sent: 1,
      message: '已完成',
      error: null,
      created_at: t - 30 * 3600,
      files: [],
    },
    {
      id: 113,
      kind: 'print',
      printer_id: MOCK_KEY,
      title: '照片-4x6.jpg',
      state: 'done',
      progress: 1,
      pages_total: 1,
      pages_sent: 1,
      message: '已完成',
      error: null,
      created_at: t - 49 * 3600,
      files: ['u_mock_photo'],
    },
  ];
}

function seedScans() {
  const t = nowSec();
  const img = scanSvg();
  MOCK.scans = [
    {
      id: 7,
      job_id: 117,
      printer_id: MOCK_KEY,
      format: 'jpeg',
      path: 'C:\Users\user\\Pictures\\HP Offline\\scan_20261024_165512.jpg',
      thumb: img,
      file: img,
      width: 2480,
      height: 3508,
      size: 1675423,
      created_at: t - 68 * 60,
    },
    {
      id: 6,
      job_id: 114,
      printer_id: MOCK_KEY,
      format: 'pdf',
      path: 'C:\Users\user\\Pictures\\HP Offline\\scan_20261023_183004.pdf',
      thumb: img,
      file: img,
      width: 2480,
      height: 3508,
      size: 2210334,
      created_at: t - 30 * 3600,
    },
  ];
}

seedJobs();
seedScans();

function startMockJob(kind, meta = {}) {
  const id = ++jobSeq;
  const total = Math.max(1, meta.pages || 1);
  const job = {
    id,
    kind,
    printer_id: MOCK_KEY,
    title: meta.title || (kind === 'scan' ? '扫描件' : '文档'),
    state: 'queued',
    progress: 0,
    pages_total: total,
    pages_sent: 0,
    message: '已加入队列',
    error: null,
    created_at: nowSec(),
    files: meta.files || [],
    scan_options: meta.scanOptions || null,
  };
  MOCK.jobs.unshift(job);
  emit('job', { ...job });

  let step = 0;
  const timer = setInterval(() => {
    step += 1;
    const current = MOCK.jobs.find((item) => item.id === id);
    if (!current) {
      clearInterval(timer);
      return;
    }
    if (step === 1) {
      current.state = 'preparing';
      current.message = kind === 'scan' ? '正在连接扫描单元' : '正在准备打印数据';
      current.progress = 0.04;
    } else if (step === 2) {
      current.state = 'sending';
      current.message = kind === 'scan' ? '正在扫描第 1 页' : `正在发送第 1/${total} 页`;
      current.pages_sent = kind === 'scan' ? 0 : 1;
      current.progress = 0.16;
    } else if (step <= total + 2) {
      const done = step - 2;
      current.state = 'sending';
      current.pages_sent = Math.min(done, total);
      current.progress = Math.min(0.94, 0.16 + (0.72 * done) / total);
      current.message = kind === 'scan' ? '正在接收扫描数据' : `正在发送第 ${Math.min(done, total)}/${total} 页`;
    } else if (step === total + 3) {
      current.state = 'printing';
      current.progress = 0.97;
      current.message = kind === 'scan' ? '正在生成扫描文件' : '打印机正在输出';
    } else {
      current.state = 'done';
      current.progress = 1;
      current.pages_sent = total;
      current.message = '已完成';
      clearInterval(timer);
      if (kind === 'scan') finishMockScan(current);
    }
    emit('job', { ...current });
  }, 620);

  return job;
}

function finishMockScan(job) {
  const id = MOCK.scans.reduce((max, item) => Math.max(max, item.id), 0) + 1;
  const img = scanSvg();
  const stamp = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const name = `scan_${stamp.getFullYear()}${pad(stamp.getMonth() + 1)}${pad(stamp.getDate())}_${pad(stamp.getHours())}${pad(stamp.getMinutes())}${pad(stamp.getSeconds())}`;
  const opts = job.scan_options || {};
  const fmt = opts.format || 'jpeg';
  MOCK.scans.unshift({
    id,
    job_id: job.id,
    printer_id: MOCK_KEY,
    format: fmt,
    path: `C:\Users\user\\Pictures\\HP Offline\\${name}.${fmt === 'pdf' ? 'pdf' : 'jpg'}`,
    thumb: img,
    file: img,
    width: 2480,
    height: 3508,
    size: 1675423,
    created_at: nowSec(),
  });
  emit('scan', MOCK.scans[0]);
}

function fail(status, message, code) {
  const err = new ApiError(message, { status, code: code || 'mock' });
  return Promise.reject(err);
}

async function mockRequest(path, { method = 'GET', body } = {}) {
  await sleep(140 + Math.random() * 160);
  const [rawPath, rawQuery] = path.split('?');
  const query = new URLSearchParams(rawQuery || '');

  if (rawPath === '/health' && method === 'GET') {
    return { ok: true, version: '1.0.0', python: '3.10.11', cloud_calls: 0 };
  }

  if (rawPath === '/printers' && method === 'GET') {
    const printers = MOCK.printer ? [MOCK.printer] : [];
    return { printers };
  }

  if (rawPath === '/printers' && method === 'POST') {
    const host = (body && body.host ? String(body.host) : '').trim();
    if (!host) return fail(400, '请填写打印机 IP 地址', 'bad_request');
    if (MOCK.printer && MOCK.printer.host === host) return fail(409, '该打印机已注册', 'exists');
    MOCK.printer = {
      ...MOCK.printer,
      id: `mock-${host.replace(/\./g, '-')}`,
      host,
      name: 'HP LaserJet Pro M404dn',
      model: 'LaserJet Pro M404dn',
      queue_name: 'HPM404',
      serial: 'VNC3K00012',
      firmware: '002.2239A',
      state: 'idle',
      online: true,
      is_default: !MOCK.printer,
      last_seen: nowSec(),
    };
    return MOCK.printer;
  }

  if (rawPath === '/printers/discover' && method === 'POST') {
    return {
      found: [
        {
          host: '192.168.1.100',
          model: 'Ink Tank Wireless 410 series',
          serial: '000000000010',
          uuid: MOCK_KEY,
          source: 'mdns',
        },
        {
          host: '192.168.1.100',
          model: 'LaserJet Pro M404dn',
          serial: 'VNC3K00012',
          uuid: '2d9b41f0-7a3c-4c11-9e55-00a0c9d1b2e4',
          source: 'wsd',
        },
      ],
    };
  }

  const statusMatch = rawPath.match(/^\/printers\/([^/]+)\/status$/);
  if (statusMatch && method === 'GET') {
    if (!MOCK.printer || statusMatch[1] !== MOCK.printer.id) return fail(404, '打印机不存在', 'not_found');
    MOCK.status.online = MOCK.printer.online;
    return { ...MOCK.status, id: MOCK.printer.id };
  }

  const maintMatch = rawPath.match(/^\/printers\/([^/]+)\/maintenance$/);
  if (maintMatch && method === 'POST') {
    const labels = {
      clean: '已开始清洗打印头，预计 60 秒完成',
      align: '已开始打印头对齐',
      calibrate: '已开始色彩校准，请稍候',
      report: '打印机状态报告已发送至打印队列',
    };
    return { ok: true, detail: labels[body && body.action] || '指令已发送' };
  }

  const defaultMatch = rawPath.match(/^\/printers\/([^/]+)\/default$/);
  if (defaultMatch && method === 'POST') {
    if (!MOCK.printer) return fail(404, '打印机不存在', 'not_found');
    MOCK.printer.is_default = true;
    MOCK.settings.default_printer = MOCK.printer.id;
    return { ok: true };
  }

  const printerMatch = rawPath.match(/^\/printers\/([^/]+)$/);
  if (printerMatch && method === 'DELETE') {
    if (!MOCK.printer || printerMatch[1] !== MOCK.printer.id) return fail(404, '打印机不存在', 'not_found');
    MOCK.printer = null;
    return null;
  }

  if (rawPath === '/print/upload' && method === 'POST') {
    const files = [];
    const entries = body && typeof body.getAll === 'function' ? body.getAll('files') : [];
    entries.forEach((file, index) => {
      const pages = Math.min(6, Math.max(1, Math.ceil((file.name || '').length / 6)));
      const token = `u_mock_${Date.now().toString(36)}_${index}`;
      files.push({
        token,
        name: file.name || `文档_${index + 1}.pdf`,
        kind: /\.pdf$/i.test(file.name || '') ? 'pdf' : 'image',
        pages,
        size: file.size || 812345,
        thumbs: Array.from({ length: pages }, (_, page) => pageSvg(file.name || '文档', page + 1, pages)),
      });
    });
    if (!files.length) return fail(400, '没有可上传的文件', 'no_files');
    return { files };
  }

  if (rawPath === '/print' && method === 'POST') {
    if (!MOCK.printer) return fail(409, '尚未注册打印机', 'no_printer');
    const tokens = (body && body.files) || [];
    const totalPages = Math.max(1, tokens.length * 2);
    const job = startMockJob('print', {
      title: tokens.length > 1 ? `${tokens.length} 个文件` : '打印文档.pdf',
      pages: totalPages,
      files: tokens,
    });
    return { job_id: job.id };
  }

  if (rawPath === '/jobs' && method === 'GET') {
    const kind = query.get('kind') || '';
    const limit = Number(query.get('limit') || 50);
    const jobs = MOCK.jobs.filter((job) => !kind || job.kind === kind).slice(0, limit);
    return { jobs: jobs.map(({ scan_options, ...rest }) => rest) };
  }

  const jobMatch = rawPath.match(/^\/jobs\/(\d+)$/);
  if (jobMatch && method === 'GET') {
    const job = MOCK.jobs.find((item) => item.id === Number(jobMatch[1]));
    if (!job) return fail(404, '作业不存在', 'not_found');
    return job;
  }

  const cancelMatch = rawPath.match(/^\/jobs\/(\d+)\/cancel$/);
  if (cancelMatch && method === 'POST') {
    const job = MOCK.jobs.find((item) => item.id === Number(cancelMatch[1]));
    if (!job) return fail(404, '作业不存在', 'not_found');
    job.state = 'canceled';
    job.message = '已取消';
    emit('job', { ...job });
    return { ok: true };
  }

  if (rawPath === '/scan' && method === 'POST') {
    if (!MOCK.printer) return fail(409, '尚未注册打印机', 'no_printer');
    const options = (body && body.options) || {};
    const job = startMockJob('scan', {
      title: '扫描件',
      pages: 1,
      scanOptions: options,
    });
    return { job_id: job.id };
  }

  if (rawPath === '/scans' && method === 'GET') {
    const limit = Number(query.get('limit') || 50);
    return { scans: MOCK.scans.slice(0, limit) };
  }

  const scanMatch = rawPath.match(/^\/scans\/(\d+)$/);
  if (scanMatch && method === 'DELETE') {
    const id = Number(scanMatch[1]);
    const before = MOCK.scans.length;
    MOCK.scans = MOCK.scans.filter((item) => item.id !== id);
    if (MOCK.scans.length === before) return fail(404, '扫描记录不存在', 'not_found');
    return null;
  }

  if (rawPath === '/settings' && method === 'GET') {
    return { ...MOCK.settings };
  }

  if (rawPath === '/settings' && method === 'PATCH') {
    Object.assign(MOCK.settings, body || {});
    return { ...MOCK.settings };
  }

  if (rawPath === '/settings/browse-dir' && method === 'POST') {
    return { path: MOCK.settings.save_dir };
  }

  return fail(404, `演示模式未实现该接口：${rawPath}`, 'mock_unimplemented');
}
