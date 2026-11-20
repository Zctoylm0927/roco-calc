"use strict";

const STORAGE_KEY = "roco-calc-team-v1";
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
const BUFF_MIN = -6;
const BUFF_MAX = 6;
const KNOCKOUT_TEXT = {
  certain: "一定击倒",
  possible: "可能击倒",
  impossible: "打不倒",
};
const NUMBER_FORMAT = new Intl.NumberFormat("zh-CN");

let meta = null;
let skillByName = new Map();
let petOptions = [];
let state = null;
let calcTimer = null;
let requestId = 0;

function $(id) {
  return document.getElementById(id);
}

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

function petLabel(pet) {
  return pet.form ? `${pet.name}（${pet.form}）` : pet.name;
}

function summaryLabel(data) {
  return data.form ? `${data.pet}（${data.form}）` : data.pet;
}

function numberText(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  return Number.isInteger(value) ? NUMBER_FORMAT.format(value) : String(value);
}

function rangeText(value, suffix = "") {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "number") {
    return `${numberText(value)}${suffix}`;
  }
  if (typeof value !== "object") {
    return `${String(value)}${suffix}`;
  }
  const { min, max } = value;
  if (typeof min !== "number" || typeof max !== "number") {
    return "—";
  }
  if (min === max) {
    return `${numberText(min)}${suffix}`;
  }
  return `${numberText(min)}～${numberText(max)}${suffix}`;
}

function formatBuff(value) {
  if (value > 0) {
    return `+${value}`;
  }
  if (value < 0) {
    return `−${Math.abs(value)}`;
  }
  return "0";
}

function findPetIndex(name) {
  for (let index = 0; index < meta.pets.length; index += 1) {
    const pet = meta.pets[index];
    if (pet.name === name && !pet.form) {
      return index;
    }
  }
  for (let index = 0; index < meta.pets.length; index += 1) {
    if (meta.pets[index].name === name) {
      return index;
    }
  }
  return -1;
}

function learnableSkills(petIndex) {
  return meta.pets[petIndex].skills || [];
}

function filterSkills(petIndex, names) {
  const learnable = new Set(learnableSkills(petIndex));
  return [...new Set(names)].filter((name) => learnable.has(name));
}

function zeroTalents() {
  const result = {};
  for (const key of STAT_ORDER) {
    result[key] = 0;
  }
  return result;
}

function zeroBuffs() {
  const result = {};
  for (const key of BUFF_KEYS) {
    result[key] = 0;
  }
  return result;
}

function countNonzeroTalents(slot) {
  return STAT_ORDER.filter((key) => slot.talents[key] > 0).length;
}

function safeSlotIndex(value) {
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 && number < 6 ? number : 0;
}

function sanitizeBuffs(raw) {
  const result = zeroBuffs();
  if (!raw || typeof raw !== "object") {
    return result;
  }
  for (const key of BUFF_KEYS) {
    const value = Number(raw[key]);
    if (Number.isInteger(value) && value >= BUFF_MIN && value <= BUFF_MAX) {
      result[key] = value;
    }
  }
  return result;
}

function sanitizeTalents(raw) {
  const result = zeroTalents();
  if (raw && typeof raw === "object") {
    for (const key of STAT_ORDER) {
      const value = Number(raw[key]);
      if (TALENT_VALUES.includes(value)) {
        result[key] = value;
      }
    }
  }
  let nonzero = 0;
  for (const key of STAT_ORDER) {
    if (result[key] > 0) {
      nonzero += 1;
      if (nonzero > 3) {
        result[key] = 0;
      }
    }
  }
  return result;
}

function freshOurSlot(petIndex) {
  return {
    petIndex,
    nature: null,
    talents: zeroTalents(),
    currentHp: null,
    buffs: zeroBuffs(),
    skills: [],
  };
}

function freshOppSlot(petIndex) {
  return {
    petIndex,
    buffs: zeroBuffs(),
    skills: [],
  };
}

function getSlot(side, index) {
  return side === "our" ? state.ourTeam[index] : state.oppTeam[index];
}

function setSlot(side, index, slot) {
  if (side === "our") {
    state.ourTeam[index] = slot;
  } else {
    state.oppTeam[index] = slot;
  }
}

