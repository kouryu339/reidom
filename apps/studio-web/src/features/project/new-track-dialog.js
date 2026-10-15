export const INSTRUMENTS = { piano: "钢琴", lead: "主音合成器", guitar: "吉他", bass: "贝斯", pad: "氛围合成器", drums: "鼓组" };
let active = false;
export function requestNewTrack(number) {
  if (active) return Promise.resolve(null);
  active = true;
  const dialog = document.createElement("dialog");
  dialog.className = "settings-dialog new-project-dialog";
  dialog.setAttribute("aria-labelledby", "new-track-title");
  dialog.innerHTML = `<form><h2 id="new-track-title">添加轨道</h2>
    <label>轨道名称<input name="name" required maxlength="80" value="轨道 ${number}" autofocus></label>
    <label>内置音源<select name="instrument">${Object.entries(INSTRUMENTS).map(([value,label]) => `<option value="${value}">${label}</option>`).join("")}</select></label>
    <p>所选音源将用于播放这条轨道的 MIDI 音符。</p>
    <footer><button type="button">取消</button><button type="submit">添加轨道</button></footer></form>`;
  document.body.append(dialog);
  return new Promise(resolve => {
    let result = null;
    dialog.addEventListener("close", () => { active = false; dialog.remove(); resolve(result); }, { once: true });
    dialog.querySelector('button[type="button"]').onclick = () => dialog.close();
    const input = dialog.querySelector("input");
    input.oninput = () => input.setCustomValidity("");
    dialog.querySelector("form").onsubmit = event => {
      event.preventDefault();
      if (!input.value.trim()) { input.setCustomValidity("请输入轨道名称"); input.reportValidity(); return; }
      result = { name: input.value.trim(), instrument: dialog.querySelector("select").value };
      dialog.close();
    };
    dialog.showModal(); input.select();
  });
}
