/**
 * i18n.js — 界面语言
 *
 * 策略：
 *  - 源码是中文；英文用「中文原文 → 译文」的字典，在渲染后对 DOM 文本与
 *    placeholder/title/aria-label 做替换，避免把 550 处硬编码字符串全部改成 key。
 *  - 语言来源优先级：localStorage → 浏览器 navigator.languages → en-US。
 *  - 动态内容（作业行、toast）由 MutationObserver 兜底翻译。
 *  - 未收录的字符串保持中文，不会出现空白或乱码。
 */

const STORAGE_KEY = 'hp.lang';
const SUPPORTED = ['zh-CN', 'en-US'];

export const LANGS = [
  { value: 'auto', label: '自动（跟随浏览器）', labelEn: 'Auto (browser)' },
  { value: 'zh-CN', label: '简体中文', labelEn: '简体中文' },
  { value: 'en-US', label: 'English', labelEn: 'English' },
];

const EN = {
  // 导航 / 页面
  首页: 'Home', 打印: 'Print', 扫描: 'Scan', 任务: 'Tasks', 打印机: 'Printer', 历史: 'History', 设置: 'Settings',
  主导航: 'Main navigation', 页面内容: 'Page content', 页面列表: 'Page list',
  跳至主要内容: 'Skip to main content', 零云端: 'Zero cloud', 次公网请求: 'outbound requests',
  // 通用
  重试: 'Retry', 取消: 'Cancel', 关闭: 'Close', 删除: 'Delete', 确认: 'Confirm', 保存: 'Save',
  完成: 'Done', 下一步: 'Next', 全部: 'All', 未知: 'Unknown', 默认: 'Default', 自动: 'Auto',
  正常: 'OK', 偏低: 'Low', 已空: 'Empty', 失败: 'Failed', 已取消: 'Canceled', 已完成: 'Completed',
  就绪: 'Ready', 忙碌: 'Busy', 离线: 'Offline', 已停止: 'Stopped', 进度: 'Progress',
  类型: 'Type', 状态: 'Status', 页数: 'Pages', 时间: 'Time', 操作: 'Actions', 版本: 'Version',
  输入框: 'Input', 选择: 'Select', 选项列表: 'Options', 选项: 'Option', 减少: 'Decrease', 增加: 'Increase',
  开关: 'Switch', 滑块: 'Slider', 刚刚: 'just now', 加载中: 'Loading', 加载失败: 'Load failed',
  读取失败: 'Failed to load', 上传失败: 'Upload failed', 作业失败: 'Job failed', 作业进度: 'Job progress',
  // 打印
  打印文档: 'Print documents', 打印照片: 'Print photos', 打印预览: 'Print preview', 打印选项: 'Print options',
  打印质量: 'Print quality', 份数: 'Copies', 质量: 'Quality', 缩放: 'Scaling', 方向: 'Orientation',
  纵向: 'Portrait', 横向: 'Landscape', 彩色: 'Color', 黑白: 'Monochrome', 草稿: 'Draft', 标准: 'Normal', 最佳: 'Best',
  适应页面: 'Fit to page', 铺满页面: 'Fill page', 原始大小: 'Actual size', 纸张: 'Paper', 默认纸张: 'Default paper',
  尚未选择文件: 'No file selected', 选择文件: 'Choose file', 取消本文件: 'Clear this file', 选择本文件: 'Select this file',
  图片: 'Image', 图片编辑: 'Image editor', 应用编辑: 'Apply edits', 重置编辑: 'Reset edits',
  旋转: 'Rotate', 翻转: 'Flip', 裁剪比例: 'Crop ratio',
  当前浏览器不支持画布编辑: 'This browser does not support canvas editing',
  无法读取该图片可能是格式不支持: 'Cannot read this image — the format may be unsupported',
  批量打印: 'Batch print', 单张打印: 'Single print', 份: 'copies',
  // 扫描
  扫描选项: 'Scan options', 开始扫描: 'Start scan', 扫描中: 'Scanning', 正在扫描: 'Scanning…',
  色彩模式: 'Color mode', 亮度: 'Brightness', 对比度: 'Contrast', 文件格式: 'File format',
  文档: 'Document', 照片: 'Photo', 扫描件: 'Scan', 尚无扫描件: 'No scans yet', 扫描页数: 'Pages scanned',
  自动裁切: 'Auto crop', 自动纠偏: 'Auto deskew', 自动增强: 'Auto enhance', PDF密码: 'PDF password',
  生成可搜索PDF: 'Create searchable PDF', 导出: 'Export',
  // 状态
  排队中: 'Queued', 准备中: 'Preparing', 发送中: 'Sending', 打印中: 'Printing', 已暂停: 'Paused',
  未命名作业: 'Untitled job', 未命名任务: 'Untitled task', 未命名打印机: 'Unnamed printer',
  取消作业: 'Cancel job', 重新打印: 'Print again', 删除扫描记录: 'Delete scan',
  该作业没有保留源文件无法重新打印: 'No source file kept for this job — cannot reprint',
  打印作业不支持删除: 'Print jobs cannot be deleted',
  // 任务 / 历史
  作业历史: 'Job history', 作业类型筛选: 'Filter by job type', 还没有作业记录: 'No job history yet',
  完成一次打印或扫描后记录会显示在这里: 'Records will appear here after a print or scan.',
  去打印: 'Go to print', 去扫描: 'Go to scan', 去注册: 'Register now', 查看全部: 'View all',
  最近打印: 'Recent prints', 基础信息: 'Basic', 高级参数: 'Advanced', 作业详情视图: 'Job detail view',
  任务名称: 'Job name', 色彩: 'Color', 提交时间: 'Submitted', 最后更新: 'Last updated', 耗时: 'Duration',
  结果说明: 'Result', 作业ID: 'Job ID', 打印机ID: 'Printer ID', 打印机地址: 'Printer address',
  IPP作业ID: 'IPP job ID', 源文件token: 'Source tokens', 创建时间戳: 'Created timestamp',
  更新时间戳: 'Updated timestamp', 错误详情: 'Error details', 完整参数: 'Full options',
  // 打印机 / 设备
  当前打印机: 'Current printer', 尚未注册打印机: 'No printer registered', 发现打印机: 'Discover printers',
  手动指定IP: 'Enter IP manually', 打印机当前离线: 'Printer is offline', 打印机离线: 'Printer offline',
  打印机不存在: 'Printer not found', 作业不存在: 'Job not found', 设备能力: 'Capabilities',
  设备信息: 'Device info', 注册: 'Register', 默认打印机: 'Default printer', 刷新打印机状态: 'Refresh printer status',
  累计页数: 'Total pages', 当前状态: 'Current state', 打印机详情: 'Printer details', IP地址: 'IP address',
  墨水余量: 'Ink levels', 墨水: 'Ink', 黑色墨水: 'Black ink', 三色墨水: 'Tri-color ink',
  黑色: 'Black', 青色: 'Cyan', 品红: 'Magenta', 黄色: 'Yellow',
  墨仓式无电子墨量设备仅上报墨仓状态不提供百分比: 'Ink tank — the device reports tank state only, not a percentage.',
  设备未上报耗材信息: 'The device did not report supply information',
  此打印机可能不支持耗材查询: 'This printer may not support supply queries.',
  连接恢复后会自动读取墨水余量: 'Ink levels will load once the connection is restored.',
  余量偏低: 'Running low', 维护: 'Maintenance', 清洗校准状态报告: 'Clean · Align · Status report',
  // 设置
  主题: 'Theme', 强调色: 'Accent color', 保存目录: 'Save folder', 自动发现: 'Auto discover',
  轮询间隔: 'Poll interval', 邮件: 'Email', SMTP主机: 'SMTP host', SMTP端口: 'SMTP port',
  SMTP账号: 'SMTP user', 发件人: 'From', 默认收件人: 'Default recipient', 启用TLS: 'Enable TLS',
  切换深浅色主题: 'Toggle light/dark theme', 切换到浅色主题: 'Switch to light theme',
  切换到深色主题: 'Switch to dark theme', 当前跟随系统主题: 'Following system theme',
  快捷方式: 'Shortcuts', 邮件本地SMTP: 'Email (local SMTP)', 关于: 'About',
  // 错误 / 提示
  请求超时本地服务未响应: 'Request timed out — local service is not responding',
  无法连接本地服务: 'Cannot reach the local service',
  打印机当前离线无法提交打印: 'Printer is offline — cannot submit the job',
  尚未选择打印机: 'No printer selected', 请填写打印机IP地址: 'Please enter the printer IP address',
  没有可上传的文件: 'No file to upload', 扫描记录不存在: 'Scan record not found',
  模拟数据: 'Sample data', 服务未连接: 'Service not connected', 本地服务未连接: 'Local service not connected',
  界面初始化失败: 'Failed to initialize the UI', 请刷新页面重试: 'Please refresh the page.',
  本地服务未返回数据请稍后重试: 'The local service returned no data. Try again shortly.',
  关闭提示: 'Dismiss', 重试连接: 'Reconnect', 已重新连接本地服务: 'Reconnected to the local service',
  仍然无法连接请检查后端进程: 'Still unreachable — check the backend process',
  已注册打印机: 'Printer registered', 未注册打印机: 'No printer registered',
  已加入队列: 'Added to queue', 正在准备打印数据: 'Preparing print data',
  正在接收扫描数据: 'Receiving scan data', 正在生成扫描文件: 'Building scan file',
  打印机正在输出: 'Printer is printing', 该打印机已注册: 'This printer is already registered',
  指令已发送: 'Command sent',
  语言: 'Language', 界面语言: 'Interface language',
  默认跟随浏览器语言也可以手动指定: 'Follows the browser language by default; you can override it.',
  外观: 'Appearance', 主题与强调色立即生效: 'Theme and accent apply immediately',
  深色模式使用独立的色调梯度而不是简单反色: 'Dark mode uses its own tonal palette, not a simple inversion.',
  自动跟随浏览器: 'Auto (browser)',  // 复印
  复印: 'Copy', 复印颜色: 'Copy color', 开始复印: 'Start copy',
  把原件放在扫描仪玻璃板上点开始复印打印机会先扫描再打印全程离线: 'Place the original on the scanner glass and tap Start copy. The printer scans then prints — fully offline.',
  // 快捷方式
  正在执行上一个快捷方式请稍候: 'A shortcut is still running — please wait',
  快捷方式执行失败: 'Shortcut failed',
};