function defaultState() {
  const result = {
    weather: "",
    activeOur: 0,
    activeOpp: 0,
    ourTeam: Array(6).fill(null),
    oppTeam: Array(6).fill(null),
  };

  const water = findPetIndex("水灵");
  if (water >= 0) {
    const slot = freshOurSlot(water);
    slot.nature = meta.natures.some((nature) => nature.name === "聪明")
      ? "聪明"
      : null;
    slot.talents.spa = 10;
    slot.currentHp = 306;
    slot.skills = filterSkills(water, ["气泡", "水炮", "天洪", "水弹枪"]);
    result.ourTeam[0] = slot;
  }

  const pal = findPetIndex("龙息帕尔");
  if (pal >= 0) {
    const slot = freshOppSlot(pal);
    slot.skills = filterSkills(pal, ["龙之利爪", "升龙咆哮"]);
    result.oppTeam[0] = slot;
  }

  const qilui = findPetIndex("奇丽花");
  if (qilui >= 0) {
    result.oppTeam[1] = freshOppSlot(qilui);
  }

  return result;
}

function sanitizeTeam(rawTeam, ours) {
  const result = Array(6).fill(null);
  if (!Array.isArray(rawTeam)) {
    return result;
  }

  for (let index = 0; index < 6 && index < rawTeam.length; index += 1) {
    const raw = rawTeam[index];
    if (!raw || typeof raw !== "object") {
      continue;
    }
    const petIndex = Number(raw.petIndex);
    if (
      !Number.isInteger(petIndex) ||
      petIndex < 0 ||
      petIndex >= meta.pets.length
    ) {
      continue;
    }

    const slot = ours ? freshOurSlot(petIndex) : freshOppSlot(petIndex);
    slot.buffs = sanitizeBuffs(raw.buffs);

    let names = Array.isArray(raw.skills) ? raw.skills : [];
    names = names.filter((name) => typeof name === "string");
    slot.skills = filterSkills(petIndex, names);
    if (ours) {
      slot.skills = slot.skills.slice(0, 4);
    }

    if (ours) {
      if (
        typeof raw.nature === "string" &&
        meta.natures.some((nature) => nature.name === raw.nature)
      ) {
        slot.nature = raw.nature;
      }
      slot.talents = sanitizeTalents(raw.talents);

      if (
        raw.currentHp === null ||
        raw.currentHp === undefined ||
        raw.currentHp === ""
      ) {
        slot.currentHp = null;
      } else {
        const hp = Number(raw.currentHp);
        if (Number.isInteger(hp) && hp >= 0) {
          slot.currentHp = hp;
        }
      }
    }

    result[index] = slot;
  }

  return result;
}

function restoreState() {
  let raw = null;
  try {
    const text = localStorage.getItem(STORAGE_KEY);
    if (text) {
      raw = JSON.parse(text);
    }
  } catch (error) {
    raw = null;
  }

  if (!raw || typeof raw !== "object") {
    state = defaultState();
    return;
  }

  state = {
    weather: raw.weather === "雨天" ? "雨天" : "",
    activeOur: safeSlotIndex(raw.activeOur),
    activeOpp: safeSlotIndex(raw.activeOpp),
    ourTeam: sanitizeTeam(raw.ourTeam, true),
    oppTeam: sanitizeTeam(raw.oppTeam, false),
  };
}

