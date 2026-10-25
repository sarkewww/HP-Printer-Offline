/**
 * components/ui.js — Material 3 基础组件与格式化工具
 * 所有组件都是原生元素 + ARIA，键盘可操作，不依赖框架。
 */

import { icon } from '../../icons.js';

export { icon };

let uid = 0;
const nextId = (prefix) => `${prefix}-${++uid}`;

/** 轻量 h()：支持 class、text、html、on* 事件、attrs、dataset */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class' || key === 'className') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key === 'html') el.innerHTML = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key === 'style' && typeof value === 'object') Object.assign(el.style, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'value' || key === 'checked' || key === 'disabled' || key === 'selected') {
      el[key] = value;
    } else if (key === 'attrs') {
      for (const [name, val] of Object.entries(value)) el.setAttribute(name, val);
    } else if (value === true) {
      el.setAttribute(key, '');
    } else {
      el.setAttribute(key, value);
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

/* -------------------------------------------------------------------------- */
/* 按钮                                                                        */
/* -------------------------------------------------------------------------- */

export function button({
  label,
  icon: iconName,
  iconEnd,
  variant = 'filled',
  size = 'md',
  onclick,
  disabled = false,
  title,
  type = 'button',
  class: extra = '',
  attrs = {},
}) {
  const el = h('button', {
    class: `btn btn-${variant}${size === 'sm' ? ' btn-sm' : ''}${extra ? ` ${extra}` : ''} md-ripple`,
    type,
    disabled,
    title,
    attrs,
    onclick,
  });
  if (iconName) el.append(icon(iconName, size === 'sm' ? 17 : 19));
  if (label) el.append(h('span', { class: 'btn-label', text: label }));
  if (iconEnd) el.append(icon(iconEnd, size === 'sm' ? 16 : 18));
  return el;
}

export function iconButton({
  icon: iconName,
  label,
  onclick,
  size = 20,
  active = false,
  variant = 'standard',
  disabled = false,
  title,
  attrs = {},
}) {
  const el = h('button', {
    class: `icon-btn icon-btn-${variant}${active ? ' is-active' : ''} md-ripple`,
    type: 'button',
    'aria-label': label,
    title: title || label,
    disabled,
    attrs,
    onclick,
  });
  el.append(icon(iconName, size));
  return el;
}

/* -------------------------------------------------------------------------- */
/* 展示                                                                        */
/* -------------------------------------------------------------------------- */

export function chip({ label, tone = 'neutral', icon: iconName, dot = false, live = false, class: extra = '' }) {
  const el = h('span', { class: `chip chip-${tone}${extra ? ` ${extra}` : ''}` });
  if (dot) el.append(h('span', { class: `chip-dot${live ? ' is-live' : ''}`, 'aria-hidden': 'true' }));
  if (iconName) el.append(icon(iconName, 15));
  if (label) el.append(h('span', { text: label }));
  return el;
}

export function liveChip({ label, online = true, tone }) {
  const resolved = tone || (online ? 'success' : 'error');
  return chip({ label, tone: resolved, dot: true, live: online });
}

export function section({ title, subtitle, actions, children, class: extra = '', padded = true }) {
  const head =
    title || actions
      ? h(
          'div',
          { class: 'section-head' },
          h(
            'div',
            { class: 'section-heading' },
            title ? h('h2', { class: 'section-title', text: title }) : null,
            subtitle ? h('p', { class: 'section-sub', text: subtitle }) : null
          ),
          actions ? h('div', { class: 'section-actions' }, actions) : null
        )
      : null;
  return h('section', { class: `card section${padded ? ' is-padded' : ''}${extra ? ` ${extra}` : ''}` }, head, children);
}

export function progressBar(value, { indeterminate = false, label } = {}) {
  const pct = Math.max(0, Math.min(100, Math.round((value || 0) * 100)));
  const el = h('div', {
    class: `progress${indeterminate ? ' is-indeterminate' : ''}`,
    role: 'progressbar',
    'aria-label': label || '进度',
    'aria-valuemin': '0',
    'aria-valuemax': '100',
  });
  if (!indeterminate) el.setAttribute('aria-valuenow', String(pct));
  el.append(h('div', { class: 'progress-track' }, h('div', { class: 'progress-fill', style: { width: `${pct}%` } })));
  return el;
}

/* -------------------------------------------------------------------------- */
/* 表单                                                                        */
/* -------------------------------------------------------------------------- */

export function textField({
  label,
  ariaLabel,
  value = '',
  placeholder = '',
  oninput,
  onchange,
  type = 'text',
  mono = false,
  hint,
  id,
  autofocus = false,
  spellcheck = false,
  inputmode,
  disabled = false,
  class: extra = '',
}) {
  const inputId = id || nextId('field');
  const wrap = h('div', { class: `field${extra ? ` ${extra}` : ''}` });
  const input = h('input', {
    id: inputId,
    class: `field-input${mono ? ' is-mono' : ''}`,
    type,
    value,
    placeholder,
    autofocus,
    spellcheck,
    inputmode,
    disabled,
    'aria-label': label ? undefined : ariaLabel || '输入框',
    oninput,
    onchange,
  });
  if (label) wrap.append(h('label', { class: 'field-label', for: inputId, text: label }));
  wrap.append(h('div', { class: 'field-box' }, input));
  if (hint) wrap.append(h('p', { class: 'field-hint', text: hint }));
  wrap.input = input;
  return wrap;
}

/**
 * MD3 描边式下拉选择（自定义 listbox）。
 * 原生 <select> 的弹出菜单无法控制圆角 / 行高 / 状态层，因此这里用
 * combobox + listbox 自己实现，键盘操作与原生一致。
 * onchange 仍收到 { target: { value } }，兼容旧调用方式。
 */
let activeSelect = null;

export function selectField({
  label,
  ariaLabel,
  options = [],
  value,
  onchange,
  id,
  hint,
  disabled = false,
  class: extra = '',
}) {
  const selectId = id || nextId('select');
  const labelId = `${selectId}-label`;
  const menuId = `${selectId}-menu`;
  let current = value === undefined || value === null ? (options[0] ? options[0].value : '') : value;
  let open = false;
  let activeIndex = Math.max(
    0,
    options.findIndex((opt) => String(opt.value) === String(current))
  );
  let typeBuffer = '';
  let typeTimer = null;

  const valueText = h('span', { class: 'select-value' });
  const trigger = h(
    'button',
    {
      id: selectId,
      class: 'select-trigger',
      type: 'button',
      role: 'combobox',
      'aria-haspopup': 'listbox',
      'aria-expanded': 'false',
      'aria-controls': menuId,
      'aria-labelledby': label ? labelId : undefined,
      'aria-label': label ? undefined : ariaLabel || '选择',
      disabled,
    },
    valueText,
    h('span', { class: 'select-caret', 'aria-hidden': 'true' }, icon('chevronDown', 20))
  );

  const menu = h('div', {
    id: menuId,
    class: 'select-menu',
    role: 'listbox',
    tabindex: '-1',
    hidden: true,
    'aria-labelledby': label ? labelId : undefined,
    'aria-label': label ? undefined : ariaLabel || '选项列表',
  });

  const items = options.map((opt, index) => {
    const item = h(
      'div',
      {
        id: `${menuId}-opt-${index}`,
        class: 'select-option',
        role: 'option',
        'aria-selected': String(String(opt.value) === String(current)),
        dataset: { index: String(index), value: String(opt.value) },
      },
      h('span', { class: 'select-option-label', text: opt.label }),
      h('span', { class: 'select-option-check', 'aria-hidden': 'true' }, icon('check', 16))
    );
    item.addEventListener('click', () => choose(index));
    item.addEventListener('mousemove', () => {
      if (open && activeIndex !== index) setActive(index, false);
    });
    menu.append(item);
    return item;
  });

  // 避免点击菜单时按钮失焦（否则键盘焦点会掉到 body）
  menu.addEventListener('mousedown', (event) => event.preventDefault());

  const wrap = h('div', { class: `field select-field${extra ? ` ${extra}` : ''}` });
  if (label) wrap.append(h('label', { class: 'field-label', id: labelId, for: selectId, text: label }));
  wrap.append(trigger);
  if (hint) wrap.append(h('p', { class: 'field-hint', text: hint }));

  function currentLabel() {
    const found = options.find((opt) => String(opt.value) === String(current));
    return found ? found.label : '';
  }

  function setActive(index, scroll = true) {
    if (!items.length) return;
    const next = Math.max(0, Math.min(items.length - 1, index));
    items.forEach((item, i) => item.classList.toggle('is-active', i === next));
    activeIndex = next;
    if (open) trigger.setAttribute('aria-activedescendant', items[next].id);
    if (scroll) items[next].scrollIntoView({ block: 'nearest' });
  }

  function sync() {
    valueText.textContent = currentLabel();
    items.forEach((item, index) =>
      item.setAttribute('aria-selected', String(String(options[index].value) === String(current)))
    );
    const found = options.findIndex((opt) => String(opt.value) === String(current));
    activeIndex = found >= 0 ? found : 0;
    if (open) setActive(activeIndex, false);
  }

  function place() {
    if (!open) return;
    const gap = 4;
    const rect = trigger.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom - gap - 8;
    const spaceAbove = rect.top - gap - 8;
    const openUp = spaceBelow < 180 && spaceAbove > spaceBelow;
    const width = Math.min(rect.width, window.innerWidth - 16);
    menu.style.minWidth = `${Math.round(width)}px`;
    menu.style.maxHeight = `${Math.round(Math.max(120, Math.min(280, openUp ? spaceAbove : spaceBelow)))}px`;
    menu.style.left = `${Math.round(Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)))}px`;
    if (openUp) {
      menu.style.top = 'auto';
      menu.style.bottom = `${Math.round(window.innerHeight - rect.top + gap)}px`;
    } else {
      menu.style.bottom = 'auto';
      menu.style.top = `${Math.round(rect.bottom + gap)}px`;
    }
  }

  function onDocPointer(event) {
    if (wrap.contains(event.target) || menu.contains(event.target)) return;
    closeMenu();
  }

  function openMenu() {
    if (disabled || open) return;
    if (activeSelect && activeSelect !== closeMenu) activeSelect();
    if (!menu.isConnected) document.body.append(menu);
    open = true;
    menu.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    wrap.classList.add('is-open');
    place();
    setActive(activeIndex, true);
    document.addEventListener('pointerdown', onDocPointer, true);
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    activeSelect = closeMenu;
  }

  function closeMenu() {
    if (!open) return;
    open = false;
    menu.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    trigger.removeAttribute('aria-activedescendant');
    wrap.classList.remove('is-open');
    document.removeEventListener('pointerdown', onDocPointer, true);
    window.removeEventListener('scroll', place, true);
    window.removeEventListener('resize', place);
    if (activeSelect === closeMenu) activeSelect = null;
  }

  function choose(index) {
    const opt = options[index];
    if (!opt) return;
    const changed = String(current) !== String(opt.value);
    current = opt.value;
    sync();
    closeMenu();
    trigger.focus();
    if (changed && typeof onchange === 'function') {
      onchange({ target: { value: opt.value }, currentTarget: { value: opt.value } });
    }
  }

  function typeahead(char) {
    typeBuffer += char.toLowerCase();
    clearTimeout(typeTimer);
    typeTimer = setTimeout(() => {
      typeBuffer = '';
    }, 600);
    if (!open) openMenu();
    const start = activeIndex + 1;
    for (let i = 0; i < items.length; i += 1) {
      const index = (start + i) % items.length;
      if (String(options[index].label).toLowerCase().startsWith(typeBuffer)) {
        setActive(index);
        return;
      }
    }
  }

  function onKeydown(event) {
    if (disabled) return;
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        if (!open) openMenu();
        else setActive(activeIndex + 1);
        break;
      case 'ArrowUp':
        event.preventDefault();
        if (!open) openMenu();
        else setActive(activeIndex - 1);
        break;
      case 'Home':
        if (open) {
          event.preventDefault();
          setActive(0);
        }
        break;
      case 'End':
        if (open) {
          event.preventDefault();
          setActive(items.length - 1);
        }
        break;
      case 'Enter':
      case ' ':
        event.preventDefault();
        if (open) choose(activeIndex);
        else openMenu();
        break;
      case 'Escape':
        if (open) {
          event.preventDefault();
          closeMenu();
        }
        break;
      case 'Tab':
        if (open) closeMenu();
        break;
      default:
        if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) typeahead(event.key);
    }
  }

  trigger.addEventListener('click', () => {
    if (open) closeMenu();
    else openMenu();
  });
  trigger.addEventListener('keydown', onKeydown);

  wrap.select = {
    get value() {
      return current;
    },
    setValue(next) {
      current = next;
      sync();
    },
    focus() {
      trigger.focus();
    },
  };
  // 供调用方在异步操作期间禁用整个下拉（例如应用编辑时冻结裁剪比例）
  wrap.setDisabled = (next) => {
    trigger.disabled = Boolean(next);
    if (next) closeMenu();
  };
  wrap.destroy = () => {
    closeMenu();
    clearTimeout(typeTimer);
    menu.remove();
  };

  sync();
  return wrap;
}

