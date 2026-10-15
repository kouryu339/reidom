export function createDeviceSettingsController({ dialog, service, status }) {
  if (!dialog) return { open() {}, close() {} };
  const form = dialog.querySelector("form");
  const output = dialog.querySelector("#audio-output-device");
  const sampleRate = dialog.querySelector("#audio-sample-rate");
  const bufferSize = dialog.querySelector("#audio-buffer-size");
  const midiInputs = dialog.querySelector("#midi-input-list");
  const diagnostic = dialog.querySelector("#device-diagnostic");

  function option(value, label, selected) {
    const item = document.createElement("option");
    item.value = String(value);
    item.textContent = label;
    item.selected = selected;
    return item;
  }

  function render(settings) {
    const audio = settings?.audio || {};
    output.replaceChildren(
      ...(audio.output_devices || []).map((device) =>
        option(device.name, `${device.name} · ${device.type}`, device.name === audio.output_device),
      ),
    );
    sampleRate.replaceChildren(
      ...(audio.sample_rates || []).map((rate) =>
        option(rate, `${Math.round(Number(rate))} Hz`, Number(rate) === Number(audio.sample_rate)),
      ),
    );
    bufferSize.replaceChildren(
      ...(audio.buffer_sizes || []).map((size) =>
        option(size, `${size} samples`, Number(size) === Number(audio.buffer_size)),
      ),
    );
    midiInputs.replaceChildren(
      ...(settings?.midi_inputs || []).map((device) => {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = device.id;
        checkbox.checked = Boolean(device.enabled);
        label.append(checkbox, document.createTextNode(device.name));
        return label;
      }),
    );
    diagnostic.textContent = audio.output_device
      ? `当前输出：${audio.output_device}`
      : "没有可用的音频输出设备";
  }

  async function open() {
    try {
      status.busy("正在读取音频设备…");
      render(await service.deviceSettings());
      status.clear();
      dialog.showModal();
    } catch (error) {
      status.error(`无法读取设备：${error.message}`);
    }
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      status.busy("正在切换音频设备…");
      const settings = await service.configureDevices({
        outputDevice: output.value,
        sampleRate: sampleRate.value,
        bufferSize: bufferSize.value,
        midiInputIds: [...midiInputs.querySelectorAll("input:checked")].map((input) => input.value),
      });
      render(settings);
      status.success("音频与 MIDI 设备已更新");
      dialog.close();
    } catch (error) {
      diagnostic.textContent = error.message;
      status.error(`设备切换失败：${error.message}`);
    }
  });
  dialog.querySelectorAll("[data-dialog-close]").forEach((button) =>
    button.addEventListener("click", () => dialog.close()),
  );

  return { open, close: () => dialog.close() };
}