function saveState() {
  if (!state) {
    return;
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (error) {
    // 浏览器存储过期或空间不足时，页面仍然可以正常计算。
  }
}

function setStatus(text, isError = false) {
  const node = $("status");
  node.textContent = text || "";
  node.classList.toggle("error", Boolean(isError));
  node.hidden = !text;
}

function slotElementId(side, index) {
  return `slot-${side}-${index}`;
}

function createPetSelect(side, index, slot) {
  const select = document.createElement("select");
  select.className = "pet-select";

  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "— 选择精灵 —";
  select.append(empty);

  const options = document.createDocumentFragment();
  for (const item of petOptions) {
    const option = document.createElement("option");
    option.value = String(item.index);
    option.textContent = item.label;
    options.append(option);
  }
  select.append(options);
  select.value = slot ? String(slot.petIndex) : "";
  select.addEventListener("change", () => {
    changePet(side, index, select.value);
  });
  return select;
}

function changePet(side, index, value) {
  let next = null;
  if (value !== "") {
    const petIndex = Number(value);
    if (
      !Number.isInteger(petIndex) ||
      petIndex < 0 ||
      petIndex >= meta.pets.length
    ) {
      return;
    }
    next =
      side === "our" ? freshOurSlot(petIndex) : freshOppSlot(petIndex);
  }
  setSlot(side, index, next);
  rerenderSlot(side, index, true);
  scheduleCalculate();
}

function field(labelText, control) {
  const wrapper = element("label", "field");
  wrapper.append(element("span", "field-label", labelText), control);
  return wrapper;
}

function buildTalents(slot) {
  const wrapper = element("div", "talents");
  const head = element("div", "field-title");
  head.append(element("span", "", "天分"));
  const count = element("span", "hint", `已选 ${countNonzeroTalents(slot)} / 3`);
  head.append(count);
  wrapper.append(head);

  const grid = element("div", "talent-grid");
  for (const key of STAT_ORDER) {
    const cell = element("label", "talent");
    cell.append(element("span", "talent-name", STAT_NAMES[key]));

    const select = document.createElement("select");
    for (const value of TALENT_VALUES) {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = String(value);
      select.append(option);
    }
    select.value = String(slot.talents[key]);
    select.addEventListener("change", () => {
      const value = Number(select.value);
      const oldValue = slot.talents[key];
      if (
        value > 0 &&
        oldValue === 0 &&
        countNonzeroTalents(slot) >= 3
      ) {
        select.value = String(oldValue);
        setStatus("最多只能有三项天分有加成。", true);
        return;
      }
      slot.talents[key] = value;
      count.textContent = `已选 ${countNonzeroTalents(slot)} / 3`;
      scheduleCalculate();
    });

    cell.append(select);
    grid.append(cell);
  }
  wrapper.append(grid);
  return wrapper;
}

function buildBuffs(values) {
  const wrapper = element("div", "buffs");
  const head = element("div", "field-title");
  head.append(element("span", "", "增减益"));
  head.append(element("span", "hint", "四维每层 10%，速度每层 10 点"));
  wrapper.append(head);

  const grid = element("div", "buff-grid");
  for (const key of BUFF_KEYS) {
    const cell = element("div", "buff-cell");
    cell.append(element("span", "buff-name", STAT_NAMES[key]));

    const controls = element("div", "buff-controls");
    const minus = element("button", "buff-btn", "−");
    minus.type = "button";
    minus.setAttribute("aria-label", `${STAT_NAMES[key]}减少一层`);

    const shown = element("span", "buff-value");
    const plus = element("button", "buff-btn", "＋");
    plus.type = "button";
    plus.setAttribute("aria-label", `${STAT_NAMES[key]}增加一层`);

    const refresh = () => {
      shown.textContent = formatBuff(values[key]);
      minus.disabled = values[key] <= BUFF_MIN;
      plus.disabled = values[key] >= BUFF_MAX;
    };

    minus.addEventListener("click", () => {
      if (values[key] <= BUFF_MIN) {
        return;
      }
      values[key] -= 1;
      refresh();
      scheduleCalculate();
    });
    plus.addEventListener("click", () => {
      if (values[key] >= BUFF_MAX) {
        return;
      }
      values[key] += 1;
      refresh();
      scheduleCalculate();
    });

    refresh();
    controls.append(minus, shown, plus);
    cell.append(controls);
    grid.append(cell);
  }
  wrapper.append(grid);
  return wrapper;
}

function skillLabel(name) {
  const info = skillByName.get(name);
  if (!info) {
    return name;
  }
  const power = info.power === null || info.power === undefined
    ? "?"
    : info.power;
  return `${name}（${info.element} · ${info.damage_class} · 威力 ${power}）`;
}

function buildSkillsSection(side, slot, index) {
  const wrapper = element("div", "skills-block");
  const head = element("div", "field-title");
  head.append(element("span", "", "技能"));
  head.append(
    element(
      "span",
      "hint",
      side === "our" ? `${slot.skills.length} / 4` : `${slot.skills.length} 个`
    )
  );
  wrapper.append(head);

  const list = element("ul", "skill-list");
  if (!slot.skills.length) {
    list.append(element("li", "empty-note", "还没有选择技能。"));
  }
  slot.skills.forEach((name, position) => {
    const item = element("li", "skill-chip");
    item.append(element("span", "skill-chip-label", skillLabel(name)));

    const remove = element("button", "skill-remove", "×");
    remove.type = "button";
    remove.title = `移除 ${name}`;
    remove.setAttribute("aria-label", `移除技能 ${name}`);
    remove.addEventListener("click", () => {
      slot.skills.splice(position, 1);
      rerenderSlot(side, index, true);
      scheduleCalculate();
    });

    item.append(remove);
    list.append(item);
  });
  wrapper.append(list);

  if (side === "our" && slot.skills.length >= 4) {
    wrapper.append(
      element("p", "hint", "我方每只最多 4 个技能，先移除一个才能添加。")
    );
    return wrapper;
  }

  const learnable = learnableSkills(slot.petIndex);
  const remaining = learnable.filter((name) => !slot.skills.includes(name));
  if (!remaining.length) {
    wrapper.append(element("p", "hint", "没有其他可学的攻击技能了。"));
    return wrapper;
  }

  const addRow = element("div", "skill-add");
  const select = document.createElement("select");
  select.className = "skill-select";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "选择可学技能";
  select.append(placeholder);

  const options = document.createDocumentFragment();
  for (const name of remaining) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = skillLabel(name);
    options.append(option);
  }
  select.append(options);

  const button = element("button", "btn btn-small", "添加");
  button.type = "button";
  button.addEventListener("click", () => {
    const name = select.value;
    if (!name || slot.skills.includes(name)) {
      return;
    }
    slot.skills.push(name);
    rerenderSlot(side, index, true);
    scheduleCalculate();
  });

  addRow.append(select, button);
  wrapper.append(addRow);
  return wrapper;
}