export function segmented({ options, value, onchange, label, ariaLabel, block = false }) {
  const group = h('div', {
    class: `segmented${block ? ' is-block' : ''}`,
    role: 'group',
    'aria-label': ariaLabel || label || '选项',
  });
  const entries = [];

  const apply = (next, notify) => {
    entries.forEach(({ btn, value: itemValue }) =>
      btn.setAttribute('aria-pressed', String(String(itemValue) === String(next)))
    );
    if (notify && typeof onchange === 'function') onchange(next);
  };

  options.forEach((opt) => {
    const btn = h(
      'button',
      {
        class: 'segment md-ripple',
        type: 'button',
        'aria-pressed': String(String(opt.value) === String(value)),
        'data-value': opt.value,
        title: opt.title,
        onclick: () => {
          if (btn.getAttribute('aria-pressed') === 'true') return;
          apply(opt.value, true);
        },
      },
      opt.icon ? icon(opt.icon, 17) : null,
      h('span', { class: 'segment-check', 'aria-hidden': 'true' }, icon('check', 15)),
      h('span', { class: 'segment-label', text: opt.label })
    );
    entries.push({ btn, value: opt.value });
    group.append(btn);
  });

  group.setValue = (next) => apply(next, false);
  return group;
}

export function stepper({ label, value, min = 1, max = 99, onchange, id }) {
  const valueId = id || nextId('stepper');
  const out = h('span', { class: 'stepper-value', id: valueId, text: String(value), 'aria-live': 'polite' });
  let current = value;

  const apply = (next) => {
    current = Math.max(min, Math.min(max, next));
    out.textContent = String(current);
    dec.disabled = current <= min;
    inc.disabled = current >= max;
    onchange(current);
  };

  const dec = iconButton({
    icon: 'minus',
    label: '减少',
    size: 18,
    onclick: () => apply(current - 1),
    disabled: value <= min,
  });
  const inc = iconButton({
    icon: 'plus',
    label: '增加',
    size: 18,
    onclick: () => apply(current + 1),
    disabled: value >= max,
  });

  const wrap = h(
    'div',
    { class: 'stepper' },
    h('span', { class: 'stepper-label', text: label, id: `${valueId}-label` }),
    h('div', { class: 'stepper-controls', role: 'group', 'aria-labelledby': `${valueId}-label` }, dec, out, inc)
  );
  wrap.setValue = (next) => {
    current = Math.max(min, Math.min(max, next));
    out.textContent = String(current);
    dec.disabled = current <= min;
    inc.disabled = current >= max;
  };
  return wrap;
}

