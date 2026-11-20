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

const KNOCKOUT_TEXT = {
  certain: "一定击倒",
  possible: "可能击倒",
  impossible: "不能击倒",
};

let meta = null;

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

function fillPets(select) {
  select.replaceChildren();
  meta.pets.forEach((pet, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = petLabel(pet);
    select.append(option);
  });
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
}

function fillTalents(select) {
  select.replaceChildren();
  for (const value of [0, 7, 8, 9, 10]) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = value === 0 ? "0（无加成）" : String(value);
    select.append(option);
  }
}

function fillSkills(select) {
  select.replaceChildren();
  const groups = new Map();
  for (const skill of meta.skills) {
    if (!groups.has(skill.element)) {
      groups.set(skill.element, []);
    }
    groups.get(skill.element).push(skill);
  }
  const elements = [...groups.keys()].sort((a, b) => a.localeCompare(b, "zh-CN"));
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
}

function selectValue(select, value) {
  const option = [...select.options].find((item) => item.value === value);
  if (option) {
    select.value = value;
  }
}

function selectPet(select, name) {
  const index = meta.pets.findIndex((pet) => pet.name === name && !pet.form);
  if (index >= 0) {
    select.value = String(index);
  }
}

async function loadMeta() {
  const response = await fetch("/api/meta");
  if (!response.ok) {
    throw new Error("读取精灵数据失败，请确认 server.py 还在运行。");
  }
  meta = await response.json();

  fillPets($("our-pet"));
  fillPets($("opp-pet"));
  fillNatures($("our-nature"));
  fillTalents($("talent-atk"));
  fillTalents($("talent-spa"));
  fillSkills($("skill"));

  // 默认填成文档里的回归例子，方便打开就能核对。
  selectPet($("our-pet"), "水灵");
  selectPet($("opp-pet"), "龙息帕尔");
  selectValue($("our-nature"), "聪明");
  $("talent-spa").value = "10";
  selectValue($("skill"), "气泡");
}

function rangeText(item) {
  if (item.min === item.max) {
    return String(item.min);
  }
  return `${item.min} ～ ${item.max}`;
}

function render(data) {
  const damage = data.damage;
  const opponent = data.opponent;
  const box = $("result");
  box.hidden = false;
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

  box.append(element("h3", "", "对方六维范围"));
  const table = element("table", "stats");
  const head = document.createElement("tr");
  for (const title of ["属性", "最低 ～ 最高", "可能取值"]) {
    head.append(element("th", "", title));
  }
  table.append(head);
  for (const key of STAT_ORDER) {
    const item = opponent.stats[key];
    const row = document.createElement("tr");
    const values = item.possible_values;
    row.append(
      element("td", "", STAT_NAMES[key]),
      element("td", "value", rangeText(item)),
      element("td", "value", `${values.length} 种`)
    );
    table.append(row);
  }
  box.append(table);

  if (opponent.warnings.length > 0) {
    const warnings = element("div", "warnings");
    warnings.append(element("div", "", "提示"));
    const list = document.createElement("ul");
    for (const text of opponent.warnings) {
      list.append(element("li", "", text));
    }
    warnings.append(list);
    box.append(warnings);
  }
}

async function calculate() {
  const status = $("status");
  const button = $("calc");
  const our = meta.pets[Number($("our-pet").value)];
  const opponent = meta.pets[Number($("opp-pet").value)];

  const talents = {};
  const atk = Number($("talent-atk").value);
  const spa = Number($("talent-spa").value);
  if (atk) {
    talents.atk = atk;
  }
  if (spa) {
    talents.spa = spa;
  }

  const state = {
    our_pet: {
      name: our.name,
      form: our.form || null,
      nature: $("our-nature").value || null,
      talents,
    },
    opponent_pet: {
      name: opponent.name,
      form: opponent.form || null,
    },
    skill: $("skill").value,
    weather: $("weather").value || null,
    observations: [],
  };

  button.disabled = true;
  status.className = "status";
  status.textContent = "计算中…";

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "计算失败。");
    }
    render(data);
    status.textContent = "";
  } catch (error) {
    status.className = "status error";
    status.textContent = error.message || "计算失败，请看 server.py 窗口。";
  } finally {
    button.disabled = false;
  }
}

$("calc").addEventListener("click", calculate);

loadMeta().catch((error) => {
  const status = $("status");
  status.className = "status error";
  status.textContent = error.message;
});
