let activeDialog = null;

export function requestNewProject({ dirty = false } = {}) {
  if (activeDialog) return Promise.resolve(null);
  const dialog = document.createElement("dialog");
  activeDialog = dialog;
  dialog.className = "settings-dialog new-project-dialog";
  dialog.setAttribute("aria-labelledby", "new-project-title");
  dialog.innerHTML = `
    <form>
      <h2 id="new-project-title">新建作品</h2>
      <label>作品名称<input name="name" maxlength="120" value="未命名作品" required autofocus></label>
      <label>速度（BPM）<input name="tempo" type="number" min="20" max="300" step="1" value="120" required></label>
      <p>当前作品会先保存到本机。新作品可以交给 AI 编曲，或进入手动编辑添加轨道。</p>
      <p class="unsaved-warning" ${dirty ? "" : "hidden"}>当前作品有未保存修改。创建后将替换当前作品；需要保留时，请先取消并保存。</p>
      <footer><button type="button" data-cancel>取消</button><button type="submit">创建作品</button></footer>
    </form>`;
  document.body.append(dialog);
  return new Promise((resolve) => {
    let result = null;
    dialog.addEventListener("close", () => {
      activeDialog = null;
      dialog.remove();
      document.querySelector("#new-project")?.focus();
      resolve(result);
    }, { once: true });
    dialog.querySelector("[data-cancel]").onclick = () => dialog.close();
    dialog.querySelector("form").onsubmit = (event) => {
      event.preventDefault();
      const name = dialog.querySelector('[name="name"]');
      if (!name.value.trim()) { name.setCustomValidity("请输入作品名称"); name.reportValidity(); return; }
      result = { name: name.value.trim(), tempo: Number(dialog.querySelector('[name="tempo"]').value) };
      dialog.close();
    };
    dialog.querySelector('[name="name"]').oninput = (event) => event.target.setCustomValidity("");
    dialog.showModal();
    dialog.querySelector('[name="name"]').select();
  });
}
