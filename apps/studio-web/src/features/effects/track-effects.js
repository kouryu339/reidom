const INSTRUMENTS = [
  ["piano", "钢琴"],
  ["electric-guitar", "电吉他"],
  ["electric-bass", "电贝斯"],
  ["synth-lead", "合成器主奏"],
  ["warm-pad", "温暖 Pad"],
  ["drum-kit", "鼓组"],
];

const EFFECTS = [
  {
    id: "eq",
    name: "三段均衡",
    code: "EQ",
    description: "修整低频、主体与明亮度",
    parameters: [
      { key: "low_gain_db", label: "低频", min: -12, max: 12, step: 0.5, unit: "db" },
      { key: "mid_gain_db", label: "中频", min: -12, max: 12, step: 0.5, unit: "db" },
      { key: "high_gain_db", label: "高频", min: -12, max: 12, step: 0.5, unit: "db" },
    ],
  },
  {
    id: "compressor",
    name: "压缩器",
    code: "COMP",
    description: "收住动态，让声音更稳定",
    parameters: [
      { key: "threshold_db", label: "阈值", min: -48, max: 0, step: 1, unit: "db" },
      { key: "ratio", label: "比例", min: 1, max: 12, step: 0.5, unit: "ratio" },
    ],
  },
  {
    id: "delay",
    name: "延迟",
    code: "DLY",
    description: "增加节奏回声与空间层次",
    parameters: [
      { key: "time_ms", label: "时间", min: 20, max: 1500, step: 10, unit: "ms" },
      { key: "feedback", label: "反馈", min: 0, max: 0.82, step: 0.01, unit: "percent" },
      { key: "mix", label: "混合", min: 0, max: 0.65, step: 0.01, unit: "percent" },
    ],
  },
  {
    id: "reverb",
    name: "混响",
    code: "VERB",
    description: "为轨道增加自然空间感",
    parameters: [
      { key: "room_size", label: "空间", min: 0, max: 1, step: 0.01, unit: "percent" },
      { key: "mix", label: "混合", min: 0, max: 0.65, step: 0.01, unit: "percent" },
    ],
  },
];

export function countEnabledEffects(track) {
  return EFFECTS.reduce((count, effect) => count + (track?.effects?.[effect.id]?.enabled ? 1 : 0), 0);
}

