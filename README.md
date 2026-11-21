# 洛克王国世界 · 6 对 6 伤害与范围计算器

一个本地运行的网页工具，用于洛克王国世界 60 级 PVP 的伤害计算和对方状态推断。

我方精灵的性格、天分、面板和生命是已知的；对方只输入精灵种类，工具会枚举所有可能的性格和天分组合，再根据战斗记录逐步缩小范围。

## 现在能做什么

- 双方各 6 个位置，点击位置切换当前出战。
- 我方每只精灵最多配置 4 个技能，技能下拉只显示它能学的攻击技能。
- 显示我方技能对对方的伤害范围、对方剩余生命百分比范围和能否击倒。
- 显示对方技能对我方的伤害范围、我方剩余具体生命和能否击倒。
- 对方每只精灵独立维护候选范围：默认 46,320 种（30 种性格 × 1,544 种天分配置）。
- 对局记录按回合保存双方行动、实际先手、是否应对、伤害/生命变化、天气、增减益、印记、状态和回合结束快照；可以添加、删除回合，并导出/导入 JSON。
- 对局记录会持续更新对方精灵的性格/天分范围和已见技能；上方 6v6 对位仍可自由选择。
- 当前出战双方显示速度，并按“先比先手值，再比速度”给出谁先行动的判断。
- 显示精灵头像和攻击技能图标；缺图时显示名字首字占位。
- 页面状态保存在浏览器本地，刷新后自动恢复。
- 当前“当前出战”伤害表仍按上方手动配置计算；下一步会改成使用对局记录推断出的范围。

当前有 **197 个自动测试**，全部通过。

## 最快上手

### 1. 准备环境

需要 Python 3.9 或更新版本。项目**只使用 Python 标准库**，不需要 `pip install` 任何东西。

Windows 上如果 `python` 命令不可用，可以改用 `py`。中文输出乱码时，在命令前加 `PYTHONIOENCODING=utf-8`。

### 2. 克隆并启动网页

```bash
git clone https://github.com/zusuyu/roco-calc.git
cd roco-calc
python server.py
```

浏览器打开：

```text
http://127.0.0.1:8000
```

默认页面应该能看到：我方水灵对龙息帕尔，气泡伤害 140～210，对方剩余生命 46.1%～68.4%。这说明数据、公式和网页都正常。

服务默认只监听本机。如果 8000 端口被占用：

```bash
python server.py --port 8001
```

### 3. 第一次克隆后补图片

仓库里**不包含游戏图片**，只包含图片名单 `data/assets.json`。直接启动网页时，头像和技能图标会显示成名字首字占位，这是正常的。

运行一次下载脚本：

```bash
python download_assets.py --dry-run
python download_assets.py
```

`--dry-run` 只统计，不联网；正式下载会一张一张地进行，默认间隔 0.6 秒，已存在的图片会跳过。下载完成后刷新网页即可看到图片。

图片保存在：

```text
web/assets/pets/     精灵头像
web/assets/skills/   攻击技能图标
```

这两个目录已被 `.gitignore` 忽略，不会上传到 GitHub。图片来自游戏/wiki，只保存在本机。

### 4. 跑测试

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

应看到 `Ran 197 tests` 和 `OK`。

## 常用命令

### 网页

```bash
python server.py
```

### 单只精灵伤害计算

```bash
PYTHONIOENCODING=utf-8 python calc.py \
  --attacker 水灵 --attacker-nature 聪明 \
  --attacker-talents "魔攻=10" \
  --defender 龙息帕尔 --skill 气泡
```

### 单只精灵范围推断

```bash
PYTHONIOENCODING=utf-8 python analyze.py \
  --our 水灵 --nature 聪明 --talent 魔攻=10 \
  --opponent 龙息帕尔 --skill 气泡 \
  --weather 雨天 --observe 341 --observe hp:50:195
```

应看到 `可能组合：4,416 / 46,320`、`可能性格：12 种`。

### 6 对 6 队伍推断演示

```bash
PYTHONIOENCODING=utf-8 python team_demo.py
```

### 完整对局日志演示

```bash
PYTHONIOENCODING=utf-8 python battle_demo.py
```

应看到对方龙息帕尔剩 `366 / 46320` 种、6 种性格，生命 `194～197`、显示 `50%`；第二只奇丽花仍是 `46320 / 46320` 种。示例文件在 `data/battle_example.json`，也可以用 `python battle_demo.py 文件路径` 分析自己的对局。

### 网页里录入一回合

1. 在上方配置双方首发、我方性格/天分/技能、对方精灵和怀疑技能。
2. 在“对局记录 → 添加一回合”里选择双方行动（技能/聚能/切换/空）、谁先行动、是否应对。
3. 填本回合的伤害和打完后的生命；有其他回血/掉血就点“添加生命变化”。
4. 展开“回合结束状态”，只改有变化的全员生命/能量、增减益、状态、印记、天气和魔力值。
5. 点“添加本回合”。对方精灵的性格/天分范围和已见技能会更新。
6. “导出对局/导入对局”可以保存和恢复整场记录。

第一次添加回合后，初始队伍会锁定；要改队伍请先点“清空对局”。

### 重新抓取数据