export function switchControl({ checked, onchange, label, ariaLabel, description, id }) {
  const labelId = id || nextId('switch');
  const btn = h('button', {
    class: `switch${checked ? ' is-on' : ''}`,
    type: 'button',
    role: 'switch',
    'aria-checked': String(checked),
    'aria-labelledby': label ? labelId : undefined,
    'aria-label': label ? undefined : ariaLabel || '开关',
    onclick: () => {
      const next = btn.getAttribute('aria-checked') !== 'true';
      btn.setAttribute('aria-checked', String(next));
      btn.classList.toggle('is-on', next);
      onchange(next);
    },
  });
  btn.append(h('span', { class: 'switch-thumb' }));
  if (!label) return btn;
  return h(
    'div',
    { class: 'switch-row' },
    h(
      'div',
      { class: 'switch-text' },
      h('span', { class: 'switch-label', id: labelId, text: label }),
      description ? h('span', { class: 'switch-desc', text: description }) : null
    ),
    btn
  );
}

export function slider({ label, ariaLabel, min, max, step = 1, value, oninput, format = (v) => String(v), hint, id }) {
  const inputId = id || nextId('slider');
  const out = h('output', { class: 'slider-value', for: inputId, text: format(value) });
  const input = h('input', {
    id: inputId,
    class: 'slider',
    type: 'range',
    min,
    max,
    step,
    value,
    'aria-label': label ? undefined : ariaLabel || '滑块',
    oninput: (event) => {
      const next = Number(event.target.value);
      out.textContent = format(next);
      if (oninput) oninput(next);
    },
  });
  const head = h(
    'div',
    { class: `slider-head${label ? '' : ' is-value-only'}` },
    label ? h('label', { class: 'field-label is-inline', for: inputId, text: label }) : null,
    out
  );
  const wrap = h('div', { class: 'field' }, head, input);
  if (hint) wrap.append(h('p', { class: 'field-hint', text: hint }));
  wrap.input = input;
  wrap.setValue = (next) => {
    input.value = next;
    out.textContent = format(next);
  };
  return wrap;
}