function buildOurFields(slot, index) {
  const fragment = document.createDocumentFragment();

  const row = element("div", "field-grid");
  const natureSelect = document.createElement("select");
  const noNature = document.createElement("option");
  noNature.value = "";
  noNature.textContent = "无性格";
  natureSelect.append(noNature);
  for (const nature of meta.natures) {
    const option = document.createElement("option");
    option.value = nature.name;
    option.textContent = `${nature.name}（${nature.up_name}↑ ${nature.down_name}↓）`;
    natureSelect.append(option);
  }
  natureSelect.value = slot.nature || "";
  natureSelect.addEventListener("change", () => {
    slot.nature = natureSelect.value || null;
    scheduleCalculate();
  });
  row.append(field("性格", natureSelect));

  const hpInput = document.createElement("input");
  hpInput.type = "number";
  hpInput.min = "0";
  hpInput.step = "1";
  hpInput.className = "hp-input";
  hpInput.placeholder = "留空 = 满血";
  hpInput.value = slot.currentHp === null ? "" : String(slot.currentHp);
  hpInput.addEventListener("input", () => {
    const raw = hpInput.value.trim();
    if (raw === "") {
      slot.currentHp = null;
      scheduleCalculate();
      return;
    }
    const hp = Number(raw);
    if (!Number.isInteger(hp) || hp < 0) {
      setStatus("当前生命必须是 0 或更大的整数，留空表示满血。", true);
      return;
    }
    slot.currentHp = hp;
    scheduleCalculate();
  });
  row.append(field("当前生命", hpInput));
  fragment.append(row);

  fragment.append(buildTalents(slot));
  fragment.append(buildBuffs(slot.buffs));
  fragment.append(buildSkillsSection("our", slot, index));
  return fragment;
}

function buildOpponentFields(slot, index) {
  const fragment = document.createDocumentFragment();
  fragment.append(buildBuffs(slot.buffs));
  fragment.append(buildSkillsSection("opp", slot, index));
  return fragment;
}

