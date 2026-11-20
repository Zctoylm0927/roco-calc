"use strict";

const STAT_NAMES = {
  hp: "生命",
  atk: "物攻",
  def: "物防",
  spa: "魔攻",
  spd: "魔防",
  spe: "速度",
};

const STAT_ORDER = ["hp", "atk", "def", "spa", "spd", "spe"];
const BUFF_KEYS = ["atk", "def", "spa", "spd", "spe"];
const TALENT_VALUES = [0, 7, 8, 9, 10];
const STORAGE_KEY = "roco-calc-state-v1";

const KNOCKOUT_TEXT = {
  certain: "一定击倒",
  possible: "可能击倒",
  impossible: "不能击倒",
};

let meta = null;
let requestId = 0;
let calcTimer = null;

const state = {
  ourPetIndex: 0,
  oppPetIndex: 0,
  nature: "",
  talents: { hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0 },
  ourBuffs: { atk: 0, def: 0, spa: 0, spd: 0, spe: 0 },
  oppBuffs: { atk: 0, def: 0, spa: 0, spd: 0, spe: 0 },
  skill: "",
  weather: "",
  starfall: 0,
  hits: 1,
  records: [],
  nextId: 1,
};

const $ = (id) => document.getElementById(id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function fact(label, value) {
  const box = element("div", "fact");
  box.append(element("span", "", label), element("b", "", value));
  return box;
}

function petLabel(pet) {
  return pet.form ? `${pet.name}（${pet.form}）` : pet.name;
}

function findPetIndex(name) {
  const index = meta.pets.findIndex((pet) => pet.name === name && !pet.form);
  return index >= 0 ? index : 0;
}

function clampInteger(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isInteger(number)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, number));
}

function clampIndex(value, length, fallback) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 0 || number >= length) {
    return fallback;
  }
  return number;
}

function safeBuff(value) {
  return Number.isInteger(value) ? Math.max(-99, Math.min(99, value)) : 0;
}

function sanitizeBuffs(raw) {
  const result = {};
  for (const key of BUFF_KEYS) {
    result[key] = safeBuff(raw && raw[key]);
  }
  return result;
}

/* ---------- 本地保存 ---------- */

function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (error) {
    // 浏览器禁用本地存储时，只影响刷新后恢复，不影响计算。
  }
}

function sanitizeRecord(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  if (raw.type === "damage") {
    const damage = Number(raw.damage);
    if (!Number.isInteger(damage) || damage < 0) {
      return null;
    }
    const skill =
      typeof raw.skill === "string" &&
      meta.skills.some((item) => item.name === raw.skill)
        ? raw.skill
        : state.skill;
    return {
      id: Number.isInteger(raw.id) && raw.id > 0 ? raw.id : 0,
      type: "damage",
      damage,
      hits: clampInteger(raw.hits, 1, 99, 1),
      skill,
      weather: raw.weather === "雨天" ? "雨天" : null,
      ourBuffs: sanitizeBuffs(raw.ourBuffs),
      theirBuffs: sanitizeBuffs(raw.theirBuffs),
      starfall: clampInteger(raw.starfall, 0, 99, 0),
      matched: null,
      kept: null,
      message: null,
    };
  }
  if (raw.type === "hp_percent") {
    const percent = Number(raw.hpPercent ?? raw.hp_percent);
    const total = Number(raw.totalDamage ?? raw.total_damage);
    if (!Number.isInteger(percent) || percent < 0 || percent > 100) {
      return null;
    }
    if (!Number.isInteger(total) || total < 0) {
      return null;
    }
    return {
      id: Number.isInteger(raw.id) && raw.id > 0 ? raw.id : 0,
      type: "hp_percent",
      hpPercent: percent,
      totalDamage: total,
      totalAuto: raw.totalAuto !== false,
      matched: null,
      kept: null,
      message: null,
    };
  }
  return null;
}