/* -------------------------------------------------------------------------- */
/* 对话框                                                                      */
/* -------------------------------------------------------------------------- */

export function openDialog({ title, body, actions = [], dismissible = true, width }) {
  const root = document.getElementById('dialog-root') || document.body;
  const titleId = nextId('dialog-title');
  const previouslyFocused = document.activeElement;

  const panel = h('div', {
    class: 'dialog',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-labelledby': titleId,
    style: width ? { maxWidth: width } : undefined,
  });
  panel.append(h('h2', { class: 'dialog-title', id: titleId, text: title }));
  if (body) panel.append(h('div', { class: 'dialog-body' }, body));
  const footer = h('div', { class: 'dialog-actions' });
  actions.forEach((action) => footer.append(action));
  if (actions.length) panel.append(footer);

  const scrim = h('div', { class: 'dialog-scrim' });
  const layer = h('div', { class: 'dialog-layer' }, scrim, panel);

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    document.removeEventListener('keydown', onKeydown, true);
    layer.classList.add('is-closing');
    setTimeout(() => layer.remove(), 140);
    if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
  };

  function onKeydown(event) {
    if (event.key === 'Escape' && dismissible) {
      event.preventDefault();
      close();
    }
    if (event.key === 'Tab') {
      const focusable = panel.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }

  if (dismissible) scrim.addEventListener('click', close);
  document.addEventListener('keydown', onKeydown, true);
  root.append(layer);
  requestAnimationFrame(() => {
    const target = panel.querySelector('[data-autofocus], .btn-filled, button, input');
    if (target) target.focus();
  });

  return { close, panel };
}

