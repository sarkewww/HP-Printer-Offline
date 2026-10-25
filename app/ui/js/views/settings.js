/**
 * views/settings.js — 设置：外观、存储、发现、默认打印机、关于
 */

import {
  h,
  icon,
  button,
  chip,
  section,
  segmented,
  selectField,
  slider,
  switchControl,
  textField,
  fmt,
  openDialog,
} from '../components/ui.js';
import { banner } from '../components/feedback.js';

export const title = '设置';
export const subtitle = '所有配置都保存在本机';

const THEMES = [
  { value: 'light', label: '浅色', icon: 'sun' },
  { value: 'dark', label: '深色', icon: 'moon' },
  { value: 'system', label: '跟随系统', icon: 'monitor' },
];

export async function mount(root, ctx) {
  const { api, state, toast } = ctx;

  const storedTheme = document.documentElement.dataset.theme || 'system';
  const settings = {
    theme: storedTheme,
    accent: (state.settings && state.settings.accent) || '#0096D6',
    save_dir: (state.settings && state.settings.save_dir) || '',
    auto_discover: state.settings ? Boolean(state.settings.auto_discover) : true,
    poll_interval: state.settings && state.settings.poll_interval ? Number(state.settings.poll_interval) : 10,
    default_printer: (state.settings && state.settings.default_printer) || (state.printer && state.printer.id) || '',
  };

  const wrap = h('div', { class: 'settings-wrap' });

  if (!state.settings) {
    wrap.append(
      banner({
        tone: 'warning',
        icon: 'warning',
        title: '未能从后端读取设置',
        message: '当前显示默认值。修改会先保存在本机，连接恢复后可再次保存。',
        action: button({ label: '重试', icon: 'refresh', variant: 'text', onclick: () => ctx.reloadRoute() }),
      })
    );
  }

  /* ------------------------------------------------------------------ 外观 */

  const accentRow = h('div', { class: 'accent-row', role: 'group', 'aria-label': '强调色' });
  Object.entries(ctx.accents).forEach(([name, meta]) => {
    const swatch = h('button', {
      class: 'accent-swatch md-ripple',
      type: 'button',
      'aria-label': `${meta.label}（${meta.hex}）`,
      'aria-pressed': String(document.documentElement.dataset.accent === name),
      title: meta.label,
      onclick: () => {
        ctx.applyAccent(name);
        accentRow.querySelectorAll('.accent-swatch').forEach((node) => node.setAttribute('aria-pressed', 'false'));
        swatch.setAttribute('aria-pressed', 'true');
        patch({ accent: meta.hex }, '强调色');
      },
    });
    swatch.style.setProperty('--swatch', meta.hex);
    accentRow.append(swatch);
  });

  const appearance = section({
    title: '外观',
    subtitle: '主题与强调色立即生效',
    children: h(
      'div',
      {},
      h(
        'div',
        { class: 'setting-row' },
        h(
          'div',
          { class: 'setting-label' },
          h('span', { class: 'setting-name', text: '主题' }),
          h('span', { class: 'setting-desc', text: '深色模式使用独立的色调梯度，而不是简单反色。' })
        ),
        h(
          'div',
          { class: 'setting-control' },
          segmented({
            options: THEMES,
            value: settings.theme,
            ariaLabel: '主题',
            onchange: (value) => {
              settings.theme = value;
              ctx.applyTheme(value);
              if (state.settings) state.settings.theme = value;
              patch({ theme: value }, '主题');
            },
          })
        )
      ),
      h(
        'div',
        { class: 'setting-row' },
        h(
          'div',
          { class: 'setting-label' },
          h('span', { class: 'setting-name', text: '强调色' }),
          h('span', { class: 'setting-desc', text: '用于按钮、进度与选中状态；中性色保持不变。' })
        ),
        h('div', { class: 'setting-control' }, accentRow)
      )
    ),
  });

  /* ------------------------------------------------------------- 存储与发现 */

  const dirField = textField({
    ariaLabel: '保存目录',
    value: settings.save_dir,
    placeholder: 'C:\\Users\\<用户名>\\Pictures\\HP Offline',
    mono: true,
    onchange: (event) => {
      const value = event.target.value.trim();
      if (value === settings.save_dir) return;
      settings.save_dir = value;
      patch({ save_dir: value }, '保存目录');
    },
  });

  const browseBtn = button({
    label: '浏览…',
    icon: 'folder',
    variant: 'outlined',
    size: 'sm',
    onclick: async () => {
      browseBtn.disabled = true;
      try {
        const result = await api.browseDir();
        if (result && result.path) {
          dirField.input.value = result.path;
          settings.save_dir = result.path;
          patch({ save_dir: result.path }, '保存目录');
          toast('已选择保存目录', { tone: 'success' });
        } else if (result && result.canceled) {
          toast('已取消选择', { tone: 'neutral' });
        } else {
          toast('后端未返回目录', { tone: 'error' });
        }
      } catch (err) {
        toast(`打开目录选择失败：${err.message}`, {
          tone: 'warning',
          duration: 6500,
        });
        dirField.input.focus();
      } finally {
        browseBtn.disabled = false;
      }
    },
  });

  const printerSelect = selectField({
    ariaLabel: '默认打印机',
    options: state.printers.length
      ? state.printers.map((printer) => ({
          value: printer.id,
          label: `${printer.model || printer.name} · ${printer.host || ''}`,
        }))
      : [{ value: '', label: '尚未注册打印机' }],
    value: settings.default_printer,
    disabled: !state.printers.length,
    hint: state.printers.length ? undefined : '先在「打印机」页面注册设备',
    onchange: async (event) => {
      const id = event.target.value;
      settings.default_printer = id;
      if (!id) return;
      try {
        await api.setDefaultPrinter(id);
        await ctx.refreshPrinters({ silent: true });
        patch({ default_printer: id }, '默认打印机');
        toast('已切换默认打印机', { tone: 'success' });
      } catch (err) {
        toast(err.message, { tone: 'error' });
      }
    },
  });

  const pollSlider = slider({
    ariaLabel: '轮询间隔',
    min: 3,
    max: 60,
    step: 1,
    value: settings.poll_interval,
    format: (value) => `${value} 秒`,
  });
  pollSlider.input.addEventListener('change', () => {
    settings.poll_interval = Number(pollSlider.input.value);
    patch({ poll_interval: settings.poll_interval }, '轮询间隔');
  });

  const storage = section({
    title: '存储与发现',
    subtitle: '控制文件落地位置与设备探测行为',
    children: h(
      'div',
      {},
      h(
        'div',
        { class: 'setting-row' },
        h(
          'div',
          { class: 'setting-label' },
          h('span', { class: 'setting-name', text: '保存目录' }),
          h('span', { class: 'setting-desc', text: '扫描件默认写入此目录，路径由后端读写。' })
        ),
        h('div', { class: 'setting-control is-wide' }, dirField, browseBtn)
      ),
      h(
        'div',
        { class: 'setting-row' },
        h(
          'div',
          { class: 'setting-label' },
          h('span', { class: 'setting-name', text: '自动发现' }),
          h('span', { class: 'setting-desc', text: '启动时用 mDNS / WSD / SNMP 探测局域网打印机。' })
        ),
        h(
          'div',
          { class: 'setting-control' },
          switchControl({
            ariaLabel: '自动发现',
            checked: settings.auto_discover,
            onchange: (value) => {
              settings.auto_discover = value;
              patch({ auto_discover: value }, '自动发现');
            },
          })
        )
      ),
      h(
        'div',
        { class: 'setting-row' },
        h(
          'div',
          { class: 'setting-label' },
          h('span', { class: 'setting-name', text: '状态轮询间隔' }),
          h('span', { class: 'setting-desc', text: '仅在实时连接不可用时生效。' })
        ),
        h('div', { class: 'setting-control is-wide' }, pollSlider)
      ),
      h(
        'div',
        { class: 'setting-row' },
        h(
          'div',
          { class: 'setting-label' },
          h('span', { class: 'setting-name', text: '默认打印机' }),
          h('span', { class: 'setting-desc', text: '打印与扫描页面默认使用该设备。' })
        ),
        h('div', { class: 'setting-control is-wide' }, printerSelect)
      )
    ),
  });

  /* ------------------------------------------------------------ 邮件 */
  const mailSection = section({
    title: '邮件（本地 SMTP）',
    subtitle: '扫描件直发邮箱，不经过 HP 服务器',
    children: h(
      'div',
      { class: 'settings-fields' },
      textField({
        label: 'SMTP 主机',
        placeholder: 'smtp.qq.com',
        value: settings.smtp_host || '',
        onchange: (event) => patch({ smtp_host: event.target.value.trim() }, 'SMTP 主机'),
      }),
      textField({
        label: '端口',
        type: 'number',
        placeholder: '465（SSL）或 587（STARTTLS）',
        value: String(settings.smtp_port || 465),
        onchange: (event) => patch({ smtp_port: Number(event.target.value) || 465 }, 'SMTP 端口'),
      }),
      textField({
        label: '账号',
        placeholder: 'you@example.com',
        value: settings.smtp_user || '',
        onchange: (event) => patch({ smtp_user: event.target.value.trim() }, 'SMTP 账号'),
      }),
      textField({
        label: '密码 / 授权码',
        type: 'password',
        placeholder: '邮箱授权码，不是登录密码',
        value: settings.smtp_password || '',
        onchange: (event) => patch({ smtp_password: event.target.value }, 'SMTP 密码'),
      }),
      textField({
        label: '发件人',
        placeholder: '留空则用账号',
        value: settings.smtp_from || '',
        onchange: (event) => patch({ smtp_from: event.target.value.trim() }, '发件人'),
      }),
      textField({
        label: '默认收件人',
        placeholder: 'scan@example.com',
        value: settings.mail_to || '',
        onchange: (event) => patch({ mail_to: event.target.value.trim() }, '默认收件人'),
      }),
      h(
        'div',
        { class: 'setting-row' },
        h(
          'div',
          { class: 'setting-label' },
          h('span', { class: 'setting-name', text: '启用 TLS' }),
          h('span', { class: 'setting-desc', text: '587 端口通常需要开启；465 端口走 SSL，可忽略。' })
        ),
        h(
          'div',
          { class: 'setting-control' },
          switchControl({
            ariaLabel: '启用 TLS',
            checked: settings.smtp_tls !== false,
            onchange: (value) => patch({ smtp_tls: value }, 'TLS'),
          })
        )
      )
    ),
  });

  /* -------------------------------------------------------- 快捷方式 */
  const shortcutList = h('div', { class: 'shortcut-list' });
  const shortcutSection = section({
    title: '快捷方式',
    subtitle: '本地动作序列，替代官方云端 Smart Tasks',
    children: h(
      'div',
      {},
      shortcutList,
      h(
        'div',
        { class: 'shortcut-actions' },
        button({
          label: '扫描 → 存 PDF',
          icon: 'scan',
          variant: 'outlined',
          size: 'sm',
          onclick: () => createShortcut('扫描存 PDF', ['save']),
        }),
        button({
          label: '扫描 → PDF → 邮件',
          icon: 'upload',
          variant: 'outlined',
          size: 'sm',
          onclick: () => createShortcut('扫描存 PDF 并发送邮件', ['save', 'email']),
        }),
        button({
          label: '扫描 → PDF → 打印',
          icon: 'print',
          variant: 'outlined',
          size: 'sm',
          onclick: () => createShortcut('扫描存 PDF 并打印', ['save', 'print']),
        })
      )
    ),
  });

  async function refreshShortcuts() {
    try {
      const res = await api.shortcuts();
      const items = (res && res.shortcuts) || [];
      if (!items.length) {
        shortcutList.replaceChildren(
          h('p', { class: 'setting-desc', text: '还没有快捷方式。点下面的按钮创建一个。' })
        );
        return;
      }
      shortcutList.replaceChildren(
        ...items.map((item) =>
          h(
            'div',
            { class: 'shortcut-row' },
            h(
              'div',
              { class: 'shortcut-main' },
              h('span', { class: 'shortcut-name', text: item.name }),
              h('span', {
                class: 'shortcut-steps',
                text: (item.steps || []).map((s) => ({ save: '保存', email: '邮件', print: '打印' }[s] || s)).join(' → '),
              })
            ),
            h(
              'div',
              { class: 'shortcut-row-actions' },
              button({
                label: '运行',
                variant: 'filled',
                size: 'sm',
                onclick: async () => {
                  toast('正在运行快捷方式…', { duration: 4000 });
                  try {
                    const r = await api.runShortcut(item.id);
                    const errs = (r && r.errors) || [];
                    toast(
                      errs.length ? `完成，但有 ${errs.length} 个步骤失败：${errs[0]}` : '快捷方式执行完成',
                      { tone: errs.length ? 'warning' : 'success', duration: 7000 }
                    );
                  } catch (err) {
                    toast(err.message, { tone: 'error', duration: 8000 });
                  }
                },
              }),
              button({
                label: '删除',
                variant: 'text',
                size: 'sm',
                onclick: async () => {
                  try {
                    await api.deleteShortcut(item.id);
                    refreshShortcuts();
                  } catch (err) {
                    toast(err.message, { tone: 'error' });
                  }
                },
              })
            )
          )
        )
      );
    } catch (err) {
      shortcutList.replaceChildren(h('p', { class: 'setting-desc', text: `读取失败：${err.message}` }));
    }
  }

  async function createShortcut(name, steps) {
    try {
      await api.addShortcut({
        name,
        icon: 'scan',
        steps,
        scan_options: { dpi: 300, format: 'pdf', auto_crop: true, auto_orient: true },
      });
      toast('已创建', { tone: 'success' });
      refreshShortcuts();
    } catch (err) {
      toast(err.message, { tone: 'error' });
    }
  }

  refreshShortcuts();

  /* ---------------------------------------------------------------- 关于 */

  const cloudCalls = state.health && Number.isFinite(Number(state.health.cloud_calls)) ? Number(state.health.cloud_calls) : null;
  const version = (state.health && state.health.version) || '—';
  const python = (state.health && state.health.python) || '—';

  const about = section({
    title: '关于',
    children: h(
      'div',
      { class: 'about-list' },
      h('p', {
        class: 'about-statement',
        text: '本应用不连接任何 HP 服务器，所有操作直连局域网打印机（IPP 631 / eSCL 80 / LEDM 80）。',
      }),
      h(
        'div',
        { class: 'protocol-chips' },
        chip({ label: 'IPP · 631', tone: 'neutral', icon: 'link' }),
        chip({ label: 'eSCL · 80', tone: 'neutral', icon: 'scan' }),
        chip({ label: 'LEDM · 80', tone: 'neutral', icon: 'print' }),
        chip({ label: `公网请求 ${cloudCalls === null ? '—' : fmt.number(cloudCalls)} 次`, tone: 'tertiary', icon: 'cloudOff' })
      ),
      h(
        'div',
        { class: 'about-meta' },
        h('span', {}, h('strong', { text: '版本 ' }), h('span', { class: 'mono', text: version })),
        h('span', {}, h('strong', { text: '后端 ' }), h('span', { class: 'mono', text: `Python ${python}` })),
        h('span', {}, h('strong', { text: '运行模式 ' }), h('span', { text: '本机回环 · 127.0.0.1:8791' })),
        h('span', {}, h('strong', { text: '界面语言 ' }), h('span', { text: '简体中文' }))
      ),
      h(
        'div',
        { class: 'about-actions' },
        button({
          label: '查看本地服务信息',
          icon: 'info',
          variant: 'text',
          size: 'sm',
          onclick: showHealth,
        })
      )
    ),
  });

  wrap.append(appearance, storage, mailSection, shortcutSection, about);
  root.append(wrap);

  /* --------------------------------------------------------------- 行为 */

  async function patch(partial, label) {
    Object.assign(settings, partial);
    if (!state.settings) state.settings = {};
    Object.assign(state.settings, partial);
    try {
      const full = await api.patchSettings(partial);
      if (full && typeof full === 'object') state.settings = { ...state.settings, ...full };
      return true;
    } catch (err) {
      toast(`${label || '设置'}已在本机生效，但同步到后端失败：${err.message}`, {
        tone: 'warning',
        duration: 6000,
      });
      return false;
    }
  }

  function showHealth() {
    let dialog = null;
    const rows = [
      ['服务状态', state.apiOnline ? '运行中' : '未连接'],
      ['版本', version],
      ['Python', python],
      ['公网请求', cloudCalls === null ? '—' : `${fmt.number(cloudCalls)} 次`],
      ['接口地址', 'http://127.0.0.1:8791/api'],
      ['事件通道', state.eventMode === 'polling' ? '轮询（3 秒）' : 'SSE'],
    ];
    dialog = openDialog({
      title: '本地服务信息',
      body: h(
        'dl',
        { class: 'info-grid' },
        rows.map(([label, value]) => [
          h('dt', { text: label }),
          h('dd', { class: 'is-text', text: value }),
        ])
      ),
      actions: [button({ label: '关闭', variant: 'text', onclick: () => dialog.close() })],
    });
  }
}