function buildSlotCard(side, index, open) {
  const slot = getSlot(side, index);
  const active =
    side === "our" ? state.activeOur === index : state.activeOpp === index;

  const card = element("article", active ? "slot active" : "slot");
  card.id = slotElementId(side, index);
  card.dataset.side = side;
  card.dataset.index = String(index);

  const head = element("div", "slot-head");
  const title = element("button", "slot-title");
  title.type = "button";
  title.append(element("span", "slot-number", String(index + 1)));
  title.append(
    element(
      "span",
      "slot-name",
      slot ? petLabel(meta.pets[slot.petIndex]) : "空位"
    )
  );
  title.addEventListener("click", () => {
    selectActive(side, index);
  });
  head.append(title);
  head.append(
    element("span", "slot-badge", active ? "当前出战" : "点击出战")
  );
  card.append(head);

  card.append(element("div", "slot-summary", "等待计算…"));

  const details = document.createElement("details");
  details.open = active || Boolean(open);
  details.append(element("summary", "configure-summary", "配置"));

  const body = element("div", "slot-body");
  body.append(createPetSelect(side, index, slot));
  if (slot) {
    body.append(
      side === "our" ? buildOurFields(slot, index) : buildOpponentFields(slot, index)
    );
  } else {
    body.append(element("p", "empty-note", "先选择一只精灵。"));
  }
  details.append(body);
  card.append(details);
  return card;
}

function renderTeams() {
  const ourBox = $("our-team");
  const oppBox = $("opp-team");
  const ourCards = [];
  const oppCards = [];
  for (let index = 0; index < 6; index += 1) {
    ourCards.push(buildSlotCard("our", index, false));
    oppCards.push(buildSlotCard("opp", index, false));
  }
  ourBox.replaceChildren(...ourCards);
  oppBox.replaceChildren(...oppCards);
}

function rerenderSlot(side, index, open) {
  const oldCard = document.getElementById(slotElementId(side, index));
  if (!oldCard) {
    return;
  }
  oldCard.replaceWith(buildSlotCard(side, index, open));
  refreshActiveStyles();
}

function refreshActiveStyles() {
  for (const side of ["our", "opp"]) {
    for (let index = 0; index < 6; index += 1) {
      const card = document.getElementById(slotElementId(side, index));
      if (!card) {
        continue;
      }
      const active =
        side === "our" ? state.activeOur === index : state.activeOpp === index;
      card.classList.toggle("active", active);
      const badge = card.querySelector(".slot-badge");
      if (badge) {
        badge.textContent = active ? "当前出战" : "点击出战";
      }
      if (active) {
        const details = card.querySelector("details");
        if (details) {
          details.open = true;
        }
      }
    }
  }
}

function selectActive(side, index) {
  if (side === "our") {
    state.activeOur = index;
  } else {
    state.activeOpp = index;
  }
  refreshActiveStyles();
  scheduleCalculate();
}

function updateSlotSummaries(data) {
  for (const side of ["our", "opp"]) {
    const list = side === "our" ? data.our_team : data.opponent_team;
    for (let index = 0; index < 6; index += 1) {
      const card = document.getElementById(slotElementId(side, index));
      if (!card) {
        continue;
      }
      const box = card.querySelector(".slot-summary");
      if (!box) {
        continue;
      }
      box.replaceChildren();
      const entry = list[index];
      if (!entry || !entry.configured) {
        box.append(element("span", "empty-note", "未选择精灵"));
        continue;
      }

      if (side === "our") {
        box.append(
          element(
            "div",
            "summary-line summary-strong",
            `生命 ${rangeText(entry.current_hp)} / ${numberText(entry.max_hp)}`
          )
        );
        box.append(
          element(
            "div",
            "summary-line summary-stats",
            STAT_ORDER.map(
              (key) => `${STAT_NAMES[key]} ${numberText(entry.stats[key])}`
            ).join(" · ")
          )
        );
      } else {
        const builds = entry.builds || {};
        box.append(
          element(
            "div",
            "summary-line summary-strong",
            `剩余 ${rangeText(entry.current_hp_percent, "%")} · 生命 ${rangeText(entry.current_hp)}`
          )
        );
        box.append(
          element(
            "div",
            "summary-line",
            `可能 ${numberText(builds.remaining)} / ${numberText(builds.total)} 种 · ${numberText(entry.natures_remaining)} 种性格`
          )
        );
        box.append(
          element(
            "div",
            "summary-line summary-stats",
            STAT_ORDER.map(
              (key) => `${STAT_NAMES[key]} ${rangeText(entry.stats[key])}`
            ).join(" · ")
          )
        );
      }
    }
  }
}