function restoreSaved() {
  let saved;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return;
    }
    saved = JSON.parse(raw);
  } catch (error) {
    return;
  }
  if (!saved || typeof saved !== "object") {
    return;
  }

  state.ourPetIndex = clampIndex(
    saved.ourPetIndex,
    meta.pets.length,
    state.ourPetIndex
  );
  state.oppPetIndex = clampIndex(
    saved.oppPetIndex,
    meta.pets.length,
    state.oppPetIndex
  );

  if (
    typeof saved.nature === "string" &&
    (saved.nature === "" ||
      meta.natures.some((nature) => nature.name === saved.nature))
  ) {
    state.nature = saved.nature;
  }

  for (const key of STAT_ORDER) {
    const value = saved.talents && Number(saved.talents[key]);
    if (TALENT_VALUES.includes(value)) {
      state.talents[key] = value;
    }
  }

  state.ourBuffs = sanitizeBuffs(saved.ourBuffs);
  state.oppBuffs = sanitizeBuffs(saved.oppBuffs);

  if (typeof saved.skill === "string") {
    if (meta.skills.some((skill) => skill.name === saved.skill)) {
      state.skill = saved.skill;
    }
  }
  state.weather = saved.weather === "雨天" ? "雨天" : "";
  state.starfall = clampInteger(saved.starfall, 0, 99, 0);
  state.hits = clampInteger(saved.hits, 1, 99, 1);

  if (Array.isArray(saved.records)) {
    state.records = saved.records.map(sanitizeRecord).filter(Boolean);
  }

  let autoId = 1;
  const usedIds = new Set(
    state.records.map((record) => record.id).filter((id) => id > 0)
  );
  for (const record of state.records) {
    if (record.id <= 0) {
      while (usedIds.has(autoId)) {
        autoId += 1;
      }
      record.id = autoId;
      usedIds.add(autoId);
    }
  }
  const maxId = state.records.reduce(
    (maximum, record) => Math.max(maximum, record.id),
    0
  );
  state.nextId = Math.max(1, maxId + 1);
}

/* ---------- 页面上半部分 ---------- */

function fillPets(select, selectedIndex) {
  select.replaceChildren();
  meta.pets.forEach((pet, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = petLabel(pet);
    select.append(option);
  });
  select.value = String(selectedIndex);
}

function fillNatures(select) {
  select.replaceChildren();
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "无（不加不减）";
  select.append(none);
  for (const nature of meta.natures) {
    const option = document.createElement("option");
    option.value = nature.name;
    option.textContent = `${nature.name}（↑${nature.up_name} ↓${nature.down_name}）`;
    select.append(option);
  }
  select.value = state.nature;
}

function buildTalentControls() {
  const box = $("our-talents");
  box.replaceChildren();
  for (const key of STAT_ORDER) {
    const label = document.createElement("label");
    label.append(document.createTextNode(STAT_NAMES[key]));
    const select = document.createElement("select");
    for (const value of TALENT_VALUES) {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = String(value);
      select.append(option);
    }
    select.value = String(state.talents[key]);
    select.addEventListener("change", () => {
      state.talents[key] = Number(select.value);
      scheduleCalculate();
    });
    label.append(select);
    box.append(label);
  }
}

function buildBuffControls(side) {
  const box = $(side === "our" ? "our-buffs" : "opp-buffs");
  const values = side === "our" ? state.ourBuffs : state.oppBuffs;
  box.replaceChildren();

  for (const key of BUFF_KEYS) {
    const row = element("div", "buff");
    const label = element("span", "", STAT_NAMES[key]);
    const minus = element("button", "", "−");
    const value = element("span", "value", "0");
    const plus = element("button", "", "＋");
    minus.type = "button";
    plus.type = "button";

    const update = () => {
      const current = values[key];
      value.textContent = current > 0 ? `+${current}` : String(current);
      value.className =
        "value" +
        (current > 0 ? " positive" : current < 0 ? " negative" : "");
    };
    minus.addEventListener("click", () => {
      values[key] = Math.max(-99, values[key] - 1);
      update();
      scheduleCalculate();
    });
    plus.addEventListener("click", () => {
      values[key] = Math.min(99, values[key] + 1);
      update();
      scheduleCalculate();
    });

    update();
    row.append(label, minus, value, plus);
    box.append(row);
  }
}

