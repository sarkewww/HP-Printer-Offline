/**
 * components/jobs.js — 作业列表与作业表格（首页 / 历史共用）
 */

import { h, fmt, stateChip, iconButton, progressBar } from './ui.js';
import { icon } from '../../icons.js';

const KIND_LABEL = { print: '打印', scan: '扫描' };
const ACTIVE_STATES = new Set(['queued', 'preparing', 'sending', 'printing']);

function kindIcon(kind) {
  return kind === 'scan' ? 'scan' : 'print';
}

function subtitle(job) {
  const parts = [KIND_LABEL[job.kind] || '作业'];
  if (job.pages_total) parts.push(fmt.pages(job.pages_total));
  parts.push(fmt.relative(job.created_at));
  return parts.join(' · ');
}

/** 紧凑行：首页「最近作业」 */
export function jobRow(job, { onclick } = {}) {
  const interactive = typeof onclick === 'function';
  const row = h(
    interactive ? 'button' : 'div',
    {
      class: `job-row${interactive ? ' is-interactive md-ripple' : ''}`,
      type: interactive ? 'button' : undefined,
      onclick,
    },
    h('span', { class: `job-icon job-icon-${job.kind || 'print'}` }, icon(kindIcon(job.kind), 19)),
    h(
      'span',
      { class: 'job-main' },
      h('span', { class: 'job-title', text: job.title || '未命名作业' }),
      h('span', { class: 'job-sub', text: subtitle(job) })
    ),
    stateChip(job.state, { kind: job.kind })
  );
  return row;
}

/** 作业表格：历史页 */
export function jobTable(jobs, { onReprint, onDelete, onCancel, onDetail } = {}) {
  const table = h('table', { class: 'data-table' });
  const thead = h(
    'thead',
    {},
    h(
      'tr',
      {},
      h('th', { scope: 'col', text: '作业' }),
      h('th', { scope: 'col', text: '类型' }),
      h('th', { scope: 'col', text: '状态' }),
      h('th', { scope: 'col', class: 'is-num', text: '页数' }),
      h('th', { scope: 'col', text: '时间' }),
      h('th', { scope: 'col', class: 'is-actions', text: '操作' })
    )
  );

  const tbody = h('tbody');
  jobs.forEach((job) => {
    // 后端 serialize_job 只返回 options（源文件 token 在 options.tokens 里），
    // 不一定带顶层 files；两者都兼容，避免「重新打印」永远被禁用。
    const files = Array.isArray(job.files) && job.files.length
      ? job.files
      : (job.options && Array.isArray(job.options.tokens) ? job.options.tokens : []);
    const canReprint = job.kind === 'print' && files.length > 0;
    const canDelete = job.kind === 'scan';
    const active = ACTIVE_STATES.has(job.state);
    const pct = Math.round((Number(job.progress) || 0) * 100);

    tbody.append(
      h(
        'tr',
        {
          class: `${active ? 'is-active-job' : ''}${onDetail ? ' is-clickable' : ''}`,
          tabindex: onDetail ? 0 : undefined,
          role: onDetail ? 'button' : undefined,
          'aria-label': onDetail ? `查看详情：${job.title || '未命名作业'}` : undefined,
          onclick: (event) => {
            if (event.target.closest('.row-actions')) return;
            if (onDetail) onDetail(job);
          },
          onkeydown: (event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            if (event.target.closest('.row-actions')) return;
            event.preventDefault();
            if (onDetail) onDetail(job);
          },
        },
        h(
          'th',
          { scope: 'row', class: 'cell-job-cell' },
          h(
            'div',
            { class: 'cell-job' },
            h('span', { class: `job-icon job-icon-${job.kind || 'print'}` }, icon(kindIcon(job.kind), 17)),
            h(
              'span',
              { class: 'cell-job-text' },
              h('span', { class: 'cell-job-title', text: job.title || '未命名作业' }),
              job.error ? h('span', { class: 'cell-job-error', text: job.message || '作业失败' }) : null
            )
          )
        ),
        h('td', { class: 'cell-type', text: KIND_LABEL[job.kind] || '作业' }),
        h(
          'td',
          { class: 'cell-state' },
          stateChip(job.state, { kind: job.kind }),
          active
            ? h(
                'div',
                { class: 'cell-progress' },
                progressBar(job.progress || 0, { label: '作业进度' }),
                h('span', {
                  class: 'cell-progress-text',
                  text: `${fmt.number(job.pages_sent || 0)} / ${fmt.number(job.pages_total || 0)} 页 · ${pct}%`,
                })
              )
            : null
        ),
        h('td', { class: 'is-num' }, fmt.pages(job.pages_total)),
        h(
          'td',
          { class: 'cell-time' },
          h('span', { text: fmt.dateTime(job.created_at) }),
          h('span', { class: 'cell-time-sub', text: fmt.relative(job.created_at) })
        ),
        h(
          'td',
          { class: 'is-actions' },
          h(
            'div',
            {
              class: 'row-actions',
              // 行本身是可点击的详情入口；操作按钮的点击 / 键盘事件不能冒泡到行上，
              // 否则会同时触发「打开详情」。
              onclick: (event) => event.stopPropagation(),
              onkeydown: (event) => {
                if (event.key === 'Enter' || event.key === ' ') event.stopPropagation();
              },
            },
            active
              ? iconButton({
                  icon: 'close',
                  label: '取消作业',
                  title: '取消作业',
                  size: 18,
                  onclick: onCancel ? () => onCancel(job) : undefined,
                })
              : null,
            iconButton({
              icon: 'refresh',
              label: canReprint ? '重新打印' : '该作业没有保留源文件，无法重新打印',
              size: 18,
              disabled: !canReprint,
              onclick: canReprint && onReprint ? () => onReprint(job) : undefined,
            }),
            iconButton({
              icon: 'trash',
              label: canDelete ? '删除扫描记录' : '打印作业不支持删除',
              size: 18,
              disabled: !canDelete,
              onclick: canDelete && onDelete ? () => onDelete(job) : undefined,
            })
          )
        )
      )
    );
  });

  table.append(thead, tbody);
  return h('div', { class: 'table-wrap' }, table);
}
