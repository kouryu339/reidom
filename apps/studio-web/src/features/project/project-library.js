export function createProjectLibrary({ service, current, open, create, save, importFile }) {
  const host = document.createElement("section");
  host.className = "project-library";
  host.innerHTML = `
    <button class="project-switcher" type="button" aria-expanded="false" aria-controls="project-library-panel">
      <span class="project-current-name">我的作品</span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>
    </button>
    <span class="project-save-state" role="status">本机项目</span>
    <section id="project-library-panel" class="project-library-panel" aria-label="项目管理" hidden>
      <header><h2>我的作品</h2><button type="button" data-new>新建作品</button></header>
      <input type="search" aria-label="搜索作品" placeholder="搜索作品名称">
      <p class="project-library-error" role="alert" hidden></p>
      <div class="project-library-list"></div>
      <footer><button type="button" data-import>导入工程文件</button><button type="button" data-save>立即保存</button></footer>
      <small>作品保存在本机。切换前自动保存当前作品。</small>
    </section>`;
  document.querySelector(".control-bar").before(host);
  const trigger = host.querySelector(".project-switcher");
  const panel = host.querySelector("#project-library-panel");
  const list = host.querySelector(".project-library-list");
  const error = host.querySelector(".project-library-error");
  const search = host.querySelector("input");
  let items = [], busy = false, request = 0;
  function close() { panel.hidden = true; trigger.setAttribute("aria-expanded", "false"); }
  function report(message) { error.textContent = message; error.hidden = !message; }
  function renderList() {
    list.replaceChildren();
    const matches = items.filter(item => (item.name || "").toLocaleLowerCase().includes(search.value.toLocaleLowerCase()));
    for (const item of matches) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "project-library-item";
      const active = item.id === current()?.project_id;
      button.setAttribute("aria-current", String(active));
      button.disabled = busy || active;
      const title = document.createElement("strong"); title.textContent = item.name || "未命名作品";
      const meta = document.createElement("span");
      meta.textContent = `${active ? "当前作品 · " : ""}${item.track_count} 轨 · ${new Date(item.updated_at).toLocaleString("zh-CN", {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})}`;
      button.append(title, meta);
      button.onclick = () => run(async () => { await open(item.id); close(); });
      list.append(button);
    }
    if (!matches.length) { const p = document.createElement("p"); p.textContent = search.value ? "没有匹配的作品" : "还没有保存的作品，新建后会自动出现在这里。"; list.append(p); }
  }
  async function run(operation) {
    if (busy) return;
    busy = true; report(""); renderList();
    host.querySelectorAll("footer button, [data-new]").forEach(button => button.disabled = true);
    try { await operation(); } catch (e) { report(e.message || "操作失败，请重试"); }
    finally { busy = false; host.querySelectorAll("footer button, [data-new]").forEach(button => button.disabled = false); renderList(); }
  }
  trigger.onclick = async () => {
    if (!panel.hidden) { close(); return; }
    panel.hidden = false; trigger.setAttribute("aria-expanded", "true"); search.focus();
    const token = ++request; list.textContent = "正在读取作品…"; report("");
    try { await save(); const result = await service().listProjects(); if (token === request) { items = result; renderList(); } }
    catch (e) { list.textContent = ""; report(`无法读取项目：${e.message}`); }
  };
  search.oninput = renderList;
  host.querySelector("[data-new]").onclick = () => { close(); create(); };
  host.querySelector("[data-import]").onclick = () => { close(); importFile(); };
  host.querySelector("[data-save]").onclick = () => run(async () => { await save(); items = await service().listProjects(); });
  document.addEventListener("click", event => { if (!host.contains(event.target)) close(); });
  host.addEventListener("keydown", event => {
    if (event.key === "Escape") { event.stopPropagation(); close(); trigger.focus(); }
  });
  return {
    render() { host.querySelector(".project-current-name").textContent = current()?.name || "我的作品"; },
    status(text, failed = false) { const label = host.querySelector(".project-save-state"); label.textContent = text; label.dataset.failed = String(failed); },
  };
}
