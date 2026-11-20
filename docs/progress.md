# 项目进度

> 洛克王国世界（roco）伤害计算器

## 已完成

- [x] **第一步：精灵数据爬取**
  - 数据来源：wiki.biligame.com/nrc 的 Lua 数据模块（`Module:Pets/data/Catalog` + `Module:Pets/data/Evolutions`）
  - 共爬取 **621 只精灵**（含形态变体），**466 个唯一编号**，**273 条进化链**
  - 输出：`data/pets.csv`
  - 脚本：`crawl_pets.py`

- [x] **第二步：属性克制/抵抗关系表**
  - 数据来源：wiki 的 `Module:Pets/data/Types`
  - 单属性克制 50 组 + 抵抗 63 组；双属性组合倍率另计
  - 输出：`data/type_relations.csv`、`data/type_multipliers.csv`
  - 脚本：`crawl_type_chart.py`

- [x] **第三步：技能与性格数据**
  - 数据来源：`Module:Pets/data/Skills`、`Module:Natures/data`
  - 技能 **825 个**（其中攻击技能 **358 个**）；性格 **30 种**
  - 性格的提升/降低关系已和 `Module:Pets/data/TrainingReference` 逐条核对，30 条全部一致
  - 输出：`data/skills.csv`、`data/natures.csv`
  - 脚本：`crawl_skills.py`、`crawl_natures.py`

- [x] **第四步：面板值计算**
  - 输入：种族值、天分（0–10，最多三项）、性格、等级（默认 60）
  - 输出：生命、物攻、物防、魔攻、魔防、速度六项面板
  - 取整口径以 tzrain 参考计算器为准
  - 核心函数：`roco_calc.calculate_stat()`、`roco_calc.calculate_panel()`、`roco_calc.build_panel()`
  - 校验：岚鸟物攻 128 + 天分 10 → 234；奇丽花物防 121 + 天分 10 → 226

- [x] **第五步：伤害计算**
  - 输入：双方面板、技能、属性克制、本系加成、连击、减伤、攻防等级、最终乘区
  - 输出：有效威力、显示威力、单次伤害、总伤害、占最大生命百分比、是否击倒
  - 核心函数：`roco_calc.calculate_damage()`、`roco_calc.calculate_matchup()`
  - 校验：岚鸟用扇风打奇丽花，显示威力 **356**、伤害 **332**，与公开文章一致

- [x] **第六步：命令行入口**
  - `calc.py`：中文排版输出，支持 `--json`
  - 支持形态、性格、天分、等级、威力覆盖、攻防等级、减伤、连击等参数
  - 错误会给出中文提示，例如同名精灵有多个形态时会列出可选形态

## 进行中

（无）

## 待开始

- [ ] 前端界面（在数据核对无误后再做）
- [ ] 特性、道具、天气、场地、印记等额外效果
- [ ] 威力随规则变化的技能自动计算（目前需要 `--power` 手动指定）
- [ ] 可学技能校验（接入 `Module:Pets/data/Learnsets`）
- [ ] 速度先后、先手、换人等战斗流程
- [ ] 成长星级/PVE 数值
- [ ] 反向计算（给定目标伤害，反推需要多少威力/面板）

## 已确认的决策

- 数据范围：全部抓取（含形态变体），编号允许重复，用 `form` 字段区分。
- 进化链：单表加列，用名称序列（`→` 连接）；只写到该精灵自身为止，`form` 非空显示为 `name(form)`。
- 属性克制数据源：wiki `Types` 模块（更权威，无遗漏），而非第三方攻略。
- 克制叠加规则：单克制 ×2、双克制 ×3（非攻略所说的 ×4）、单抵抗 ×0.5、双抵抗 ×0.25。
- 面板取整口径：以 tzrain 为准；与 rocokingdom 等计算器可能有 ±1 差异。
- 性格默认：不加不减；天分默认：全 0。实际计算时显式传入，避免隐藏假设。
- 等级默认：60 级 PVP。
- 本系加成：×1.25（不是宝可梦的 ×1.5）。
- 没有暴击和随机浮动。
- 双克制是 ×3，不是 ×4。

## 快速验证

跑全部单元测试：

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

应看到 `Ran 48 tests` 和 `OK`。

跑公开文章实例：

```bash
PYTHONIOENCODING=utf-8 python calc.py \
  --attacker 岚鸟 --attacker-form 本来的样子 \
  --defender 奇丽花 --skill 扇风 \
  --attacker-talents "物攻=10" --defender-talents "物防=10" \
  --power 142.5
```

应看到 `显示威力：356` 和 `总伤害：332`。