export function confirmDialog({ title, message, confirmLabel = '确认', cancelLabel = '取消', danger = false }) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
      dialog.close();
    };
    const dialog = openDialog({
      title,
      body: h('p', { class: 'dialog-text', text: message }),
      actions: [
        button({ label: cancelLabel, variant: 'text', onclick: () => finish(false) }),
        button({ label: confirmLabel, variant: danger ? 'danger' : 'filled', onclick: () => finish(true) }),
      ],
    });
    dialog.panel.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        finish(true);
      }
    });
  });
}

/* -------------------------------------------------------------------------- */
/* 格式化                                                                      */
/* -------------------------------------------------------------------------- */

const zhNumber = new Intl.NumberFormat('zh-CN');
const zhDateTime = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const zhDate = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
const zhTime = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
const zhRelative = new Intl.RelativeTimeFormat('zh-CN', { numeric: 'auto' });

export const fmt = {
  number(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return zhNumber.format(Number(value));
  },
  dateTime(ts) {
    if (!ts) return '—';
    return zhDateTime.format(new Date(ts * 1000));
  },
  date(ts) {
    if (!ts) return '—';
    return zhDate.format(new Date(ts * 1000));
  },
  time(ts) {
    if (!ts) return '—';
    return zhTime.format(new Date(ts * 1000));
  },
  relative(ts) {
    if (!ts) return '—';
    const diff = Math.round(Date.now() / 1000 - ts);
    if (diff < 45) return '刚刚';
    if (diff < 3600) return zhRelative.format(-Math.round(diff / 60), 'minute');
    if (diff < 86400) return zhRelative.format(-Math.round(diff / 3600), 'hour');
    if (diff < 86400 * 7) return zhRelative.format(-Math.round(diff / 86400), 'day');
    return zhDate.format(new Date(ts * 1000));
  },
  bytes(bytes) {
    if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) return '—';
    const n = Number(bytes);
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  },
  pages(count) {
    if (count === null || count === undefined) return '—';
    return `${zhNumber.format(Number(count))} 页`;
  },
  percent(value) {
    if (value === null || value === undefined) return '—';
    return `${Math.round(Number(value))}%`;
  },
};

