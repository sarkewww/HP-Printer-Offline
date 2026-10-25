/**
 * icons.js — 内联 SVG 图标集（Material Symbols 轮廓风格，24×24，1.7px 描边）
 *
 * 离线约束：不使用任何图标字体或 CDN，所有路径内联在此文件中。
 * 用法：icon('print', 20)  →  <svg class="icon" width="20" height="20">…</svg>
 */

const P = {
  home: '<path d="M4 10.6 12 4l8 6.6V19a1.4 1.4 0 0 1-1.4 1.4h-4.1v-6.2H9.5v6.2H5.4A1.4 1.4 0 0 1 4 19z"/>',

  print:
    '<path d="M7 9V4h10v5"/><path d="M7 18H5.5A2.5 2.5 0 0 1 3 15.5v-4A2.5 2.5 0 0 1 5.5 9h13a2.5 2.5 0 0 1 2.5 2.5v4A2.5 2.5 0 0 1 18.5 18H17"/><rect x="7" y="14" width="10" height="6" rx="1"/><circle cx="16.7" cy="12" r=".9" fill="currentColor" stroke="none"/>',

  scan:
    '<path d="M4 8.5V6a2 2 0 0 1 2-2h2.5"/><path d="M15.5 4H18a2 2 0 0 1 2 2v2.5"/><path d="M20 15.5V18a2 2 0 0 1-2 2h-2.5"/><path d="M8.5 20H6a2 2 0 0 1-2-2v-2.5"/><path d="M3.5 12h17"/>',

  history:
    '<path d="M3.6 12a8.5 8.5 0 1 0 2.8-6.3"/><path d="M3.6 4.5V9H8"/><path d="M12 7.8V12l3 1.8"/>',

  settings:
    '<path d="M12.22 3h-.44a1.9 1.9 0 0 0-1.9 1.9v.17a1.9 1.9 0 0 1-.95 1.64l-.41.24a1.9 1.9 0 0 1-1.9 0l-.14-.08a1.9 1.9 0 0 0-2.6.7l-.21.36a1.9 1.9 0 0 0 .7 2.6l.14.09a1.9 1.9 0 0 1 .95 1.64v.48a1.9 1.9 0 0 1-.95 1.65l-.14.08a1.9 1.9 0 0 0-.7 2.6l.21.36a1.9 1.9 0 0 0 2.6.7l.14-.08a1.9 1.9 0 0 1 1.9 0l.41.24a1.9 1.9 0 0 1 .95 1.64v.17A1.9 1.9 0 0 0 11.78 21h.44a1.9 1.9 0 0 0 1.9-1.9v-.17a1.9 1.9 0 0 1 .95-1.64l.41-.24a1.9 1.9 0 0 1 1.9 0l.14.08a1.9 1.9 0 0 0 2.6-.7l.21-.37a1.9 1.9 0 0 0-.7-2.6l-.14-.07a1.9 1.9 0 0 1-.95-1.65v-.48a1.9 1.9 0 0 1 .95-1.65l.14-.08a1.9 1.9 0 0 0 .7-2.6l-.21-.36a1.9 1.9 0 0 0-2.6-.7l-.14.08a1.9 1.9 0 0 1-1.9 0l-.41-.24a1.9 1.9 0 0 1-.95-1.64V4.9A1.9 1.9 0 0 0 12.22 3Z"/><circle cx="12" cy="12" r="3.1"/>',

  folder:
    '<path d="M3 7.4A2.4 2.4 0 0 1 5.4 5h3.1a2 2 0 0 1 1.6.8l.9 1.3a2 2 0 0 0 1.6.8h5.8A2.4 2.4 0 0 1 21 10.3v7.3A2.4 2.4 0 0 1 18.6 20H5.4A2.4 2.4 0 0 1 3 17.6z"/>',

  file:
    '<path d="M14 3.5H7A2 2 0 0 0 5 5.5v13A2 2 0 0 0 7 20.5h10a2 2 0 0 0 2-2V8.5z"/><path d="M14 3.5v5h5"/>',

  fileText:
    '<path d="M14 3.5H7A2 2 0 0 0 5 5.5v13A2 2 0 0 0 7 20.5h10a2 2 0 0 0 2-2V8.5z"/><path d="M14 3.5v5h5"/><path d="M8.5 13h7M8.5 16.5h4.5"/>',

  upload:
    '<path d="M12 16V4.5"/><path d="M7.5 9 12 4.5 16.5 9"/><path d="M4.5 15v3.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5V15"/>',

  download:
    '<path d="M12 4v11"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M4.5 19.5h15"/>',

  trash:
    '<path d="M4 7h16"/><path d="M9.5 7V5.2a1.2 1.2 0 0 1 1.2-1.2h2.6a1.2 1.2 0 0 1 1.2 1.2V7"/><path d="M6.2 7 7 19.1a1.8 1.8 0 0 0 1.8 1.7h6.4a1.8 1.8 0 0 0 1.8-1.7L17.8 7"/><path d="M10.5 11v6M13.5 11v6"/>',

  refresh:
    '<path d="M20.4 12a8.4 8.4 0 1 1-2.6-6.1"/><path d="M20.4 3.6V9H15"/>',

  close: '<path d="M6 6l12 12M18 6 6 18"/>',

  check: '<path d="M4.5 12.5 9.5 17.5 19.5 6.5"/>',

  checkCircle:
    '<circle cx="12" cy="12" r="8.5"/><path d="M8.2 12.2l2.6 2.6 5-5.2"/>',

  xCircle:
    '<circle cx="12" cy="12" r="8.5"/><path d="M9 9l6 6M15 9l-6 6"/>',

  warning:
    '<path d="M12 3.8 21.2 20H2.8z"/><path d="M12 9.5v4.7"/><circle cx="12" cy="17.3" r=".85" fill="currentColor" stroke="none"/>',

  info:
    '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.2"/><circle cx="12" cy="8" r=".9" fill="currentColor" stroke="none"/>',

  error:
    '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5.4"/><circle cx="12" cy="16.4" r=".9" fill="currentColor" stroke="none"/>',

  clock:
    '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.4V12l3.2 2"/>',

  chevronDown: '<path d="M5.5 9.5 12 16l6.5-6.5"/>',
  chevronRight: '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
  chevronLeft: '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
  arrowRight: '<path d="M4.5 12h14"/><path d="M13 6.5 18.5 12 13 17.5"/>',

  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',

  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l4.5 4.5"/>',

  cloudOff:
    '<path d="M7 18h10.2a3.8 3.8 0 0 0 1-7.5A6 6 0 0 0 8.2 7"/><path d="M6.4 9.4A4.3 4.3 0 0 0 7 18"/><path d="M3.5 3.5l17 17"/>',

  droplet:
    '<path d="M12 3.6c2.9 3.3 5.6 6.2 5.6 9.4a5.6 5.6 0 0 1-11.2 0c0-3.2 2.7-6.1 5.6-9.4Z"/>',

  wrench:
    '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',

  external:
    '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5 11 13"/><path d="M18.5 14v4.5a1.5 1.5 0 0 1-1.5 1.5H5.5A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',

  palette:
    '<path d="M12 3.2a8.8 8.8 0 1 0 0 17.6c1.3 0 2-.9 2-1.9 0-1.3-1-1.7-1-2.9 0-1 .8-1.8 1.8-1.8h2.1a3.9 3.9 0 0 0 3.9-3.9c0-3.9-3.9-7.1-8.8-7.1Z"/><circle cx="8" cy="10" r="1.05" fill="currentColor" stroke="none"/><circle cx="12" cy="7.6" r="1.05" fill="currentColor" stroke="none"/><circle cx="16" cy="10" r="1.05" fill="currentColor" stroke="none"/><circle cx="7.6" cy="14.4" r="1.05" fill="currentColor" stroke="none"/>',

  sun:
    '<circle cx="12" cy="12" r="4"/><path d="M12 2.6v2M12 19.4v2M2.6 12h2M19.4 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4"/>',

  moon: '<path d="M20 14.2A8.4 8.4 0 0 1 9.8 4a8.5 8.5 0 1 0 10.2 10.2Z"/>',

  monitor:
    '<rect x="3" y="4.5" width="18" height="12" rx="1.8"/><path d="M9 20h6M12 16.5V20"/>',

  wifi:
    '<path d="M3.5 9.2a13 13 0 0 1 17 0"/><path d="M6.4 12.5a9 9 0 0 1 11.2 0"/><path d="M9.2 15.8a5.2 5.2 0 0 1 5.6 0"/><circle cx="12" cy="19" r=".9" fill="currentColor" stroke="none"/>',

  link:
    '<path d="M10 13.5a4 4 0 0 0 5.7 0l2.8-2.8a4 4 0 1 0-5.7-5.7L11.5 6.3"/><path d="M14 10.5a4 4 0 0 0-5.7 0L5.5 13.3a4 4 0 1 0 5.7 5.7l1.3-1.3"/>',

  pause: '<rect x="8" y="5" width="2.6" height="14" rx="1"/><rect x="13.4" y="5" width="2.6" height="14" rx="1"/>',
  play: '<path d="M8 5.5v13l11-6.5z"/>',
  copy:
    '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="1.8"/><path d="M15.5 5.5v-.8A1.7 1.7 0 0 0 13.8 3H5.7A1.7 1.7 0 0 0 4 4.7v8.1a1.7 1.7 0 0 0 1.7 1.7h.8"/>',

  image:
    '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="9.5" r="1.6"/><path d="M4 17.5 9.5 12l3.4 3.4 2.6-2.6 4.5 4.5"/>',

  list:
    '<path d="M8.5 6.5h11.5M8.5 12h11.5M8.5 17.5h11.5"/><circle cx="4.7" cy="6.5" r="1" fill="currentColor" stroke="none"/><circle cx="4.7" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="4.7" cy="17.5" r="1" fill="currentColor" stroke="none"/>',

  tune:
    '<path d="M4 7h8M16 7h4M4 17h4M12 17h8"/><circle cx="14" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',

  crop:
    '<path d="M6.5 3.5v14h14"/><path d="M3.5 6.5h14v14"/>',

  rotate:
    '<path d="M20 11.5a8 8 0 1 1-2.6-5.9"/><path d="M20 3.8V9h-5.2"/><path d="M12 8.5v7M9 11.5l3-3 3 3"/>',

  flipHorizontal:
    '<path d="M12 3.5v17"/><path d="M8.5 6.5 4 12l4.5 5.5z"/><path d="M15.5 6.5 20 12l-4.5 5.5z"/>',

  contrast:
    '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v17"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17Z" fill="currentColor" stroke="none"/>',

  more:
    '<circle cx="12" cy="5.5" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="18.5" r="1.4" fill="currentColor" stroke="none"/>',

  dot: '<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/>',
};

export const ICON_NAMES = Object.keys(P);

/**
 * @param {string} name 图标名（见上方 P）
 * @param {number} size 像素尺寸
 * @param {string} cls 附加 class
 * @returns {SVGElement}
 */
export function icon(name, size = 20, cls = '') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.7');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.setAttribute('class', cls ? `icon ${cls}` : 'icon');
  svg.innerHTML = P[name] || P.dot;
  return svg;
}