const PATTERNS = [
  [/^(\d+) \/ (\d+) 页$/, '$1 / $2 pages'],
  [/^共 (\d+) 页$/, '$1 pages'],
  [/^(\d+) 页$/, '$1 pages'],
  [/^(\d+) 份$/, '$1 copies'],
  [/^(\d+) 次公网请求$/, '$1 outbound requests'],
  [/^(\d+) 个任务$/, '$1 jobs'],
  [/^(\d+) 个进行中$/, '$1 running'],
  [/^共 (\d+) 色$/, '$1 colors'],
  [/^第 (\d+) \/ (\d+) 页$/, 'Page $1 of $2'],
  [/^已提交 (\d+) 个作业$/, '$1 jobs submitted'],
];

const DICTS = { 'zh-CN': null, 'en-US': EN };

let currentLang = 'zh-CN';
let observer = null;
let applying = false;
let timer = null;
const listeners = new Set();

function normalizeKey(text) {
  return String(text || '')
    .replace(/\s+/g, '')
    .replace(/[：:，,。.、；;！!？?（）()「」“”"'\s]/g, '');
}

const NORMALIZED = new Map(Object.entries(EN).map(([k, v]) => [normalizeKey(k), v]));

function lookup(text) {
  if (currentLang === 'zh-CN') return null;
  const direct = EN[text];
  if (direct) return direct;
  const norm = NORMALIZED.get(normalizeKey(text));
  if (norm) return norm;
  for (const [rx, rep] of PATTERNS) {
    if (rx.test(text)) return text.replace(rx, rep);
  }
  return null;
}

export function t(text) {
  const hit = lookup(text);
  return hit || text;
}

export function matchLang(tag) {
  const t = String(tag || '').toLowerCase();
  if (t.startsWith('zh')) return 'zh-CN';
  if (t.startsWith('en')) return 'en-US';
  return null;
}

export function resolveLang(pref) {
  if (pref && pref !== 'auto') {
    const m = matchLang(pref);
    if (m) return m;
  }
  const list = (navigator.languages && navigator.languages.length)
    ? navigator.languages
    : [navigator.language || 'en-US'];
  for (const tag of list) {
    const m = matchLang(tag);
    if (m) return m;
  }
  return 'en-US';
}

export function getPref() {
  try {
    return localStorage.getItem(STORAGE_KEY) || 'auto';
  } catch {
    return 'auto';
  }
}

export function getLang() {
  return currentLang;
}

function translateNode(node) {
  const raw = node.nodeValue;
  if (!raw) return;
  const key = raw.trim();
  if (!key) return;
  const hit = lookup(key);
  if (!hit || hit === key) return;
  node.nodeValue = raw.replace(key, hit);
}

function translateAttributes(root) {
  const sel = '[placeholder],[title],[aria-label]';
  root.querySelectorAll(sel).forEach((el) => {
    ['placeholder', 'title', 'aria-label'].forEach((attr) => {
      const value = el.getAttribute(attr);
      if (!value) return;
      const hit = lookup(value.trim());
      if (hit && hit !== value) el.setAttribute(attr, hit);
    });
  });
}

export function apply(root = document.body) {
  if (!root || currentLang === 'zh-CN') return;
  if (applying) return;
  applying = true;
  try {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const nodes = [];
    let node = walker.nextNode();
    while (node) {
      nodes.push(node);
      node = walker.nextNode();
    }
    nodes.forEach(translateNode);
    if (root.querySelectorAll) translateAttributes(root);
  } finally {
    applying = false;
  }
}

function scheduleApply() {
  if (currentLang === 'zh-CN') return;
  if (timer) return;
  timer = setTimeout(() => {
    timer = null;
    apply(document.body);
  }, 40);
}

export function startObserver() {
  if (observer || typeof MutationObserver === 'undefined') return;
  observer = new MutationObserver(() => {
    if (applying) return;
    scheduleApply();
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}

export function setLang(pref, { persist = true } = {}) {
  const next = resolveLang(pref);
  if (persist) {
    try {
      localStorage.setItem(STORAGE_KEY, pref);
    } catch {}
  }
  const changed = next !== currentLang;
  currentLang = next;
  document.documentElement.setAttribute('lang', next === 'zh-CN' ? 'zh-CN' : 'en');
  if (changed) {
    // 中文是源码语言，切回中文需要刷新才能还原被替换过的文本
    if (next === 'zh-CN' && document.body.dataset.i18nApplied === '1') {
      listeners.forEach((fn) => fn(next));
      window.location.reload();
      return;
    }
    document.body.dataset.i18nApplied = next === 'zh-CN' ? '0' : '1';
    apply(document.body);
    listeners.forEach((fn) => fn(next));
  }
}

export function onChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function init() {
  setLang(getPref(), { persist: false });
  startObserver();
  return currentLang;
}

export function langLabel(pref) {
  const item = LANGS.find((l) => l.value === pref);
  return item ? item.label : pref;
}

export { SUPPORTED };