function skillMatches(skill, filter) {
  if (!filter) {
    return true;
  }
  return (
    skill.name.includes(filter) ||
    skill.element.includes(filter) ||
    skill.damage_class.includes(filter)
  );
}

function fillSkills(filterText) {
  const select = $("skill");
  const filter = filterText.trim();
  select.replaceChildren();

  const groups = new Map();
  for (const skill of meta.skills) {
    if (!skillMatches(skill, filter)) {
      continue;
    }
    if (!groups.has(skill.element)) {
      groups.set(skill.element, []);
    }
    groups.get(skill.element).push(skill);
  }
  const elements = [...groups.keys()].sort((a, b) =>
    a.localeCompare(b, "zh-CN")
  );
  for (const elementName of elements) {
    const group = document.createElement("optgroup");
    group.label = elementName;
    for (const skill of groups.get(elementName)) {
      const option = document.createElement("option");
      option.value = skill.name;
      option.textContent = `${skill.name}（${skill.damage_class} ${skill.power}）`;
      group.append(option);
    }
    select.append(group);
  }

  if ([...select.options].some((option) => option.value === state.skill)) {
    select.value = state.skill;
  } else if (select.options.length > 0) {
    state.skill = select.options[0].value;
    select.value = state.skill;
  } else {
    state.skill = "";
  }
  updateSkillInfo();
}

function updateSkillInfo() {
  const skill = meta.skills.find((item) => item.name === state.skill);
  const info = $("skill-info");
  if (!skill) {
    info.textContent = "没有找到符合筛选条件的技能。";
    return;
  }
  info.textContent =
    `${skill.name} · ${skill.element} · ${skill.damage_class} · ` +
    `威力 ${skill.power}` +
    (skill.energy === null ? "" : ` · 能耗 ${skill.energy}`);
}

function activeTalents() {
  const result = {};
  for (const key of STAT_ORDER) {
    if (state.talents[key]) {
      result[key] = state.talents[key];
    }
  }
  return result;
}

function scheduleCalculate() {
  // 改动后旧请求的结果已经过时，先把它的编号作废。
  requestId += 1;
  saveState();
  clearTimeout(calcTimer);
  calcTimer = setTimeout(calculate, 200);
}

function setStatus(text, isError) {
  const status = $("status");
  status.textContent = text;
  status.className = isError ? "status error" : "status";
}

function setRecordStatus(text, isError) {
  const status = $("record-status");
  status.textContent = text;
  status.className = isError ? "status error" : "status";
}

function validateState() {
  const nonzero = STAT_ORDER.filter((key) => state.talents[key] > 0);
  if (nonzero.length > 3) {
    return "我方天分最多只能给三项能力加成，请去掉一项。";
  }
  if (!state.skill) {
    return "请选择一个技能。";
  }
  if (
    !Number.isInteger(state.starfall) ||
    state.starfall < 0 ||
    state.starfall > 99
  ) {
    return "星陨层数必须是 0～99 的整数。";
  }
  if (!Number.isInteger(state.hits) || state.hits < 1 || state.hits > 99) {
    return "连击次数必须是 1～99 的整数。";
  }
  return null;
}

