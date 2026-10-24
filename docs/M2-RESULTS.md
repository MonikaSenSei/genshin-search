# M2 结果（2026-10-23 完成）

## 交付物
- 索引 v2：index/genshin.db（386,016 篇，与 M1 同量同序，新增 speaker/在场 两列）
- 语义向量库：index/vectors.npz（386k 文档 × 512 维 float16，398MB；bge-small-zh-v1.5 本地 ONNX 推理，零成本，301 篇/秒，全程约 21 分钟）
- 查询 v2：scripts/query.py（说话人展示、别名语境降噪两档分层、--semantic 语义档）
- 向量构建：scripts/build_vectors.py、共享编码器 scripts/embed.py（须用 .venv/bin/python）
- 别名提名器：scripts/alias_candidates.py → aliases/candidates_<词条>.md/.json（待人工审，不自动入库）
- 提名示例：aliases/candidates_法涅斯.md（28 条通过筛选，含"维系者"、《列王与宗室史》等真实词形）

## 1. 逐句说话人归因 ✓
- 路径：DialogExcelConfigData.talkRole → PLAYER=旅行者；NPC= id→NpcExcelConfigData.nameTextMapHash→**TextMap_MediumCHS.json**（短标签 TextMap，24.2 万条）。
- 覆盖：203,908 对白行中 201,503 行解析出说话人（98.8%）；索引内 77,538 篇带说话人、全部带"在场"名单（按对话图连通分量聚合）。
- 验证：坎瑞亚抽样——戴因斯雷布/凯亚/纳西妲各归其句，在场名单与剧情一致；NPC 1005=派蒙。
- 对 M1 记述的修正：对话行自带的 talkRoleNameTextMapHash 在本 dump 中是逐行随机的废值（203,908 个唯一值、0 个可解析），不可用；M1 说"多指向角色表"不准确，真实路径在 NpcExcelConfigData+TextMap_Medium。名称类短串（NPC 名、书名标签）只存在于 TextMap_Medium，主 TextMap 没有。

## 2. 别名语境降噪 ✓
- 机制：每个别名按全库 df 计 IDF；文档得分=命中的不同别名 IDF 之和；分档——强相关=字面命中 / ≥2 个不同别名互证 / 单一近唯一别名（df≤5）；弱相关（仅单一常用别名）默认只展示 15 条并列 noise-suspect。输出附各别名 df。
- 验收（法涅斯，32 别名）：M1 无差别 204 篇 → 现强相关 35 篇 / 弱相关 301 篇。M1 关键文献（Book1119 献祭诗、Relic15043 残碑、Book433、Book333《日月前事》）全部居强相关榜首（多别名互证，score 66→33）。
- 弱相关档如实暴露词形冲突："原初之主"在游戏内同时指龙王尼伯龙根，单别名命中被正确压到弱相关。

## 3. 语义检索（暗示） ✓（按短语使用）
- 全语料嵌入（含出处未定的 QE 对白、书籍、字幕），存 rowid 对齐；查询侧 numpy 暴力余弦（61GB 内存下即时）。
- 冒烟：同题 0.643 > 代称暗示 0.308 > 无关 0.171（排序正确）。
- 暗示召回实例："把真实的天空藏起来的虚假帷幕"（无"虚假之天"字面）→ 六条全部命中"虚假之天"论述；"法涅斯+别名锚定" → 召回别名词面未命中的 Relic15043_4、Book434。
- 边界（如实）：单词罕见专名做语义查询会退化为字面相似（法涅斯→法里斯/伊涅芙等音形近名）；故 --semantic 自动用别名表锚定查询短语。语义结果独立成档，不与字面/别名混排。语义检索请描述场景而非只丢名字。

## 4. 别名自动提名 ✓（候选报告）
- 共现统计：以现有别名命中集为种子，抽 2-6 字 CJK n-gram，筛：全库 df≤60、种子集内 precision≥0.5、去已有词形与首尾虚词、只保留极大词串。
- 法涅斯：336 种子篇 → 1,646 候选 → 28 提名（真实词形已浮出）；滑窗碎片是已知噪声，报告带统计与例句供人工裁决。
- 与向量通道的分工：提名器负责"词形发现"，语义档负责"无词形检索"，两层互补。

## 命令
- 建索引：python3 scripts/build_index.py（约 5 分钟）
- 建向量：.venv/bin/python scripts/build_vectors.py（约 21 分钟；.venv 含 numpy/onnxruntime/tokenizers，模型在 models/，从 hf-mirror 下载的 bge-small-zh ONNX）
- 查询：python3 scripts/query.py 关键词 [--limit N] [--json] [--no-alias]；.venv/bin/python ... --semantic 开语义档
- 提名：python3 scripts/alias_candidates.py 词条（需词条已在别名表）

## 遗留（M3 输入）
- 提名报告尚无人工审词流程（v1 人肉看报告即可，后续再谈 UI）。
- 语义阈值未调参，只有排序保证；上线 v2 网页壳时若走浏览器端推理需换 transformers.js 同模型导出。