export function createTrackEffectsController({
  root,
  getTrack,
  executeCommand,
  updateRoute,
  resolveInstrumentRole,
  onClose,
}) {
  if (!root) return { render() {} };

  root.addEventListener("click", (event) => {
    const close = event.target.closest("[data-close-track-effects]");
    if (close) {
      onClose();
      return;
    }

    const routeButton = event.target.closest("[data-route-toggle]");
    if (routeButton) {
      const track = getTrack();
      if (!track) return;
      const key = routeButton.dataset.routeToggle;
      void updateRoute(track.track_id, { [key]: !Boolean(track[key]) });
      return;
    }

    const powerButton = event.target.closest("[data-effect-toggle]");
    if (powerButton) {
      const track = getTrack();
      if (!track) return;
      const effect = powerButton.dataset.effectToggle;
      const enabled = Boolean(track.effects?.[effect]?.enabled);
      void executeCommand("effects.set_state", {
        track_id: track.track_id,
        effect,
        enabled: !enabled,
        parameters: {},
      });
    }
  });

  root.addEventListener("input", (event) => {
    const input = event.target.closest("[data-effect-param], [data-route-range]");
    if (!input) return;
    const output = input.closest("label")?.querySelector("output");
    if (output) output.textContent = formatValue(Number(input.value), input.dataset.unit);
  });

  root.addEventListener("change", (event) => {
    const track = getTrack();
    if (!track) return;
    const target = event.target;

    if (target.matches("[data-track-name]")) {
      const name = target.value.trim();
      if (!name) {
        target.value = track.name || "";
        return;
      }
      if (name !== track.name) {
        void executeCommand("tracks.rename", { track_id: track.track_id, name });
      }
      return;
    }

    if (target.matches("[data-track-instrument]")) {
      void executeCommand("tracks.set_instrument", {
        track_id: track.track_id,
        instrument: target.value,
        role: resolveInstrumentRole(target.value),
      });
      return;
    }

    if (target.matches("[data-route-range]")) {
      const key = target.dataset.routeRange;
      void updateRoute(track.track_id, { [key]: Number(target.value) });
      return;
    }

    if (target.matches("[data-effect-param]")) {
      const effect = target.dataset.effect;
      const key = target.dataset.effectParam;
      void executeCommand("effects.set_state", {
        track_id: track.track_id,
        effect,
        parameters: { [key]: Number(target.value) },
      });
    }
  });

  function render() {
    const track = getTrack();
    root.replaceChildren();
    if (!track) {
      const empty = element("div", "track-effects-empty");
      empty.append(
        element("strong", "", "未选择轨道"),
        element("span", "", "在编曲区选择一条轨道后即可调整音源、混音和效果。"),
      );
      root.append(empty);
      return;
    }

    root.style.setProperty("--detail-track-color", track.color || "#70e1c2");
    root.append(createHeader(track), createBody(track));
  }

  function createHeader(track) {
    const header = element("header", "detail-panel-header");
    const title = element("div", "detail-panel-title");
    title.append(
      element("span", "detail-kicker", "轨道声音"),
      element("strong", "", track.name || track.track_id),
      element("small", "", countEnabledEffects(track) + " 个效果已启用"),
    );
    const close = element("button", "detail-close", "×");
    close.type = "button";
    close.dataset.closeTrackEffects = "";
    close.title = "关闭轨道设置";
    close.setAttribute("aria-label", "关闭轨道设置");
    header.append(title, close);
    return header;
  }

  function createBody(track) {
    const body = element("div", "track-effects-body");
    body.append(createTrackStrip(track));

    const rack = element("div", "builtin-effects-rack");
    EFFECTS.forEach((effect, index) => {
      rack.append(createEffectCard(effect, track.effects?.[effect.id] || {}, index));
    });
    body.append(rack);
    return body;
  }

  function createTrackStrip(track) {
    const strip = element("section", "track-strip");
    const heading = element("div", "track-strip-heading");
    heading.append(element("span", "track-color-swatch"), element("strong", "", "轨道"));
    strip.append(heading);

    const nameLabel = element("label", "detail-field");
    nameLabel.append(element("span", "", "名称"));
    const name = document.createElement("input");
    name.type = "text";
    name.maxLength = 80;
    name.value = track.name || "";
    name.dataset.trackName = "";
    nameLabel.append(name);

    const instrumentLabel = element("label", "detail-field");
    instrumentLabel.append(element("span", "", "音源"));
    const instrument = document.createElement("select");
    instrument.dataset.trackInstrument = "";
    INSTRUMENTS.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = value === (track.instrument_ref || track.instrument);
      instrument.append(option);
    });
    instrumentLabel.append(instrument);

    const toggles = element("div", "track-state-toggles");
    [
      ["arm", "R", "录音预备"],
      ["monitor", "I", "输入监听"],
      ["mute", "M", "静音"],
      ["solo", "S", "独奏"],
    ].forEach(([key, label, title]) => {
      const button = element("button", track[key] ? "active" : "", label);
      button.type = "button";
      button.dataset.routeToggle = key;
      button.title = title;
      toggles.append(button);
    });

    strip.append(
      nameLabel,
      instrumentLabel,
      toggles,
      createRange("音量", "volume", Number(track.volume ?? 0.85), 0, 1.5, 0.01, "percent"),
      createRange("声像", "pan", Number(track.pan ?? 0), -1, 1, 0.01, "pan"),
    );
    return strip;
  }

  function createEffectCard(definition, settings, index) {
    const card = element("article", "effect-module" + (settings.enabled ? " enabled" : ""));
    card.style.setProperty("--module-index", String(index));

    const header = element("header", "effect-module-header");
    const identity = element("div", "effect-identity");
    identity.append(
      element("span", "effect-code", definition.code),
      element("div", "", definition.name),
    );
    const power = element("button", "effect-power" + (settings.enabled ? " active" : ""), settings.enabled ? "开" : "关");
    power.type = "button";
    power.dataset.effectToggle = definition.id;
    power.setAttribute("aria-pressed", String(Boolean(settings.enabled)));
    power.title = settings.enabled ? "旁路此效果" : "启用此效果";
    header.append(identity, power);

    card.append(header, element("p", "", definition.description));
    const controls = element("div", "effect-controls");
    definition.parameters.forEach((parameter) => {
      controls.append(createEffectRange(definition.id, parameter, Number(settings[parameter.key] ?? parameter.min)));
    });
    card.append(controls);
    return card;
  }

  return { render };
}

function createRange(label, key, value, min, max, step, unit) {
  const field = element("label", "rack-range");
  const heading = element("span", "rack-range-label");
  heading.append(element("span", "", label), outputFor(value, unit));
  const input = document.createElement("input");
  input.type = "range";
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.value = String(value);
  input.dataset.routeRange = key;
  input.dataset.unit = unit;
  field.append(heading, input);
  return field;
}

function createEffectRange(effect, parameter, value) {
  const field = element("label", "rack-range");
  const heading = element("span", "rack-range-label");
  heading.append(element("span", "", parameter.label), outputFor(value, parameter.unit));
  const input = document.createElement("input");
  input.type = "range";
  input.min = String(parameter.min);
  input.max = String(parameter.max);
  input.step = String(parameter.step);
  input.value = String(value);
  input.dataset.effect = effect;
  input.dataset.effectParam = parameter.key;
  input.dataset.unit = parameter.unit;
  field.append(heading, input);
  return field;
}

function outputFor(value, unit) {
  const output = document.createElement("output");
  output.textContent = formatValue(value, unit);
  return output;
}

function formatValue(value, unit) {
  if (unit === "db") return (value > 0 ? "+" : "") + value.toFixed(1) + " dB";
  if (unit === "ms") return Math.round(value) + " ms";
  if (unit === "ratio") return value.toFixed(1) + ":1";
  if (unit === "percent") return Math.round(value * 100) + "%";
  if (unit === "pan") {
    if (Math.abs(value) < 0.01) return "C";
    return (value < 0 ? "L " : "R ") + Math.round(Math.abs(value) * 100);
  }
  return String(value);
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}
