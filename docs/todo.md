# 待办事项

## 下一步（伤害计算器核心）

- [ ] 确定伤害计算公式（种族值 → 面板值的换算，属性克制系数、技能威力等）
- [ ] 接入 `data/pets.csv` 与 `data/type_multipliers.csv`，提供精灵查询 + 倍率查询接口

## 后续

- [ ] 技能数据（wiki 的 `Module:Pets/data/Skills`、`Learnsets` 已有结构化数据，可复用同一解析器）
- [ ] 精灵页面详情（进化条件、特性等）按需补充

## 备注

- 属性克制关系已由 `Module:Pets/data/Types` 爬取完成，见 `data/type_relations.csv` 与 `data/type_multipliers.csv`。
- 爬虫均支持 `--cache` 离线重跑；重新拉取最新数据时去掉 `--cache` 即可。
- 数据模块中还有 `Skills`、`Learnsets`、`Config` 等，未来可按需扩展解析。
