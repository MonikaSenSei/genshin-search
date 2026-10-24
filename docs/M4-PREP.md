# M4 准备（2026-10-25 更新：站点已上线 Netlify）

**线上地址：https://genshin-text-search.netlify.app**（已实测：首页 200、数据容器字节一致、「法涅斯」检索 333 篇/37 强/296 弱，与 CLI 完全一致）。

## 部署与更新管线（当前形态）
- GitHub 仓库：`github.com/MonikaSenSei/genshin-search`（main；代码+站点产物+数据容器；GDS 大源数据 .gitignore 不进仓库）。
- Netlify：项目 `genshin-text-search`（site id 32949321-147e-4179-9382-77c794fe10af，Free 团队 monikasensei，GitHub OAuth 已关联账户）。
- 数据更新一条命令：`python3 scripts/redeploy_netlify.py`（内容哈希增量上传，无变化的文件 0 字节流量）。顺序：social_fetch update → export_static.py → redeploy_netlify.py。
- Netlify PAT 在仓库根 `.netlify_token`（已 gitignore），名为 deploy-cli，**2026-11-01 过期**；续期：app.netlify.com/user/applications#personal-access-tokens 建新 token 覆盖该文件。
- 可选升级（一次性）：Netlify 控制台把仓库直接挂到项目做"推即部署"（控制台 UI 的 Import from Git 流程；本次 API 挂仓在 Netlify 新版上不开放，未做成，不影响现管线）。

## 下次开干：观测枢接入（用户已定向，2026-10-25）
跳转原文 + 书名接回的源改为**观测枢 Wiki**（米游社原神版块→观测·Wiki，https://baike.mihoyo.com/ys/obc/ ，官方托管+玩家协作，国内直连实测 200）。已验证：搜「野猪公主」有词条，URL 形态 `baike.mihoyo.com/ys/obc/content/<数字id>/detail`（注意是数字 ID，非书名 slug）。步骤：
1. 找它的搜索/分类数据接口（页面是 SPA，HTML 全是壳；search 接口和书籍分类目录接口待逆向）。
2. 拉全书籍词条目录 → 按书名（含分卷）join 我们的 Book* 正文，替换/扩大 index/book_titles.db（现 196/1259，BWiki 封顶已确认）。词条名即游戏内书名，预期覆盖率远超 BWiki 方案。
3. 同法评估物品+任务词条覆盖率，决定「跳转原文」范围（原 B 选项的 6-7 成天花板基于 BWiki，需重测）。
4. 导出加可选 URL 列 → 前端只对已校验 URL 渲染按钮（技术形态不变）→ 每日维护顺带 HEAD 重验。
不可由此解决的：米游社社媒正文（既有 cron 管线）、出处未定 10%（游戏数据本身缺）。

## 上线前遗留
1. 米游社正文续抓：139/约1435（每日 9:30 cron 自愈）；补齐后跑一次数据更新命令。

## M4.5 出处回填结果（保留）
1. M4.5 出处回填：完成。scripts/resolve_qe.py（338MB Talk 树 8 秒扫完）→ index/qe_src.db（260,524 id，其中 247,415 带说话人）→ build_index.py 消费后重建索引。出处未定 269,014 → 24,665（91% 回填），带说话人文本 81k → 309k；总篇数与文本集合与旧库完全一致（零差异），检索语义不变。实测样例：「望舒须筑阶」「踏鞴物语·终幕」等真实任务名+说话人已进 web 端展示（浏览器实测通过）。
   - join 链：Talk/<kind>/<id>.json 文件名即 join key：Quest 文件名=QuestExcelConfigData.subId → mainId → MainQuestExcelConfigData.titleTextMapHash（Quest 表本身无标题字段）；Npc 文件名=configId→nameTextMapHash；说话人=TALK_ROLE_* 引用。
   - 书名：官方表已死（见上），社区路线已做——scripts/book_titles.py 用 BWiki {{书籍}} 模板页正文做归一化包含匹配，196/1259 本接上真实书名（含卷数），已进索引（「书籍:《召唤王》」实测通过）；URL 一并存 index/book_titles.db 供"跳转原文"用。覆盖率封顶=BWiki 只转录了 118 个书页（精确引文检索确认其余书文不在 BWiki 任何页面；Huiji 有 Cloudflare 硬墙；DocumentExcelConfigData 1,862 标题是拾取文档线，与 Book* 正文不重叠；正文内嵌「——标题——」行与 Document 标题碰撞 0 命中）。未接名的保持 书籍:BookNNN。