async function calculate() {
  if (!meta) {
    return;
  }
  const problem = validateState();
  if (problem) {
    setStatus(problem, true);
    return;
  }

  const our = meta.pets[state.ourPetIndex];
  const opponent = meta.pets[state.oppPetIndex];
  refreshAutoTotals();
  const payload = {
    our_pet: {
      name: our.name,
      form: our.form || null,
      nature: state.nature || null,
      talents: activeTalents(),
      buffs: state.ourBuffs,
    },
    opponent_pet: {
      name: opponent.name,
      form: opponent.form || null,
      buffs: state.oppBuffs,
    },
    skill: state.skill,
    weather: state.weather || null,
    starfall_layers: state.starfall,
    hits: state.hits,
    observations: state.records.map(recordToObservation),
  };

  const id = ++requestId;
  setStatus("计算中…");
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (id !== requestId) {
      return;
    }
    if (!response.ok) {
      throw new Error(data.error || "计算失败。");
    }
    renderOur(data.our);
    renderOpponent(data.opponent);
    renderDamage(data.damage, data.opponent);
    updateRecordResults(data.opponent);
    setStatus("");
  } catch (error) {
    if (id !== requestId) {
      return;
    }
    setStatus(error.message || "计算失败，请看 server.py 窗口。", true);
  }
}

function renderOur(our) {
  const list = $("our-stats");
  list.replaceChildren();
  for (const key of STAT_ORDER) {
    const row = document.createElement("li");
    row.append(
      element("span", "", STAT_NAMES[key]),
      element("b", "", String(our.stats[key]))
    );
    if (key === "spe" && our.buffs.spe) {
      row.append(
        element("small", "values", `增减益后 ${our.speed_after_buffs}`)
      );
    }
    list.append(row);
  }
}

function renderOpponent(opponent) {
  const list = $("opp-stats");
  list.replaceChildren();
  for (const key of STAT_ORDER) {
    const item = opponent.stats[key];
    const values = item.possible_values;
    const text =
      item.min === item.max ? String(item.min) : `${item.min} ～ ${item.max}`;
    const row = document.createElement("li");
    const detail = element("small", "values", `${values.length} 种`);
    detail.title = values.join("、");
    row.append(
      element("span", "", STAT_NAMES[key]),
      element("b", "", text),
      detail
    );
    list.append(row);
  }

  const details = $("nature-details");
  const summary = $("nature-summary");
  const chips = $("nature-list");
  chips.replaceChildren();
  if (opponent.possible_natures.length === 0) {
    details.hidden = true;
    return;
  }
  details.hidden = false;
  summary.textContent = `可能性格 ${opponent.natures_remaining} 种（点开查看）`;
  for (const name of opponent.possible_natures) {
    chips.append(element("li", "", name));
  }
}

function renderDamage(damage, opponent) {
  const box = $("damage-result");
  box.replaceChildren();

  const headline = element("div", "headline");
  headline.append(
    element("span", "", "伤害范围"),
    element("strong", "", `${damage.min} ～ ${damage.max}`)
  );
  box.append(headline);

  const facts = element("div", "facts");
  facts.append(
    fact(
      "占对方生命",
      `${damage.damage_percent_min}% ～ ${damage.damage_percent_max}%`
    ),
    fact("击倒判断", KNOCKOUT_TEXT[damage.knockout] || damage.knockout),
    fact(
      "对方可能组合",
      `${opponent.builds.remaining.toLocaleString("zh-CN")} / ` +
        opponent.builds.total.toLocaleString("zh-CN")
    ),
    fact("对方可能性格", `${opponent.natures_remaining} 种`)
  );
  box.append(facts);

  const defenseName = STAT_NAMES[damage.defense_key];
  box.append(
    element(
      "p",
      "note",
      `按对方${defenseName}计算：${defenseName}最高 ` +
        `${damage.min_case_defense} → 伤害 ${damage.min}；` +
        `${defenseName}最低 ${damage.max_case_defense} → 伤害 ${damage.max}。`
    )
  );
}

/* ---------- 战斗记录 ---------- */

function cumulativeDamage() {
  return state.records
    .filter((record) => record.type === "damage")
    .reduce((sum, record) => sum + record.damage, 0);
}