/* -------------------------------------------------------------------------- */
/* 状态映射                                                                    */
/* -------------------------------------------------------------------------- */

const JOB_STATES = {
  queued: { label: '排队中', tone: 'neutral' },
  preparing: { label: '准备中', tone: 'info' },
  sending: { label: '发送中', tone: 'info' },
  printing: { label: '打印中', tone: 'info' },
  paused: { label: '已暂停', tone: 'warning' },
  done: { label: '已完成', tone: 'success' },
  error: { label: '失败', tone: 'error' },
  canceled: { label: '已取消', tone: 'neutral' },
};

const PRINTER_STATES = {
  idle: { label: '就绪', tone: 'success' },
  processing: { label: '忙碌', tone: 'warning' },
  stopped: { label: '已停止', tone: 'error' },
  offline: { label: '离线', tone: 'error' },
  unknown: { label: '未知', tone: 'neutral' },
};

export function jobStateMeta(state, kind) {
  if (kind === 'scan' && (state === 'sending' || state === 'printing')) {
    return { label: '扫描中', tone: 'info' };
  }
  return JOB_STATES[state] || { label: state || '未知', tone: 'neutral' };
}

export function printerStateMeta(state, online) {
  if (!online && (!state || state === 'idle')) return PRINTER_STATES.offline;
  return PRINTER_STATES[state] || { label: state || '未知', tone: 'neutral' };
}

export function stateChip(state, { kind, online } = {}) {
  const meta = kind === 'printer' ? printerStateMeta(state, online) : jobStateMeta(state, kind);
  return chip({ label: meta.label, tone: meta.tone, dot: meta.tone === 'info' || meta.tone === 'success' });
}

export const MEDIA_LABELS = {
  'iso_a4_210x297mm': 'A4 · 210 × 297 mm',
  'na_letter_8.5x11in': 'Letter · 8.5 × 11 in',
  'na_legal_8.5x14in': 'Legal · 8.5 × 14 in',
  'iso_a5_148x210mm': 'A5 · 148 × 210 mm',
  'na_index-4x6_4x6in': '4 × 6 in 照片',
  'na_index_4x6': '4 × 6 in 照片',
  'na_index-4x6': '4 × 6 in 照片',
  'na_5x7_5x7in': '5 × 7 in 照片',
  'om_small-photo_100x150mm': '100 × 150 mm 照片',
  'oe_photo-l_3.5x5in': 'L 照片 · 3.5 × 5 in',
  'iso_a6_105x148mm': 'A6 · 105 × 148 mm',
};

export function mediaLabel(value) {
  if (!value) return '—';
  return MEDIA_LABELS[value] || value;
}