2. 社媒：mys 增量两个 bug 已修——(a) 已知最新前缀导致早停（改为连续10个全已知页才停），(b) 正文风控(1034)时空烧退避（连续5条正文失败即熔断，未成功不标记已知，次日 cron 自动续抓）。当前 mys 已入库 139/约1435，正文 API 处于风控冷却，明日 9:30 cron 起自动补齐（跨日渐进）。
3. 下一步：请用户定托管（建议 Cloudflare Pages）并注册账号 → 部署上线（用户已说"不急"，避免反复改托管）。

## 下次启动待问用户（已两次明确暂缓，勿主动开工）
A. "跳转原文"按钮的目标源：能否接受书籍/物品/任务跳 BWiki 社区页（官方无对应网页可跳；社媒本就有官方链接）。
B. 范围：只做"书籍+社媒"（现成零风险：书籍 URL 已在 index/book_titles.db）vs 再做"物品+任务"页批量 join+校验（覆盖率约 6-7 成，错链风险用"建库时 HEAD 校验、验不过不给按钮"兜底）。
技术形态已定：导出加可选 URL 列（+几百 KB），前端仅对已校验 URL 渲染按钮，每日维护顺带重验。
书名结果：196/1259 已接真实书名并入索引（见上），未接名保持 书籍:BookNNN。
本地预览实例当前仍在跑：http://localhost:8405/（要停说一声）。

## 已完成
- 导出器：scripts/export_static.py（genshin.db + social.db + 别名表 → web/data/）
  - 二进制容器：JSON 头（字符串表）+ u32 UTF-16 偏移 + 全文 blob（\u0000 分隔）+ u8/u16 列
  - 双格式：.bin.zst（首选，浏览器 DecompressionStream('zstd')）+ .bin.gz（兜底）
  - 体量：genshin 16.2 MB（386,016 篇 / blob 32.8 MB）、social 2.1 MB（4,569 条）、meta.json 3.7 KB（25 词条别名表）
- 前端：web/index.html + app.js + style.css（零依赖零构建）
  - 检索引擎：全文 blob 上 indexOf + 换行容忍正则（[\s]* 间隙；两者取并集）。刻意比 FTS/CLI 更严：同句标点间隙会造出词形边界事故（实测别名层 3/3 条标点间隙命中全是误报，如「当天，父亲」≈ 天父；0 条真实命中依赖标点容忍），换行间隙保留（书文换行是真实场景）。
  - 两档降噪完整复刻 query.py：IDF=log2(N/(df+1))，强相关=字面/≥2别名互证/单一df≤5；弱相关展示15条并列总数
  - 展示：语料类型、出处、说话人、在场名单、命中词链；社媒独立区块带日期与原文链接；别名扩展可开关
- 一致性实测（浏览器 vs DB 直查，同语义无截断对拍）：
  - 法涅斯：333 命中 / 37 强 / 296 弱 —— 与 DB 按相同（换行容忍）语义计算完全一致。DB/CLI 的 FTS 标点容忍语义下为 336/35/301，差值恰为 3 条标点间隙误报（全在弱相关档）；用户实探发现「当天，父亲」撞「天父」后收紧了语义。
  - 坎瑞亚：355 篇 / 381 处 —— 与 DB 完全一致（PLAN 里"330次"是 M1 建索引前的预估，索引实际为 355）
  - 性能：32 词形全展开 244 ms；纯字面 13 ms；首次加载 16 MB（之后走浏览器缓存）
- 本地预览：cd web && python3 -m http.server 8405（当前唯一在跑的实例，报告地址前先 curl 实测）

## 已知差异（已消除）
- ~~CLI 收集上限 500/词、标点容忍与网页不一致~~ → query.py 已同步收紧（2026-10-24）：FTS 仅作候选层，命中逐条经「精确子串 ∪ 仅空白间隙」校验后才计 df/打分/分层；收集上限移除。索引无需重建。实测两端完全一致（法涅斯 37强/296弱、坎瑞亚 355，top1 与得分同值）。
- zstd-19 对中文文本相对 gzip 几乎无增益（16.19→16.17 MB）；保留双格式是为兼容不支持 zstd 的旧浏览器。

## 待做（上线）
0. ~~M4.5 出处回填~~ 已完成（见顶部状态）。剩余 ~10% 如实保留「出处未定」（实测：Talk 树里也确实没有引用方）。
1. 托管二选一：GitHub Pages（代码顺带上 GitHub）或 Cloudflare Pages；均需一次性注册免费账号（用户本人在场）。
2. 数据刷新管线：social_fetch update → export_static.py 重导出 → 部署。上线前手动跑；上线后迁 GitHub Actions。
3. 米游社/B站正文补齐（风控冷却中，9:30 cron 自动重试）后重导出，1,435 条米游社正文与 B站简介进社媒区块。
4. 语义"暗示"档为 v2（vectors.npz 400MB 不进浏览器；接免费推理接口，PLAN 已定）。