function refreshAutoTotals() {
  let running = 0;
  for (const record of state.records) {
    if (record.type === "damage") {
      running += record.damage;
    } else if (record.totalAuto) {
      record.totalDamage = running;
    }
  }
}

function recordToObservation(record) {
  if (record.type === "damage") {
    return {
      type: "damage",
      attacker: "our",
      skill: record.skill,
      damage: record.damage,
      hits: record.hits,
      weather: record.weather,
      our_buffs: record.ourBuffs,
      their_buffs: record.theirBuffs,
      starfall_layers: record.starfall,
    };
  }
  return {
    type: "hp_percent",
    hp_percent: record.hpPercent,
    total_damage: record.totalDamage,
  };
}

function buffSummary(buffs) {
  const parts = [];
  for (const key of BUFF_KEYS) {
    const value = buffs[key];
    if (value) {
      parts.push(`${STAT_NAMES[key]}${value > 0 ? `+${value}` : value}`);
    }
  }
  return parts.join("，");
}

function recordContextText(record) {
  if (record.type === "hp_percent") {
    return (
      `累计伤害 ${record.totalDamage}` +
      (record.totalAuto ? "（自动累计）" : "（手动填写）")
    );
  }
  const parts = [record.skill, record.weather || "无天气"];
  const our = buffSummary(record.ourBuffs);
  const theirs = buffSummary(record.theirBuffs);
  if (our) {
    parts.push(`我方 ${our}`);
  }
  if (theirs) {
    parts.push(`对方 ${theirs}`);
  }
  if (record.starfall) {
    parts.push(`星陨 ${record.starfall} 层`);
  }
  if (record.hits !== 1) {
    parts.push(`${record.hits} 连击`);
  }
  return parts.join(" · ");
}

function markRecordPending(record) {
  record.matched = null;
  record.kept = null;
  record.message = null;
  const node = document.querySelector(
    `.record-result[data-id="${record.id}"]`
  );
  if (node) {
    node.className = "record-result";
    node.textContent = "等待计算…";
  }
}

function markAllRecordsPending() {
  for (const record of state.records) {
    record.matched = null;
    record.kept = null;
    record.message = null;
  }
}

function recordResultText(record) {
  if (record.matched === true) {
    return `对上了 · 剩 ${record.kept.toLocaleString("zh-CN")} 种组合`;
  }
  if (record.matched === false) {
    return `没对上，已跳过：${record.message}`;
  }
  return "等待计算…";
}

function updateRecordContext(record) {
  const node = document.querySelector(
    `.record-context[data-id="${record.id}"]`
  );
  if (node) {
    node.textContent = recordContextText(record);
  }
}

function recordResultClass(record) {
  if (record.matched === true) {
    return "record-result ok";
  }
  if (record.matched === false) {
    return "record-result bad";
  }
  return "record-result";
}

function numberField(labelText, getValue, onChange, options) {
  const settings = options || {};
  const min = settings.min === undefined ? 0 : settings.min;
  const max = settings.max;
  const label = element("label", "record-field");
  label.append(document.createTextNode(labelText));
  const input = document.createElement("input");
  input.type = "number";
  input.min = String(min);
  if (max !== undefined) {
    input.max = String(max);
  }
  input.step = "1";
  input.value = String(getValue());
  input.addEventListener("change", () => {
    const raw = input.value.trim();
    const value = Number(raw);
    if (
      raw === "" ||
      !Number.isInteger(value) ||
      value < min ||
      (max !== undefined && value > max)
    ) {
      setRecordStatus(
        `${labelText}必须是 ${min}${max === undefined ? " 以上" : `～${max}`} 的整数。`,
        true
      );
      input.value = String(getValue());
      return;
    }
    setRecordStatus("");
    onChange(value);
    input.value = String(getValue());
  });
  label.append(input);
  return label;
}

