/**
 * components/feedback.js — 骨架屏、空状态、错误态、横幅与 Snackbar
 */

import { h, button, iconButton } from './ui.js';
import { icon } from '../../icons.js';

/* -------------------------------------------------------------------------- */
/* 骨架屏                                                                      */
/* -------------------------------------------------------------------------- */

export function skeleton({ width = '100%', height = 16, radius = 8, class: extra = '' } = {}) {
  return h('div', {
    class: `skeleton${extra ? ` ${extra}` : ''}`,
    style: { width, height: typeof height === 'number' ? `${height}px` : height, borderRadius: `${radius}px` },
    'aria-hidden': 'true',
  });
}

export function skeletonLines(count = 3, { widths = ['100%', '92%', '64%'] } = {}) {
  return h(
    'div',
    { class: 'skeleton-lines', 'aria-hidden': 'true' },
    Array.from({ length: count }, (_, i) => skeleton({ width: widths[i % widths.length], height: 12, radius: 6 }))
  );
}

export function skeletonCard({ lines = 3, title = true, media = false } = {}) {
  return h(
    'div',
    { class: 'card skeleton-card', 'aria-hidden': 'true' },
    media ? skeleton({ height: 132, radius: 12 }) : null,
    title ? skeleton({ width: '42%', height: 20, radius: 6 }) : null,
    skeletonLines(lines)
  );
}

export function skeletonRows(count = 4) {
  return h(
    'div',
    { class: 'skeleton-rows', 'aria-hidden': 'true' },
    Array.from({ length: count }, () =>
      h(
        'div',
        { class: 'skeleton-row' },
        skeleton({ width: 36, height: 36, radius: 10 }),
        h('div', { class: 'skeleton-row-text' }, skeleton({ width: '38%', height: 13 }), skeleton({ width: '22%', height: 11 }))
      )
    )
  );
}

export function spinner(size = 20, label = '加载中') {
  return h(
    'span',
    { class: 'spinner', style: { width: `${size}px`, height: `${size}px` }, role: 'status', 'aria-label': label }
  );
}

/* -------------------------------------------------------------------------- */
/* 空状态 / 错误态                                                             */
/* -------------------------------------------------------------------------- */

export function emptyState({ icon: iconName = 'info', title, description, action, tone = 'neutral' }) {
  return h(
    'div',
    { class: `empty empty-${tone}` },
    h('div', { class: 'empty-icon' }, icon(iconName, 26)),
    h('p', { class: 'empty-title', text: title }),
    description ? h('p', { class: 'empty-desc', text: description }) : null,
    action ? h('div', { class: 'empty-action' }, action) : null
  );
}

export function errorState({ title = '加载失败', message, retry, retryLabel = '重试' }) {
  return emptyState({
    icon: 'warning',
    title,
    description: message || '本地服务未返回数据，请稍后重试。',
    tone: 'error',
    action: retry ? button({ label: retryLabel, icon: 'refresh', variant: 'tonal', onclick: retry }) : null,
  });
}

/* -------------------------------------------------------------------------- */
/* 横幅                                                                        */
/* -------------------------------------------------------------------------- */

export function banner({ tone = 'warning', icon: iconName = 'warning', title, message, action, onClose }) {
  return h(
    'div',
    { class: `banner banner-${tone}`, role: tone === 'error' ? 'alert' : 'status' },
    h('span', { class: 'banner-icon' }, icon(iconName, 20)),
    h(
      'div',
      { class: 'banner-text' },
      h('strong', { class: 'banner-title', text: title }),
      message ? h('span', { class: 'banner-message', text: message }) : null
    ),
    action ? h('div', { class: 'banner-action' }, action) : null,
    onClose ? iconButton({ icon: 'close', label: '关闭提示', size: 18, onclick: onClose }) : null
  );
}

/* -------------------------------------------------------------------------- */
/* Snackbar（MD3）                                                             */
/* -------------------------------------------------------------------------- */

const MAX_TOASTS = 3;

export function toast(message, { tone = 'default', actionLabel, onAction, duration = 4200, id } = {}) {
  const root = document.getElementById('toast-root');
  if (!root) return () => {};

  if (id) {
    const existing = root.querySelector(`[data-toast-id="${id}"]`);
    if (existing) existing.remove();
  }

  while (root.children.length >= MAX_TOASTS) root.firstElementChild.remove();

  const bar = h('div', {
    class: `snackbar snackbar-${tone}`,
    role: tone === 'error' ? 'alert' : 'status',
    dataset: id ? { toastId: id } : {},
  });

  bar.append(
    h(
      'div',
      { class: 'snackbar-main' },
      tone === 'error' ? icon('error', 18) : tone === 'success' ? icon('checkCircle', 18) : null,
      h('span', { class: 'snackbar-text', text: message })
    )
  );

  if (actionLabel && onAction) {
    bar.append(
      h('button', {
        class: 'snackbar-action',
        type: 'button',
        text: actionLabel,
        onclick: () => {
          onAction();
          dismiss();
        },
      })
    );
  }

  let timer = setTimeout(dismiss, duration);

  function dismiss() {
    clearTimeout(timer);
    if (!bar.isConnected) return;
    bar.classList.add('is-leaving');
    setTimeout(() => bar.remove(), 180);
  }

  bar.addEventListener('mouseenter', () => clearTimeout(timer));
  bar.addEventListener('mouseleave', () => {
    timer = setTimeout(dismiss, 1600);
  });

  root.append(bar);
  return dismiss;
}
