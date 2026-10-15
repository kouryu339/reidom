const mutationSelectors = [
  '[data-edit]', '[data-clip-action]', '[data-quick-action]:not([data-quick-action="open-editor"])',
  '[data-track-control]', '[data-control]', '[data-route-state]', '#add-track', '#import-midi', '#mock-midi',
  '#undo-command', '#redo-command', '#tempo-input', '#set-loop-range',
  '[data-transport="recording"]', '[data-transport="loop"]', '[data-transport="metronome"]',
  '#track-effects-panel input', '#track-effects-panel select', '#track-effects-panel button',
  '#clip-inspector input', '#clip-inspector button[type="submit"]',
].join(',');

export function createEditMode({ state, service, refresh, report }) {
  const shell = document.querySelector('#app-shell');
  const button = document.querySelector('#edit-mode');
  const label = document.querySelector('#edit-mode-status');
  let switching = false;
  const manual = () => state.project?.editing?.mode === 'manual';

  button.addEventListener('click', async () => {
    if (switching) return;
    switching = true; button.disabled = true;
    try {
      await service().setEditMode(manual() ? 'ai' : 'manual');
      state.interaction = null; state.clipInteraction = null;
      await refresh();
    } catch (error) { report(`模式切换失败：${error.message}`); }
    finally { switching = false; render(); }
  });

  const menu = document.querySelector('#project-menu');
  const menuBody = menu.querySelector('.project-menu-body');
  for (const id of ['open-project','save-project','import-midi','mock-midi','export-midi','export-wav','open-device-settings']) {
    const control = document.getElementById(id);
    if (control) menuBody.append(control);
  }
  menuBody.addEventListener('click', (event) => {
    if (event.target.closest('button:not(:disabled)')) menu.open = false;
  });
  document.addEventListener('click', (event) => { if (!menu.contains(event.target)) menu.open = false; });

  // Capture prevents controls from opening editing flows while read-only.
  for (const type of ['click','change','submit']) document.addEventListener(type, (event) => {
    if (!manual() && event.target.closest?.(mutationSelectors)) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);

  function render() {
    const editing = manual();
    shell.dataset.editMode = editing ? 'manual' : 'ai';
    button.textContent = editing ? '完成编辑' : '手动编辑';
    button.setAttribute('aria-pressed', String(editing));
    button.disabled = switching || !state.project?.editing;
    label.textContent = editing ? '手动编辑中 · AI 暂停修改' : 'AI 创作 · 作品只读';
    document.querySelector('#workspace-title').textContent = state.project?.name || '新的作品';
    for (const control of document.querySelectorAll(mutationSelectors)) control.disabled = !editing;
    const empty = document.querySelector('#song-empty');
    empty.hidden = editing || Boolean(state.project?.tracks?.length);
  }
  return { render, manual };
}