function renderRecords() {
  const list = $("record-list");
  list.replaceChildren();
  if (state.records.length === 0) {
    list.append(element("li", "hint", "还没有记录。打了一次之后，把伤害或剩余生命百分比填到上面。"));
    return;
  }

  state.records.forEach((record, index) => {
    const item = element("li", "record");
    const main = element("div", "record-main");
    main.append(element("span", "record-index", String(index + 1)));

    if (record.type === "damage") {
      main.append(element("span", "record-type", "伤害"));
      main.append(
        numberField(
          "伤害",
          () => record.damage,
          (value) => {
            record.damage = value;
            refreshAutoTotals();
            markAllRecordsPending();
            renderRecords();
            saveState();
            scheduleCalculate();
          },
          { min: 0 }
        )
      );
      main.append(
        numberField(
          "连击",
          () => record.hits,
          (value) => {
            record.hits = value;
            updateRecordContext(record);
            markRecordPending(record);
            saveState();
            scheduleCalculate();
          },
          { min: 1, max: 99 }
        )
      );
    } else {
      main.append(element("span", "record-type", "生命 %"));
      main.append(
        numberField(
          "剩余 %",
          () => record.hpPercent,
          (value) => {
            record.hpPercent = value;
            markRecordPending(record);
            saveState();
            scheduleCalculate();
          },
          { min: 0, max: 100 }
        )
      );
      main.append(
        numberField(
          "累计伤害",
          () => record.totalDamage,
          (value) => {
            record.totalDamage = value;
            record.totalAuto = false;
            updateRecordContext(record);
            markRecordPending(record);
            saveState();
            scheduleCalculate();
          },
          { min: 0 }
        )
      );
    }

    const context = element("span", "record-context", recordContextText(record));
    context.dataset.id = String(record.id);
    main.append(context);

    const remove = element("button", "delete", "删除");
    remove.type = "button";
    remove.addEventListener("click", () => {
      state.records.splice(index, 1);
      refreshAutoTotals();
      markAllRecordsPending();
      setRecordStatus("");
      renderRecords();
      saveState();
      scheduleCalculate();
    });
    main.append(remove);

    const result = element("div", recordResultClass(record), recordResultText(record));
    result.dataset.id = String(record.id);
    item.append(main, result);
    list.append(item);
  });
}

function updateRecordResults(opponent) {
  const byIndex = new Map(
    opponent.observations.map((result) => [result.index, result])
  );

  state.records.forEach((record, index) => {
    const result = byIndex.get(index);
    const node = document.querySelector(
      `.record-result[data-id="${record.id}"]`
    );
    if (!result) {
      return;
    }
    record.matched = result.matched;
    record.kept = result.kept;
    record.message = result.message;
    if (node) {
      node.className = recordResultClass(record);
      node.textContent = recordResultText(record);
    }
  });

  const box = $("record-warnings");
  box.replaceChildren();
  if (opponent.warnings.length === 0) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.append(element("div", "", "有记录没有对上（范围没有因为这条记录缩小）："));
  const list = document.createElement("ul");
  for (const warning of opponent.warnings) {
    list.append(element("li", "", warning));
  }
  box.append(list);
}

function updateRecordFormFields() {
  const type = $("record-type").value;
  $("record-damage-field").hidden = type !== "damage";
  $("record-percent-field").hidden = type !== "hp_percent";
  $("record-total-field").hidden = type !== "hp_percent";
  if (type === "hp_percent") {
    $("record-total").value = String(cumulativeDamage());
  }
}