`data/*.csv` 已经提交在仓库里，正常使用不需要重新抓。要更新数据时：

```bash
python crawl_pets.py
python crawl_type_chart.py
python crawl_skills.py
python crawl_natures.py
python crawl_learnsets.py
```

这些脚本会访问 BWiki。抓取脚本支持 `--cache`，可以复用本地 `.cache/` 里的 Lua 数据，不联网重跑。不要并发猛刷网站。

## 项目结构

| 路径 | 作用 |
|------|------|
| `crawl_pets.py` | 抓精灵基础数据和进化链 |
| `crawl_type_chart.py` | 抓属性克制/抵抗关系 |
| `crawl_skills.py` | 抓技能表 |
| `crawl_natures.py` | 抓性格表 |
| `crawl_learnsets.py` | 抓每只精灵的可学习技能 |
| `download_assets.py` | 限速下载精灵头像和技能图标，生成图片名单 |
| `data/*.csv` | 已生成并提交的游戏数据 |
| `data/assets.json` | 精灵/技能到本地图片的对应关系 |
| `roco_calc.py` | 核心库：面板值、属性倍率、伤害公式 |
| `roco_analysis.py` | 单只精灵的范围推断 |
| `roco_team.py` | 6 对 6 队伍推断、记录重放 |
| `roco_skill_rules.py` | 从技能描述读取先手、应对和防御减伤 |
| `roco_battle.py` | 完整对局日志校验、重放和范围推断 |
| `calc.py` | 单只精灵伤害命令行 |
| `analyze.py` | 单只精灵范围推断命令行 |
| `team_demo.py` | 6 对 6 固定例子演示 |
| `battle_demo.py` | 完整对局日志演示 |
| `data/battle_example.json` | 完整对局日志示例 |
| `server.py` | 本地网页服务和 JSON 接口 |
| `web/` | 网页 HTML、CSS、JavaScript |
| `tests/` | 自动测试（含 `test_roco_battle.py`） |
| `docs/` | 架构、进度、设计、待办和历史记录 |
| `DEVLOG.md` | 每一步做了什么、为什么、当前状态 |

## 数据流程

```text
BWiki Lua 数据模块
        │
        │ crawl_*.py
        ▼
data/*.csv
        │
        │ roco_calc.py
        ▼
面板值 / 属性倍率 / 伤害公式
        │
        │ roco_analysis.py / roco_team.py
        ▼
对方性格、天分、生命范围
        │
        │ server.py
        ▼
web/ 网页
```

图片是另一条线：

```text
BWiki 图片
    │ download_assets.py
    ▼
web/assets/ + data/assets.json
    │ /api/meta 提供路径，/assets/... 提供文件
    ▼
网页头像和技能图标
```

## 文档怎么读

建议按这个顺序：

1. `docs/progress.md`：当前已经做到哪一步，最适合先看。
2. `docs/architecture.md`：数据来源、面板公式、伤害公式、范围推断和接口细节。
3. `docs/frontend-design.md`：页面结构、交互和接口设计。
4. `docs/todo.md`：还没做的功能和已知缺口。
5. `DEVLOG.md`：按时间顺序的开发记录，包含每一步的验证结果。

注意：

- `instruction-20261121.md` 是最早的任务说明，只是历史材料，不代表当前状态。
- `docs/sessions/2026-11-21.md` 是早期阶段总结，部分内容已经过时。
- `docs/frontend-design.md` 的 1～7 节描述旧的单只精灵页面；现在的 6 对 6 页面和后续功能看第 8～10 节。

## 当前限制

- 特性、道具、场地、护盾和其他印记尚未接入。
- 目前只有雨天接入伤害计算；其他天气只显示文本。
- 特殊威力规则技能（如魔能爆、怨力打击）需要手动指定威力。
- 换人顺序和换人后的先手判断尚未实现。
- 不含成长星级/PVE 数值，默认 60 级 PVP。
- 目前是手动录入对局信息，还没有从游戏客户端自动读取。
- 伤害公式和取整以 tzrain 计算器及游戏内实测为准，和其他计算器可能有 ±1 差异。

## 协作约定

- 提交前先跑测试：`PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v`。
- 每个可验证的小步骤，在 `DEVLOG.md` 末尾追加一条中文记录，写清“做了什么 / 为什么 / 当前状态”。
- 提交信息使用“前缀 + 中文描述”，前缀用 `feat`、`fix`、`docs`、`chore`，例如：
  `feat: 增加速度与先手判断`
- 新增数据或重新抓取数据时，请说明来源和生成命令。
- 不要把 `web/assets/pets/` 和 `web/assets/skills/` 里的图片提交到 Git。
- 大改动建议先开 issue 或分支讨论，避免直接改坏 `master`。

## 数据来源与参考

- 游戏数据：<https://wiki.biligame.com/nrc/> 的 Lua 数据模块。
- 公式和取整参考：<https://rocopvp.tzrain.wiki/battle>。
- 属性克制关系已和 tzrain 内置 18×18 表逐条比对。
- 部分伤害和天气规则用游戏内实测校准，具体记录见 `docs/architecture.md` 和 `DEVLOG.md`。

本项目是个人研究和计算工具，不是游戏官方项目。