function updateHpHints(data) {
  for (let index = 0; index < 6; index += 1) {
    const card = document.getElementById(slotElementId("our", index));
    if (!card) {
      continue;
    }
    const input = card.querySelector(".hp-input");
    const entry = data.our_team[index];
    if (!input || !entry || !entry.configured) {
      continue;
    }
    input.max = String(entry.max_hp);
    input.placeholder = `留空 = 满血 ${entry.max_hp}`;
  }
}

function buildActiveSide(side, data) {
  const box = element("div", `active-side ${side}`);
  box.append(element("span", "active-tag", side === "our" ? "我方" : "对方"));

  const body = element("div", "active-side-body");
  body.append(element("div", "active-pet", summaryLabel(data)));
  if (side === "our") {
    body.append(
      element(
        "div",
        "active-meta",
        `生命 ${rangeText(data.current_hp)} / ${numberText(data.max_hp)}`
      )
    );
  } else {
    const builds = data.builds || {};
    body.append(
      element(
        "div",
        "active-meta",
        `生命 ${rangeText(data.current_hp)} · 显示 ${rangeText(data.current_hp_percent, "%")}`
      )
    );
    body.append(
      element(
        "div",
        "active-meta",
        `可能 ${numberText(builds.remaining)} / ${numberText(builds.total)} 种`
      )
    );
  }
  box.append(body);
  return box;
}

function buildSkillRow(skill, side) {
  const row = element("div", skill.available ? "skill-row" : "skill-row unavailable");

  const head = element("div", "skill-row-head");
  head.append(element("span", "skill-name-text", skill.skill));
  const power = skill.power === null || skill.power === undefined
    ? "?"
    : skill.power;
  head.append(
    element(
      "span",
      "skill-tag",
      `${skill.element} · ${skill.damage_class} · 威力 ${power}`
    )
  );
  row.append(head);

  if (!skill.available) {
    row.append(element("p", "skill-reason", skill.reason || "无法计算。"));
    return row;
  }

  const metrics = element("div", "skill-metrics");
  metrics.append(element("span", "damage-value", `伤害 ${rangeText(skill.damage)}`));

  let remaining;
  if (side === "our") {
    remaining = `对方剩余 ${rangeText(skill.remaining_hp_percent, "%")}`;
  } else {
    remaining = `我方剩余 ${rangeText(skill.our_remaining_hp)}`;
  }
  metrics.append(element("span", "remain-value", remaining));
  row.append(metrics);

  const knockout = skill.knockout || "impossible";
  row.append(
    element(
      "span",
      `ko-tag ${knockout}`,
      KNOCKOUT_TEXT[knockout] || "无法判断"
    )
  );
  return row;
}

function buildSkillPanel(title, skills, side) {
  const panel = element("section", "skill-panel");
  panel.append(element("h3", "panel-title", title));

  if (!skills || !skills.length) {
    panel.append(element("p", "empty-note", "这个位置还没有技能。"));
    return panel;
  }

  for (const skill of skills) {
    panel.append(buildSkillRow(skill, side));
  }
  return panel;
}

function renderActive(active, data) {
  const head = $("active-head");
  const tables = $("active-tables");
  head.replaceChildren();
  tables.replaceChildren();

  if (!active) {
    head.append(
      element("p", "empty-note", "当前出战位置上还有空位，请在我方和对方各选一个位置。")
    );
    tables.append(element("p", "empty-note", "选定双方位置后，这里会列出技能伤害表。"));
    return;
  }

  const our = data.our_team[active.our_slot];
  const opponent = data.opponent_team[active.opponent_slot];
  head.append(buildActiveSide("our", our));
  head.append(element("span", "vs", "对"));
  head.append(buildActiveSide("opp", opponent));

  tables.append(
    buildSkillPanel("我方技能 → 对方", active.our_skills, "our")
  );
  tables.append(
    buildSkillPanel("对方技能 → 我方", active.opponent_skills, "opp")
  );
}

