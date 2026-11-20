# 架构说明

## 数据来源

站点：https://wiki.biligame.com/nrc/（BWiki，MediaWiki 1.37.0）

精灵数据并非存在 HTML 里，而是存在站点的 Lua 数据模块中，由页面模板通过 `#invoke` 渲染。
因此爬虫直接通过 MediaWiki API 拉取模块源码，解析 Lua 表字面量，得到结构化数据。

关键模块：

| 模块 | 内容 |
|------|------|
| `Module:Pets/data/Catalog` | 精灵基础数据：编号、名称、种族值、属性、阶段、形态、进化链 ID |
| `Module:Pets/data/Evolutions` | 进化链：主进化线（chain）+ 领主化分支（lord_branches） |
| `Module:Pets/data/Skills` | 技能数据（本步未用，可复用） |
| `Module:Pets/data/Learnsets` | 可学技能（本步未用） |
| `Module:Pets/data/Types` | 属性（后续伤害计算用） |

## 获取方式

```
GET /api.php?action=parse&page=Module:Pets/data/Catalog&prop=wikitext&format=json
```

必须携带浏览器 `User-Agent` 与 `Referer` 请求头，否则被腾讯 EdgeOne 防护拦截（返回 567）。

## 数据流

```
api.php (wikitext)  →  LuaParser（递归下降解析 Lua 表）
                          ├─ Catalog → 精灵基础数据
                          └─ Evolutions → 进化链
                          →  关联（通过 evolution_id）
                          →  data/pets.csv
```

## Lua 表结构

### Catalog（每只精灵一个条目）

```lua
pet_000050 = {
  name = "一窝蜂",
  number = "082",            -- 图鉴编号（形态变体会共享同一编号）
  stats = { atk=32, def=27, hp=87, spa=29, spd=27, spe=26 },
  types = { "虫系", "翼系" },
  stage = 1,                 -- 进化阶段：1 初始 → 2/3 进化 → 4 领主化
  form = "",                 -- 形态（基础形态为空，变体如"首领形态"）
  evolution_id = "evolution_bf682d603e12",
  ...
}
```

### Evolutions（一个 id 可能对应多条分支线）

```lua
evolution_bf682d603e12 = {
  { chain = { {id="pet_000050", stage=1, ...}, {id="pet_000051", stage=2, ...}, {id="pet_000143", stage=3, ...} },
    lord_branches = { {id="pet_000548", stage=4, ...} },   -- 领主化分支
    name = "一窝蜂进化链" },
}
```

- `chain`：主进化线（stage 1→2→3），正常进化。
- `lord_branches`：领主化分支（stage 4），通过道具首领化，**与前身共享图鉴编号**。
- 御三家（如迪莫）有多个领主化分支，即数组里含多个 `{chain, lord_branches}` 元素。

## CSV 输出 schema（data/pets.csv）

| 字段 | 含义 | 示例 |
|------|------|------|
| `number` | 精灵编号 | `082` |
| `name` | 名称（中文） | `一窝蜂` |
| `hp` | 生命种族值 | `87` |
| `atk` | 物攻种族值 | `32` |
| `def` | 物防种族值 | `27` |
| `spa` | 魔攻种族值 | `29` |
| `spd` | 魔防种族值 | `27` |
| `spe` | 速度种族值 | `26` |
| `types` | 属性（多个用 `\|` 分隔） | `虫系\|翼系` |
| `stage` | 进化阶段 | `1` |
| `form` | 形态（基础形态为空） | `首领形态` |
| `evolution_chain` | 进化链（名称序列，`→` 连接） | `一窝蜂→黄蜂后→花魁蜂后→女王蜂(首领形态)` |

> 进化链用名称而非编号，是因为领主化形态与前身共享编号，编号序列会出现 `084→084` 的歧义。

## 进化链语义（重要）

进化链只写到**该精灵自身为止**，分叉点之后的形态不展开：

- 迪莫 → `迪莫`（起点，不向后展开）
- 圣光迪莫 → `迪莫→圣光迪莫(首领形态)`
- 女王蜂 → `一窝蜂→黄蜂后→花魁蜂后→女王蜂(首领形态)`

规则：

1. 对每条分支线，某成员的进化链 = 该分支线从起点到它自身（含）的成员序列。
2. 分叉点（如迪莫有 4 个领主化分支）之后的形态各自独立成线，不会拼成一串。
3. `form` 非空的成员以 `name(form)` 形式显示（如 `女王蜂(首领形态)`）。

## 种族值字段映射（已与渲染页交叉验证）

| 字段 | 中文 | 渲染页 rune |
|------|------|-------------|
| `hp` | 生命 | HP |
| `atk` | 物攻 | ATK |
| `def` | 物防 | DEF |
| `spa` | 魔攻 | MATK |
| `spd` | 魔防 | MDEF |
| `spe` | 速度 | SPD |

## 属性克制数据（第二步）

数据来源：`Module:Pets/data/Types`（游戏实际数据，权威）。

模块结构（防御方视角）：

```lua
{ ["光系"] = { weak={{multiplier=2,type="草系"},...}, resist={{multiplier=0.5,type="恶系"},...} },
  ["光系|地系"] = { weak={{multiplier=3,type="草系"},...}, resist={{multiplier=0.5,type="普通系"},...} } }
```

- `weak`：该属性组合「被克制」——被 `type` 攻击时伤害 ×`multiplier`。
- `resist`：该属性组合「被抵抗」——被 `type` 攻击时伤害 ×`multiplier`。

共 18 个单属性 + 102 个双属性组合，倍率 4 档：

| 情形 | 倍率 |
|------|------|
| 单克制（攻击属性克制一个防御属性） | ×2 |
| 双克制（攻击属性克制两个防御属性） | ×3 |
| 单抵抗 | ×0.5 |
| 双抵抗 | ×0.25 |
| 无关系 | ×1（不显式存储） |

> 注意：双克制是 ×3 而非乘算的 ×4，与部分第三方攻略（写 ×4）不一致，以 wiki 数据为准。

### 输出文件

**`data/type_relations.csv`**（单属性二元组，113 行）

| 字段 | 含义 |
|------|------|
| `attack` | 攻击方属性 |
| `defend` | 被攻击方属性 |
| `relation` | `克制`（×2）或 `抵抗`（×0.5） |

**`data/type_multipliers.csv`**（完整倍率表，1023 行，含双属性组合）

| 字段 | 含义 |
|------|------|
| `defend` | 防御方属性组合（如 `光系` 或 `光系\|地系`） |
| `attack` | 攻击方属性 |
| `multiplier` | 倍率（0.25 / 0.5 / 2 / 3） |

伤害计算器查表：给定攻击属性 a 与防御属性组合 d，在 `type_multipliers.csv` 查 `(defend=d, attack=a)`，命中则取 `multiplier`，否则 ×1。

## 与第三方攻略的交叉验证

最初按需求爬取 ali213 攻略页，与 wiki 数据对比发现：

- 抵抗关系：63 组完全一致。
- 克制关系：攻略 49 组，wiki 50 组，唯一差异是「草系→光系」——攻略草系条目漏写，wiki 确认草克制光。

故最终改用 wiki `Types` 模块为权威数据源。