function addRecord() {
  const type = $("record-type").value;
  if (type === "damage") {
    const damageRaw = $("record-damage").value.trim();
    const damage = Number(damageRaw);
    if (damageRaw === "" || !Number.isInteger(damage) || damage < 0) {
      setRecordStatus("伤害必须是 0 或更大的整数。", true);
      return;
    }
    if (!state.skill) {
      setRecordStatus("请先选择一个技能。", true);
      return;
    }
    state.records.push({
      id: state.nextId++,
      type: "damage",
      damage,
      hits: state.hits,
      skill: state.skill,
      weather: state.weather || null,
      ourBuffs: { ...state.ourBuffs },
      theirBuffs: { ...state.oppBuffs },
      starfall: state.starfall,
      matched: null,
      kept: null,
      message: null,
    });
    $("record-damage").value = "";
  } else {
    const percentRaw = $("record-percent").value.trim();
    const percent = Number(percentRaw);
    if (percentRaw === "" || !Number.isInteger(percent) || percent < 0 || percent > 100) {
      setRecordStatus("剩余生命百分比必须是 0～100 的整数。", true);
      return;
    }
    const autoTotal = cumulativeDamage();
    const totalRaw = $("record-total").value.trim();
    const total = Number(totalRaw);
    if (totalRaw === "" || !Number.isInteger(total) || total < 0) {
      setRecordStatus("累计伤害必须是 0 或更大的整数。", true);
      return;
    }
    state.records.push({
      id: state.nextId++,
      type: "hp_percent",
      hpPercent: percent,
      totalDamage: total,
      totalAuto: total === autoTotal,
      matched: null,
      kept: null,
      message: null,
    });
    $("record-percent").value = "";
    $("record-total").value = String(cumulativeDamage());
  }

  setRecordStatus("");
  refreshAutoTotals();
  renderRecords();
  saveState();
  scheduleCalculate();
}

/* ---------- 启动 ---------- */

async function loadMeta() {
  const response = await fetch("/api/meta");
  if (!response.ok) {
    throw new Error("读取精灵数据失败，请确认 server.py 还在运行。");
  }
  meta = await response.json();

  // 默认例子：水灵（聪明、魔攻天分 10）用气泡打龙息帕尔。
  state.ourPetIndex = findPetIndex("水灵");
  state.oppPetIndex = findPetIndex("龙息帕尔");
  state.nature = "聪明";
  state.talents.spa = 10;
  state.skill = "气泡";

  // 上次打开页面时的内容优先于默认例子。
  restoreSaved();

  fillPets($("our-pet"), state.ourPetIndex);
  fillPets($("opp-pet"), state.oppPetIndex);
  fillNatures($("our-nature"));
  buildTalentControls();
  buildBuffControls("our");
  buildBuffControls("opp");
  fillSkills("");

  $("hits").value = String(state.hits);
  $("starfall").value = String(state.starfall);
  $("weather").value = state.weather;
  renderRecords();
  updateRecordFormFields();

  $("our-pet").addEventListener("change", () => {
    state.ourPetIndex = Number($("our-pet").value);
    scheduleCalculate();
  });
  $("opp-pet").addEventListener("change", () => {
    state.oppPetIndex = Number($("opp-pet").value);
    scheduleCalculate();
  });
  $("our-nature").addEventListener("change", () => {
    state.nature = $("our-nature").value;
    scheduleCalculate();
  });
  $("skill").addEventListener("change", () => {
    state.skill = $("skill").value;
    updateSkillInfo();
    scheduleCalculate();
  });
  $("skill-filter").addEventListener("input", () => {
    fillSkills($("skill-filter").value);
    scheduleCalculate();
  });
  $("weather").addEventListener("change", () => {
    state.weather = $("weather").value;
    scheduleCalculate();
  });
  $("starfall").addEventListener("change", () => {
    const value = Number($("starfall").value);
    state.starfall = Number.isFinite(value) ? value : 0;
    scheduleCalculate();
  });
  $("hits").addEventListener("change", () => {
    const value = Number($("hits").value);
    if (!Number.isInteger(value) || value < 1 || value > 99) {
      setStatus("连击次数必须是 1～99 的整数。", true);
      $("hits").value = String(state.hits);
      return;
    }
    state.hits = value;
    scheduleCalculate();
  });
  $("record-type").addEventListener("change", updateRecordFormFields);
  $("add-record").addEventListener("click", addRecord);

  calculate();
}

loadMeta().catch((error) => {
  setStatus(error.message, true);
});
