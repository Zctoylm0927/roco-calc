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
      option.textContent = value === 0 ? "0" : String(value);
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
  clearTimeout(calcTimer);
  calcTimer = setTimeout(calculate, 200);
}

function setStatus(text, isError) {
  const status = $("status");
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
    observations: [],
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
    const text = item.min === item.max ? String(item.min) : `${item.min} ～ ${item.max}`;
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

async function loadMeta() {
  const response = await fetch("/api/meta");
  if (!response.ok) {
    throw new Error("读取精灵数据失败，请确认 server.py 还在运行。");
  }
  meta = await response.json();

  state.ourPetIndex = findPetIndex("水灵");
  state.oppPetIndex = findPetIndex("龙息帕尔");
  state.nature = "聪明";
  state.talents.spa = 10;
  state.skill = "气泡";

  fillPets($("our-pet"), state.ourPetIndex);
  fillPets($("opp-pet"), state.oppPetIndex);
  fillNatures($("our-nature"));
  buildTalentControls();
  buildBuffControls("our");
  buildBuffControls("opp");
  fillSkills("");

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

  calculate();
}

loadMeta().catch((error) => {
  setStatus(error.message, true);
});