function renderWarnings(warnings) {
  const box = $("warnings");
  box.replaceChildren();
  if (!warnings || !warnings.length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.append(element("strong", "warning-title", "提示"));
  const list = element("ul", "warning-list");
  for (const text of warnings) {
    list.append(element("li", "", text));
  }
  box.append(list);
}

function renderResponse(data) {
  updateSlotSummaries(data);
  updateHpHints(data);
  renderActive(data.active, data);
  renderWarnings(data.warnings || []);
}

function validateState() {
  for (const side of ["our", "opp"]) {
    const label = side === "our" ? "我方" : "对方";
    for (let index = 0; index < 6; index += 1) {
      const slot = getSlot(side, index);
      if (!slot) {
        continue;
      }
      if (side === "our") {
        if (slot.skills.length > 4) {
          return `${label}第 ${index + 1} 只精灵最多只能有 4 个技能。`;
        }
        if (countNonzeroTalents(slot) > 3) {
          return `${label}第 ${index + 1} 只精灵的天分最多只能有三项有加成。`;
        }
        if (
          slot.currentHp !== null &&
          (!Number.isInteger(slot.currentHp) || slot.currentHp < 0)
        ) {
          return `${label}第 ${index + 1} 只精灵的当前生命必须是 0 或更大的整数。`;
        }
      }
    }
  }
  return null;
}

function slotPayload(side, slot) {
  const pet = meta.pets[slot.petIndex];
  const payload = {
    pet: { name: pet.name, form: pet.form || null },
    buffs: { ...slot.buffs },
    skills: [...slot.skills],
  };

  if (side === "our") {
    payload.nature = slot.nature || null;
    payload.talents = { ...slot.talents };
    payload.current_hp = slot.currentHp;
  }
  return payload;
}

function buildPayload() {
  return {
    level: 60,
    weather: state.weather || null,
    active_our_slot: state.activeOur,
    active_opponent_slot: state.activeOpp,
    our_team: state.ourTeam.map((slot) =>
      slot ? slotPayload("our", slot) : null
    ),
    opponent_team: state.oppTeam.map((slot) =>
      slot ? slotPayload("opp", slot) : null
    ),
    records: [],
  };
}

function friendlyError(error) {
  if (error instanceof TypeError) {
    return "无法连接本地服务，请确认运行 server.py 的窗口还开着。";
  }
  return error && error.message ? error.message : String(error);
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

  const currentRequest = requestId + 1;
  requestId = currentRequest;
  setStatus("计算中…");

  try {
    const response = await fetch("/api/team", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload()),
    });
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (currentRequest !== requestId) {
      return;
    }
    if (!response.ok) {
      const message = data && data.error
        ? data.error
        : `服务返回了 ${response.status}`;
      throw new Error(message);
    }
    if (!data) {
      throw new Error("服务返回的内容不是有效数据。");
    }
    renderResponse(data);
    setStatus("");
  } catch (error) {
    if (currentRequest !== requestId) {
      return;
    }
    setStatus(`计算失败：${friendlyError(error)}`, true);
  }
}

function scheduleCalculate() {
  requestId += 1;
  saveState();
  if (calcTimer) {
    clearTimeout(calcTimer);
  }
  calcTimer = setTimeout(() => {
    calcTimer = null;
    calculate();
  }, 180);
}

async function init() {
  setStatus("正在读取精灵资料…");
  try {
    const response = await fetch("/api/meta");
    if (!response.ok) {
      throw new Error(`读取精灵资料失败（${response.status}）`);
    }
    meta = await response.json();
    skillByName = new Map(meta.skills.map((skill) => [skill.name, skill]));
    petOptions = meta.pets
      .map((pet, index) => ({ index, label: petLabel(pet) }))
      .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));

    restoreState();
    $("weather").value = state.weather;
    $("weather").addEventListener("change", () => {
      state.weather = $("weather").value;
      scheduleCalculate();
    });

    renderTeams();
    refreshActiveStyles();
    saveState();
    setStatus("");
    calculate();
  } catch (error) {
    setStatus(`页面载入失败：${friendlyError(error)}`, true);
  }
}

init();
