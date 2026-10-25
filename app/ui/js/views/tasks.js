/**
 * views/tasks.js — 任务中心
 *
 * 所有打印 / 扫描 / 复印都先「提交任务」，再在这里统一管理：
 * 暂停 / 继续 / 取消 / 再次。任务状态来自后端 SQLite + SSE 实时推送。
 */

import { h, icon, button, chip, section, segmented, progressBar, stateChip, fmt } from '../components/ui.js';
import { emptyState, banner, skeletonRows } from '../components/feedback.js';

export const title = '任务';
export const subtitle = '所有打印与扫描任务都在这里，可暂停、继续、取消或再次执行';

const ACTIVE_STATES = new Set(['queued', 'preparing', 'sending', 'printing', 'paused']);
const KIND_LABEL = { print: '打印', scan: '扫描', copy: '复印' };
const KIND_ICON = { print: 'print', scan: 'scan', copy: 'copy' };

export async function mount(root, ctx) {
  const { api, state, bus, toast } = ctx;

  let filter = 'active';
  let jobs = [];
  let loading = true;
  let errorText = '';
  let disposed = false;
  let reloadTimer = null;
  let acting = false;

  const wrap = h('div', { class: 'view-tasks' });
  const filterSlot = h('div', { class: 'tasks-filter' });
  const listSlot = h('div', { class: 'tasks-list' });
  // chip() 会把图标放在前面、label 放在后面；这里显式持有 label 引用，
  // 不能再靠 firstElementChild 猜结构（那样会把计数写进 <svg> 图标里）。
  const countLabel = h('span', { text: '—' });
  const countChip = chip({ label: '', tone: 'neutral', icon: 'list' });
  countChip.append(countLabel);

  const card = section({
    title: '任务队列',
    subtitle: '提交后立即返回，任务在后台执行',
    actions: countChip,
    children: h('div', {}, filterSlot, listSlot),
  });

  wrap.append(card);
  root.append(wrap);

  filterSlot.append(
    segmented({
      options: [
        { value: 'active', label: '进行中' },
        { value: 'done', label: '已完成' },
        { value: 'all', label: '全部' },
      ],
      value: filter,
      ariaLabel: '任务筛选',
      onchange: (value) => {
        filter = value;
        paint();
      },
    })
  );

  paint();

  async function load() {
    try {
      const res = await api.jobs({ limit: 80 });
      if (disposed) return;
      jobs = (res && res.jobs) || [];
      errorText = '';
    } catch (err) {
      if (disposed) return;
      errorText = err.message || '读取任务失败';
    } finally {
      loading = false;
      if (!disposed) paint();
    }
  }

  function visibleJobs() {
    if (filter === 'active') return jobs.filter((job) => ACTIVE_STATES.has(job.state));
    if (filter === 'done') return jobs.filter((job) => !ACTIVE_STATES.has(job.state));
    return jobs;
  }

  function paint() {
    const list = visibleJobs();
    const activeCount = jobs.filter((job) => ACTIVE_STATES.has(job.state)).length;
    countLabel.textContent = activeCount ? `${activeCount} 个进行中` : `${jobs.length} 个任务`;

    if (loading) {
      listSlot.replaceChildren(skeletonRows(4));
      return;
    }
    if (errorText) {
      listSlot.replaceChildren(
        banner({ tone: 'error', title: '读取任务失败', message: errorText })
      );
      return;
    }
    if (!list.length) {
      listSlot.replaceChildren(
        emptyState({
          icon: 'list',
          title: filter === 'active' ? '没有正在进行的任务' : '没有任务记录',
          description: '在「打印」或「扫描」页提交后会出现在这里。',
        })
      );
      return;
    }
    listSlot.replaceChildren(...list.map(row));
  }

  function row(job) {
    const active = ACTIVE_STATES.has(job.state);
    const paused = job.state === 'paused';
    const progress =
      active && Number.isFinite(Number(job.progress)) ? Math.max(0, Math.min(1, Number(job.progress))) : null;

    const actions = [];
    if (job.kind === 'print' && active && !paused) {
      actions.push(
        button({
          label: '暂停',
          icon: 'pause',
          variant: 'text',
          size: 'sm',
          disabled: acting,
          onclick: () => act(() => api.pauseJob(job.id), '已暂停'),
        })
      );
    }
    if (paused) {
      actions.push(
        button({
          label: '继续',
          icon: 'play',
          variant: 'tonal',
          size: 'sm',
          disabled: acting,
          onclick: () => act(() => api.resumeJob(job.id), '已继续'),
        })
      );
    }
    if (active) {
      actions.push(
        button({
          label: '取消',
          icon: 'close',
          variant: 'text',
          size: 'sm',
          disabled: acting,
          onclick: () => act(() => api.cancelJob(job.id), '已取消'),
        })
      );
    } else {
      actions.push(
        button({
          label: '再次执行',
          icon: 'refresh',
          variant: 'tonal',
          size: 'sm',
          disabled: acting,
          onclick: () => act(() => api.retryJob(job.id), '已重新提交', true),
        })
      );
    }

    return h(
      'article',
      { class: `task-row${active ? ' is-active' : ''}${paused ? ' is-paused' : ''}` },
      h(
        'div',
        { class: 'task-main' },
        h(
          'div',
          { class: 'task-line' },
          h('span', { class: 'task-icon' }, icon(KIND_ICON[job.kind] || 'print', 18)),
          h('span', { class: 'task-title', text: job.title || '未命名任务' }),
          stateChip(job.state, { kind: job.kind })
        ),
        h(
          'div',
          { class: 'task-meta' },
          h('span', { text: KIND_LABEL[job.kind] || job.kind }),
          h('span', { text: fmt.pages(job.pages_total || 0) }),
          h('span', { text: fmt.relative(job.created_at) })
        ),
        progress !== null
          ? h(
              'div',
              { class: 'task-progress' },
              progressBar(progress, { label: job.message || '处理中' }),
              h('span', { class: 'task-pct', text: `${Math.round(progress * 100)}%` })
            )
          : job.error
            ? h('p', { class: 'task-error', text: job.error })
            : null
      ),
      h('div', { class: 'task-actions' }, ...actions)
    );
  }

  /** 请求期间禁用所有行内操作按钮，避免「再次执行」等重复提交 */
  function setActionsDisabled(disabled) {
    listSlot.querySelectorAll('.task-actions button').forEach((btn) => {
      btn.disabled = disabled;
    });
    listSlot.setAttribute('aria-busy', String(disabled));
  }

  async function act(fn, okText, navigateOnSuccess = false) {
    if (acting) return; // in-flight 标记：同一时间只允许一个操作
    acting = true;
    setActionsDisabled(true);
    try {
      const res = await fn();
      toast(okText, { tone: 'success' });
      await load();
      if (navigateOnSuccess && res && res.job_id) {
        navigateToJob(res.job_id);
      }
    } catch (err) {
      toast(err.message || '操作失败', { tone: 'error', duration: 7000 });
    } finally {
      acting = false;
      if (!disposed) setActionsDisabled(false);
    }
  }

  function navigateToJob(jobId) {
    // 再次执行后跳到历史页看新任务，任务页保持列表
    if (ctx.navigate) ctx.navigate('history');
    toast(`新任务 #${jobId} 已提交`, { tone: 'success' });
  }

  function scheduleReload() {
    if (reloadTimer) return;
    reloadTimer = setTimeout(() => {
      reloadTimer = null;
      load();
    }, 350);
  }

  const offJob = bus && typeof bus.on === 'function' ? bus.on('job', scheduleReload) : null;
  const offRefresh = bus && typeof bus.on === 'function' ? bus.on('refresh', scheduleReload) : null;

  await load();

  return () => {
    disposed = true;
    if (reloadTimer) clearTimeout(reloadTimer);
    if (offJob) offJob();
    if (offRefresh) offRefresh();
  };
}
