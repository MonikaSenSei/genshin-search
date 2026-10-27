# M4 准备（2026-10-25 更新：站点已上线 Netlify）

**线上地址：https://genshin-text-search.netlify.app**（已实测：首页 200、数据容器字节一致、「法涅斯」检索 333 篇/37 强/296 弱，与 CLI 完全一致）。

## 部署与更新管线（当前形态）
- GitHub 仓库：`github.com/MonikaSenSei/genshin-search`（main；代码+站点产物+数据容器；GDS 大源数据 .gitignore 不进仓库）。
- Netlify：项目 `genshin-text-search`（site id 32949321-147e-4179-9382-77c794fe10af，Free 团队 monikasensei，GitHub OAuth 已关联账户）。
- 数据更新一条命令：`python3 scripts/redeploy_netlify.py`（内容哈希增量上传，无变化的文件 0 字节流量）。顺序：social_fetch update → export_static.py → redeploy_netlify.py。
- Netlify PAT 在仓库根 `.netlify_token`（已 gitignore），名为 deploy-cli，**2026-11-01 过期**；续期：app.netlify.com/user/applications#personal-access-tokens 建新 token 覆盖该文件。
- 可选升级（一次性）：Netlify 控制台把仓库直接挂到项目做"推即部署"（控制台 UI 的 Import from Git 流程；本次 API 挂仓在 Netlify 新版上不开放，未做成，不影响现管线）。

## 观测枢接入（M4.6，2026-10-25 完成第一期：书籍）
接口已逆向（scripts/obc_probe.py 头部注释有全部端点；关键参数 app_sn=ys_obc，请求须带 UA+Referer/Origin 否则 403）：
- 频道树 getChannelTree → 「书籍」频道 id=68，共 93 个词条（=站点渲染数，无翻页）。
- 词条详情 entry_page?entry_page_id=<id>：按卷分模块，rich_text 即书籍全文（逐卷完整转录）。
- 列表接口 home/content/list?channel_id=68 的 content_id 与 entry_page_id 同一 ID 体系；URL=content/<id>/detail。
- scripts/obc_books.py：拉 93 词条全文（缓存 data/obc_books_raw.json）→ 归一化精确文本包含 join 本地 BookNNN.txt。
结果：183 本经 OBC 接回（72 个词条），另 42 本原 BWiki 行经书名确认改指 OBC 词条——合计 225/1259 本书带官方 URL；剩余 20 本仅 BWiki 覆盖（保留 BWiki URL）。72 个 URL HEAD 全 200；--verify 模式已接入每日维护 cron（死链标 source='stale'，前端不出按钮）。
「跳转原文」已上线：export_static.py 给 genshin.bin header 加 src_url 平行表（120 个带 URL 的 source 标签），前端仅对非空 URL 渲染按钮。浏览器线上实测「最洁白的獠牙」→ 书籍:野猪公主·卷一 + 跳转按钮 → content/625/detail。
未完成：M4-PREP 第 3 步（物品+任务词条覆盖率评估→决定跳转范围）未做，下次接着做；OBC 书籍频道只有 93 系列，物品/任务频道词条量待测。
## M4.6 第二期：模糊 join + 书名可检索（2026-10-25）
用户报障：搜书名（如「日月前事」）搜不到书本身。根因两层：
1. 结构性：书名不在任何书正文里（标题表 ReadingExcelConfigData 在所有转储中已死），索引只搜正文 → 书名查询永远只能命中提到书名的对白/任务。
2. join 过严：观测枢是社区转录，与 dump 存在单字差异（实测 OBC「日月前事」漏掉「出现在」的「出」字）且在正文前拼了「第N卷」字样；旧 join 要求归一化整篇精确包含，一个字的差异即失配。
修复（已上线）：
- scripts/obc_books.py join_all 改容错匹配：剥掉 OBC 文本的卷首标记后做 6-gram 覆盖率（本地文本被覆盖 ≥0.9）或精确包含；每本书取最高分卷。卷名标签修正：OBC 模块名不带系列名时拼 base·卷名（旧逻辑一律退回系列名，导致「日月前事」这类卷名丢失）。
- 覆盖率：245 → 293 本（新增 48 本接回 + 245 中 192 本细化到卷级标签）；90 个 OBC 词条 URL HEAD 全部 200。dump 里 31 本正文为空/「？？？」占位（其中 Book421/422/420 等 8 本 Book*），OBC 有全文但一期不注入，未接名。
- 书名可检索：build_index.py 给每本已接名的书 emit 一条 corpus_type='book_title' 的「书名卡片」文档（《书名》+ 提示语），source 与正文同标签 → 检索书名命中卡片，卡片带「跳转原文」。前端 app.js：TYPE_LABEL 加「书名条目」；dedup key 加入 source（不同书的同名卡片不互相吞并）。总文档 386,016 → 386,301（+285 张卡片，8 个未接名书无卡片）。
- 书名匹配独立栏（取代上一版正文加权置顶，用户明确要求）：页面顶部新增「书名匹配」区（游戏语料、社媒公告之上），直接扫描 genshin.bin 的 source 标签表（书籍:<title>，含 293 本接回书名；BookNNN 等未接名过滤）——检索词是书名子串即列出《书名》+跳转原文，与正文是否提到查询词无关；按书名排序、按书名去重、无命中即隐藏该区。游戏语料区回退为原 IDF 排序并过滤 book_title 卡片文档（由书名栏代表）。app.js renderTitleSection；index.html 新增 titles-sec。CLI 侧（query.py）仍保留 ×10 书名加权（无独立栏）。顺带修复：语料未加载完点击检索会 JS 报错，现在忽略。
- 实测：本地 CLI query.py 与浏览器端「日月前事」均命中「书籍:白夜国馆藏·日月前事」书名卡片+跳转按钮。书名卡片正文按用户要求精简为纯《书名》（去掉提示语；285 个书名全局唯一，无 dedup 冲突；若未来出现同名书需加不可见唯一后缀）。
- 字面 \n 清洗（用户报「搜索结果出现 \n」）：TextMap 字符串把换行存成两字符转义（实测 8,356 条，多为图鉴/物品描述），build_index.py emit() 统一 replace("\\n","\n")；重建后字面 \n 归零，总数 386,301→386,279（−22 为转义写法造成的重复文本合法合并）。8 条官方测试文本里的字面 /n 属原文如此，保留。
遗留（可选下一步）：搜书名顺带注入正文段落=用户明确不要（改为书名命中置顶，已做）；占位书的 OBC 正文注入（语料分层要标明来源为观测枢转录）；M4.6 第 3 步物品/任务频道评估不变。

scripts/obc_join_dryrun.py：改动 join 前先看增量的固定工具。

## M4.6 第 3 步：物品/任务频道覆盖率评估（2026-10-26，完成）
探针：scripts/obc_channel_counts.py（频道词条量，缓存 data/obc_channel_entries.json）、obc_quest_eval2/3.py（任务 join）、obc_item_eval.py / obc_viewpoint_eval.py（物品层）、obc_quest_verify.py（抽查复核）。
API 补充事实：列表接口返回 data.list[0].list（频道节点内嵌全部词条，无翻页）；搜索接口 wapi/search 返回 data.list，名称含 <em> 高亮标记；词条 URL 的 ID 两种形态并存（旧词条小 ID 如 2247，新投稿 50 万级 ID），均走 content/<id>/detail。
频道量：任务43=2196、NPC&商店20=4752、背包13=4104、成就252=3228、敌人6=834、食物21=646、武器5=504、角色25=276、观景点253=264、活动105=275。
【任务线】索引中带任务出处的 1105 个标题 / 38,198 篇 → 观测枢可接 241 标题 / ~9,970 篇（标题 21.8%、篇数 26.1%）。join 可靠性高（抽查通过）：世界任务独立成条且标题逐字一致；魔神任务只收录部分（「第一章 第四幕「我们终将重逢」」这类组合式标题，抽「」内幕名可 join；第五章等新章节未转录）；事件任务基本没转（活动频道 275 条是活动页不是任务文本）。join 必须按「标题全等 + 「」段抽取」做，禁模糊。
【物品层】语料里物品类文档仅 ~2.3k 篇（占 0.6%）：
- 武器/料理/角色：名称 join 观测枢 88-98%，但 dump 描述文本几乎不进语料（武器 1/287、角色 0/167）——无文档可挂，放弃。
- 观景点（ViewCodex 268 条）：desc 全部在语料（268/268），名称与观景点(253)频道逐字 join 257/268 → 257 篇可挂官方跳转。近全量、零风险。
- 材料/材料图鉴：MaterialExcel 名称 join 2335/10512（但多为杂物）；MaterialCodex desc 352 在语料，但名字段半数解析不出，需二段 join 到 Material 线，仅 ~53-214 直接可接。性价比低。
【结论建议】做：①观景点线 257 篇（全量可接）；②世界任务/部分魔神任务 ~241 标题 9.9k 篇顺带做（exact-title join，验不过不出按钮）。不做：物品通用跳转（文档太少）；材料图鉴二段 join（低产出）。"正文中的物品名→物品页"属新特性（词条内链），不在跳转原文范围。

## M4.7 物品栏（用户新方向，2026-10-26 开工）
用户改需求：物品不做跳走，站内点开看（仿原神背包物品详情）。这绕开了与 dump 的 join——物品词条本身就是独立实体层，观测枢词条即卡片内容。
结果页设计：检索命中物品名 → 顶部「物品匹配」网格栏（图标+名称，仿背包），点卡片开站内详情弹窗（图标+星级+名称+类别+描述/效果+故事+获取方式，底部小链接去观测枢看数值全页）。
用户定的栏目优先级（结果页区块顺序）：书籍(书名匹配) > 角色故事 > 生物志 > 物品栏 > 剧情 > 社媒公告。角色(25,276条)/敌人(6,834条)各单开一栏，下次对话做。
本期范围：物品线全部——武器(5,504)+圣遗物(218,63)+料理(21,646)+背包/材料(13,4104)，去重后 ~5.3k 词条；详情用精简版（纯文本组件；成长数值/推荐角色等结构化表格不进弹窗，靠跳转链接看全页）。
数据管线：scripts/obc_items_fetch.py（entry_page 详情，缓存 data/obc_items_raw/<id>.json 逐条落盘可续传；后台运行中）→ scripts/obc_items_parse.py（组件解析:equipment_base_info/good_desc/material_base_info/rich_base_info/artifact_list_v2/collapse_panel；HTML→纯文本；产出 data/obc_items.json）。圣遗物按套装成条，含五部位名称/描述/故事。
组件结构要点：详情=page.modules[].components[]，data 为 JSON 字符串；富文本是 HTML（<p>/<span class=custom-entry-wrapper> 内嵌词条链接）；食材有同名变体行（奇怪的X/美味X）取主名行。
待做：export_static.py 加 items 容器（name/alias/kind/category/star/icon/desc 摘要/url，全名表+摘要进前端，故事全文可同容器——5k×~1KB 可接受）；app.js 物品匹配栏+详情弹窗；daily 维护顺带死链校验。
实测记录（2026-10-26 本地预览）：物品栏用户验收「非常棒」。抓取实际去重量=2,690（频道列表含重复，5.3k 是未去重数）。
物品抓取完成：去重 2,690 词条全部抓齐（0 失败）；parse 产出 2,648 条（42 条空正文跳过），items.bin 已含全量并上线。

## M4.8 书名匹配网格卡（2026-10-26 完成，已上线）
书名栏从文字列表改为物品栏同款图标网格卡；卡片点击=新标签直开观测枢原文（不开弹窗）。
数据管线：export_static.py export_books() → web/data/books.bin（zst 8KB，285 个接名书名，标题从 book_titles.db 去重；封面 icon 从缓存 data/obc_channel_68.json 按 URL 里的 entry id 反查——列表 API icon 字段即封面，93 词条全部有 icon）。277 本带观测枢封面，8 本仅 BWiki 覆盖的退化为无图文字卡（tag 标 BWiki）。
前端：app.js renderTitleSection 重写为读 books.bin（books.bin 缺失时回退旧 src 标签扫描）；style.css 复用 .item-grid/.item-card，加 .book-card（a 标签去下划线）。书名自带《》的 3 本（召唤王等）导出时预生成 disp 字段防双书名号。
实测（本地 + 线上均通过）：「日月前事」1 本带封面卡→content/3470/detail 图片加载成功；「公主」8 本全带图且 naturalWidth>0；「召唤王」BWiki 文字卡无双书名号；物品栏「狼」7 条正常。
下一对话任务：按用户定的栏目优先级做「角色故事」栏（角色频道 25/276 条）+「生物志」栏（敌人频道 6/834 条），各单开一栏，复用网格卡组件（点击行为待用户定：弹窗或跳转）。
可选顺带：观景点线 257 篇挂跳转（M4.6 第 3 步已验证近全量可接）；世界任务/部分魔神任务 exact-title join ~241 标题。

## M4.9 角色/生物栏 + 富文本标签清洗（2026-10-26 完成，已上线）
用户决定：角色、生物卡片点击都跳转观测枢词条页（同书籍，不开弹窗）。
数据层：export_charlayer() 直接吃 obc_fetch_channel.py 25/6 的列表缓存（无需抓详情页）→ characters.bin（去重 131 角色，全带 icon）/ creatures.bin（417 生物，全带 icon，zst 合计 ~36KB）。match 字段拆装饰变体：【预告】剥离、「死之执政」若娜瓦 拆出「死之执政」「若娜瓦」两段可搜。
前端：index.html 新增 chars-sec/creatures-sec（顺序=书名>角色>生物>物品，按用户定的优先级）；app.js 抽出 renderLinkGrid 共用组件（书/角色/生物三处），renderEntrySection 通用匹配渲染；loadLayer(key) 通用加载。注意：执行官（公子/仆人等）在观测枢属敌人频道 → 命中在生物栏（角色栏没有），符合观测枢自身分类。
富文本清洗（用户报「<color=#00E1FFFF> 出现在结果里」）：build_index.py emit() 剥 <color=>/<size=>/<i>/<center|right|multi>/<image|region/>（实测 7,956 篇含标签；<病历> 这类正文性尖括号词不匹配标签正则、保留）。索引 386,279→385,963（剥离后文本合法合并），旧库备份 index/genshin.db.bak-2026-10-26。
每日维护 cron 已扩：步骤 5=obc_fetch_channel 68 25 6 + items fetch/parse 增量，步骤 6=export_static + redeploy（内容哈希增量，无变化零流量）。
实测（本地+线上）：「纳西妲」角色卡带图→content/5111/detail；「公子」生物栏命中；「丘丘人」14 条；「若娜瓦」带图；「日月」检索结果 color 标签归零、「病历」文本保留。

## M4.9.1 执行官代号别名（2026-10-26，用户报「搜仆人找不到阿蕾奇诺」）
根因两层：卡片栏此前只按原始查询词匹配、不走别名扩展；且别名表登记形态是带引号的「仆人」，用户搜裸词「仆人」查不到条目。
修复：①renderEntrySection 改收 terms（别名扩展后匹配）；②alias_table.json +25 条执行官代号↔真名（带引号与裸词两种形态；全部语料直证后收录：仆人↔阿蕾奇诺、公子↔达达利亚、博士↔多托雷、队长↔卡皮塔诺、丑角↔皮耶罗、公鸡↔普契涅拉、木偶↔桑多涅、少女↔哥伦比娅、冰之女皇；「女士」初版误判「真名不在语料」，用户指正后查证：真名=罗莎琳，语料 51 篇（女士图鉴「亲爱的罗莎琳」直证、葬礼/燃珀剧情线），已补 3 条（「女士」/女士/罗莎琳 双向））。
卡片可见性取决于观测枢是否有词条：阿蕾奇诺/桑多涅/哥伦比娅/达达利亚在角色频道；多托雷在敌人频道；皮耶罗/普契涅拉/卡皮塔诺/冰之女皇无词条（别名只提升语料召回，无卡片，属数据源限制非 bug）。
教训（已入 skill）：别名条目要同时登记「代号」带引号与裸词两种形态；卡片层必须复用别名扩展的 terms。
实测（本地+线上）：搜「仆人」→角色栏出阿蕾奇诺卡片（别名扩展 1 词形）；「博士」→生物栏「博士」「多托雷」两条；「队长」→无卡片（OBC 无词条）但语料召回增加。

## M4.9.2 执行官本名层（用户指正：代号≠真名）
用户指出执行官名字是多层结构：代号→称号名→本名。语料查证后补别名（现共 55 条）：
- 佩露薇利 = 「仆人」阿蕾奇诺的本名（壁炉之家线，17 篇直证：「以『佩露薇利』的身份出战」、克雷薇决斗）→ 双向别名，并入仆人/阿蕾奇诺条目。
- 阿贾克斯 = 「公子」达达利亚的本名（璃月出身，23 篇：英杰谈「阿贾克斯大哥/哥哥」故乡线）→ 双向别名，并入公子/达达利亚条目。
- 库塔尔 = 「少女」哥伦比娅的神名（挪德卡莱月之少女，81 篇）→ 并入少女/哥伦比娅条目（语料直证「少女」哥伦比娅=月神库塔尔）。
- 查证不收录的：克雷薇(79)/莱茵多特(89)/乔瓦尼(15) 均为独立角色（壁炉之家成员/生之执政等），语料无与执行官等同的直证句，不臆断。
顺带发现并修复大括号标记族（用户搜罗莎琳时暴露的 {RUBY#…}）：语料 12,958 篇含 { 标记。{RUBY#[D]词} 注音壳（词在壳内、[D]/[S] 是阅读标志——剥壳留词）、{LINK#id}…{/LINK}、{SPRITE_PRESET#{n}}/{SPRITE_PRESET#n} 图标壳→剥除；保留可读占位符 {NICKNAME}/{M}/{F}/{Q…}/{REALNAME}/{PLAYERAVATAR}。修复后 库塔尔/阿卡西 等被注音壳隔断的词恢复可 substring 检索（{RUBY/{LINK/{SPRITE 计数归零）。索引总数不变 385,963。
教训（已入 skill）：「真名」可能是三层（代号/称号/本名），别名条目应覆盖全部已知层；标记清洗要枚举 { 族不能只查 < 族。


## M4.10 首屏加载幕 + 观景点跳转（2026-10-26 完成，已上线）
加载幕（用户报「语料加载完成前搜索无效，体验差」）：整页遮罩（标题+状态行+字节进度条），按 content-length（本地/Netlify 均返回）显示「下载语料 x.x MB / 11.0 MB」；社媒+游戏语料全部加载解析完才淡出揭幕，之后才启用搜索框/按钮并聚焦——加载中搜索栏 disabled，不再有静默无效检索。加载失败时遮罩不撤，红字「加载失败：…（刷新重试）」。实测本地+线上：加载中 loader=present 且 q.disabled=true，揭幕 ~2s（缓存）；「日月前事」无回归。fetchDecompressed 加 onProgress（读流计字节），main() 重写为揭幕流程。
观景点线（M4.6 第 3 步验证过的方向 1）：scripts/obc_viewpoints.py = 拉观景点频道(253, 264 条, 缓存 data/obc_channel_253.json) → ViewCodex 名称归一化全等 join → desc 文本确认在语料 → 逐 URL HEAD 校验，产出 data/viewpoint_urls.json（desc 全文 → {id,name,url,ok}；重跑时 URL 未变则跳过 HEAD，--内建 verify）。实测 257/268 可接、0 冲突、0 死链。
导出/前端：一条文本可能属多个场景时置冲突不出按钮（实测冲突 0）。genshin.bin header 新增 doc_url 稀疏表（doc 下标→URL；场景图鉴没有独立 source 标签，必须逐文档）；gameCard 跳转优先级 = doc_url > src_url。实测本地+线上：搜「望舒客栈的楼阁」场景图鉴卡带跳转→content/504954/detail。
每日维护 cron 已扩：步骤 4 顺带跑 obc_viewpoints.py（重 join+全量 HEAD，摘要含「观景点 N/N 存活」）。
注意：本次导出文档总数 385,963→385,962（−1），为 M4.9.2 索引重建（03:17）后首次重导出，属剥离标记后文本合法合并，非 bug。浏览器实测坑：本测试浏览器无 DecompressionStream('zstd')（走 .gz 回退），直接探测 .zst 会抛错；检索后立刻查 DOM 可能读到空结果，多等 2-3 秒再断言。
下一对话可做：方向 2=世界/魔神任务 exact-title join（~241 标题、~9.9k 篇）；方向 3=占位书 OBC 正文注入（31 本）。

## M4.11 任务标题跳转（方向 2，2026-10-26 完成，已上线）
scripts/obc_quests.py：任务频道(43) 去重 1098 词条 ↔ 索引 1105 个 任务「title」 标签。join=严格键分层：tier0 全等（归一化全名 / 「」段 / 第N幕尾段），tier1-2 系列回退（索引全名或系列半 = 观测枢 'S·V' 条目的 S，跳系列页）。禁子串回退（曾产生 不速之客→泡泡桔色的不速之客 噪声）；观测枢侧不拆·（系列 token 互相吸出 46 歧义，如 全能美食队·*）；含歧义（命中>1条目）不出按钮。结果：214 标题 / 7,990 任务文档 / 歧义 5 / 0 死链（缓存复用则跳过 HEAD）。
export_static.py：任务标签挂 src_url 三种形态——任务「X」直接/系列继承；mainquest｜X、dailytask｜X、quest｜X 取 ｜ 后标题同规则（+432 篇；item｜/viewcodex｜ 与任务同名属巧合不挂）。src_url 标签总数 277→746。注意：非任务出处的对白提到任务名不挂跳转（正确语义：跳转=该文档属于该任务）。
实测（本地）：「踏鞴物语·终幕」mainquest 卡→content/2394（系列继承）；「三十人团」的招募→7647、「月莲杯」的初战→505553（「」段 join）；提到任务名的普通对白无按钮。
cron 步骤 4 已加 obc_quests.py（join+全量 HEAD）；步骤 6 发布成功后 git add/commit/push（此前 daily 数据提交不会自动进 GitHub，已修）。
阻塞（2026-10-26 04:20）：Netlify 返回 403『Account credit usage exceeded - new deploys are blocked until credits are added』——站点现网正常（仍为 M4.10 版），M4.11 数据已 commit+push 到 GitHub。账号=新 credits 制（nf_team_dev，300 credits/周期，API 无明细端点，usage API 404），消耗元凶已查明=导出字节非确定性（gzip 嵌 mtime）导致每日重发全量重传 ~50MB；已修（mtime=0，双跑 md5 一致）。【用户决定（最终规则）：项目正式完工前一律不发布 Netlify，完工后由用户提醒才发布；在此之前日常只 commit+push GitHub + 本地预览验证，维护 cron 无发布步骤。】
下一对话可做：方向 3=占位书 OBC 正文注入（31 本）。【已做，见 M4.12】

## M4.12 占位书注入 + 地图文本层 + 未接名层重标注（2026-10-27，本地完成，未发布）
用户口径（本轮对话确定）：书籍层以观测枢为准（93 系列书单），观测枢没有的不补；BWiki 独有 8 本保留不删；未接名的 Readable 不得以 BookNNN 示人，改真实名称（优先，含位置）或类别名；开发残留过滤；这一层在结果里整体降权排后。
盘点结论（先于动工实测）：31 个占位文件里只有 14 本是 BookNNN（其余 17 个是武器/圣遗物/风之翼 flavor 文件）；这 14 本正文为空/？？？，CHS/EN/JP 全无文本，且 dump 三条命名路（Reading/772NNN 物件名/Gadget）全部解析不出名字——占位书接不回。真实可注入的是另一组：观测枢书籍频道 join 后仍无对应 dump 正文的卷，且必须是真实世界可读书（验证=717 系书籍场景物件名 GadgetExcel+TextMap，data/book_gadget_names.json 533 个）。
①书籍注入 scripts/obc_book_inject.py：5 卷（古老的考察日志·其之一[原名带'.其之一'照录观测枢]、其之二、残破的笔记、风、勇气和翅膀、林间风·故事拔萃节选）。写 book_titles.db 合成键行 inject:<eid>:<vi>（source='obc'→自动获得书名卡片+跳转）；正文由 build_index 从 data/obc_books_raw.json 注入，corpus_type='book_obc'（标签「书籍（观测枢转录）」，不降权）。白之公主六侏儒各卷(28-43字引用行)自动判为 stub 不注入。
②地图文本层（用户要求的“世界拾取物+位置”）：观测枢 图鉴>地图文本 频道=251，706 词条，每词条=文档名+【区域】+交互文本全文+关联任务链接。scripts/obc_maptext.py：列表缓存 data/obc_channel_251.json、逐条缓存 data/obc_maptext_raw/<id>.json（可续传）、--join=锚点预筛+包含/6-gram 容错匹配→data/maptext_match.json（实测 205/706 命中 dump Readable、歧义 1 剔除）、--verify=全量 HEAD→data/maptext_urls.json（ok 才出跳转）。关键发现：未匹配的 501 条里随机 60 条在索引任何标签下都不存在——这批世界文本 dump 根本没有；build_index 3c 段直接注入（剥除行首社区注释行，corpus_type='maptext_obc'，实测注入 1420 段），已匹配 205 条改标签 世界文书:<名称含区域>（正文仍是 dump 原文，corpus_type='maptext'）。
③其余未接名 Readable（1626 文件）：scripts/relabel_readable.py→data/pickup_labels.json。命名链：WeaponNNN 文件名数字=官方武器 ID→WeaponExcelConfigData→TextMap（248 本接名，如 斫峰之刃）；RelicNNN_x 文本包含进 obc_items.json 圣遗物套装 story（232 本接名，如 回声之林夜话）；接不上名的按内容分类（杂记 451/残句 98/诗 59/剧本 35/信件 28/日记 17/告示 1）标 世界文书:未收录·<类别>（ctype='pickup'）；武器/圣遗物/衣装接不上名的标 物品故事:未收录·<类>（ctype='flavor'）。跳转=卡层 data/obc_items.json 名称精确 join（与物品栏词条同源）。开发残留过滤 155 文件（纯 <image> 壳/（test）/？？？/<8 字）。
④降权：app.js LOW_TIERS={maptext,maptext_obc,pickup,flavor} 在 searchCorpus 排序里整层置后（strong/weak 内部同理）；query.py 同步（两端语义一致保持）。TYPE_LABEL 新增：书籍（观测枢转录）/世界文书/世界文书（观测枢转录）/世界文书（未收录）/物品故事。书名匹配栏不含世界文书（只扫 book_titles）。
export_static：src_url 改为 label_jump()，新增 世界文书:/物品故事: 前缀→data/pickup_labels.json + maptext_urls.json(仅 ok)。索引 385,962→388,062（+注入书 10 段+书名卡 5+地图文本 1420 段+世界文书条目卡 683-过滤 155 文件的段）。控制词 坎瑞亚 358 篇（+3=新注入文本合法命中），与旧库差异仅限新增层。
cron 变更：步骤 4 增加 obc_maptext.py（续抓）+ --verify + relabel_readable.py（新 pickup_labels 在下次索引重建生效）。
实测（本地预览 2026-10-27）：「字迹潦草的手记」→世界文书条目卡【蓝珀湖】+跳转（706/706 URL 全存活）；「残破的笔记」→书名卡+注入正文（暝垣山/废弃避难所两处）；「吉约丹」→主层在前、世界文书被压出前 12 名；BookNNN 标签在索引中 0 残留（仅 textmap 原始 source 保留）；开发残留过滤 155 文件。索引 385,962→388,062。
已知遗留：world-doc 名称卡只有标题+跳转，点开后本地正文需另搜内容词（OBC 跳转页含全文，够用）；带前缀的标题如「第一份蒸汽鸟报」按前缀整体成 token，搜“蒸汽鸟报”命不中该卡片（CJK 分词既有特性）；relabel 分类器是启发式（类别名可能个别不准，属标签非正文，影响小）；地图文本 501 条未匹配中还有少量同文不同点位变体（歧义 1 条已剔除）；世界文书没有书名匹配栏（搜标题词只能靠正文含标题的少数情况）——如要可加“世界文书匹配”栏，未做。

## M4.13 生物图鉴命名接回（2026-10-27，本地）
用户问题：『图鉴为什么没有名字』——AnimalCodex 行只有 descTextMapHash，生物/机关显示名（nameTextMapHash）在 dump 的所有 TextMap（CHS/EN/Medium）里都不存在（实测 3501653553 等 0 命中），出处只能落裸 'codex' 标签。观测枢敌人频道（channel 6）词条=真名标题+good_desc/collapse_panel 含同一份游戏图鉴原文，按描述文本 join 可接名+跳转。
scripts/obc_creatures.py：列表用已有 data/obc_channel_6.json（417 去重条目，与 creatures.bin 同源），逐条缓存 data/obc_creatures_raw/<id>.json（可续传）；--join：AnimalCodex desc 原文 ↔ 词条文本（12字锚点预筛+包含/6-gram≥0.9），→data/codex_match.json {descHash:{name,id,url,ok}}，HEAD 内置（--verify-only 仅复核）。实测 574 段本地图鉴文 217 段接名（未接=观测枢未收录的区域变体/亚种等）、0 歧义、0 死链。
build_index：scan_table 增加 codex_names（descTextMapHash→name），label_for 失败时兜底——出处变 'codex｜烈焰史莱姆' 形态。export_static：label_jump 增 'codex｜' 前缀→codex_match（仅 ok）。
未接的保持裸 'codex'（诚实标注）。cron：步骤4 增加 obc_creatures.py（续抓）+ --verify-only。
实测（本地预览 2026-10-27）：用户原卡「最早设计制造的新式发条机械…」出处现为 图鉴 codex｜机关·侦察记录型 + 观测枢跳转（6991/6982 实测在结果里）；索引内 215 段图鉴文带真名标签，其余（观测枢未收录的变体/亚种）保持裸 codex。

## M4.14 出处回填第二批：活动名表 + id 前缀连接 + 对白序列层（2026-10-27，本地）
用户提出"把找不到出处的文本按上下文连起来推断出处"。实测：会话文件级归属早已覆盖（同文件相邻行投票只能救 8k/81k，且多落在通用池），真正的坑是缺连接表。三处修复（scripts/resolve_qe.py）：
①活动名表换代：ActivityExcelConfigData 在现 dump 只剩 2 行存根；真表是 NewActivityExcelConfigData（401 个 activityId→nameTextMapHash）+ NewActivityEntryConfigData（tab 名）。act_label 扫 beginCond 参数的原有逻辑不变，只是喂对表。
②id 前缀连接：自由对话组/任务对话/多人任务/活动对话的文件 id 内嵌所属任务 subId（730379907→7303799、20170401→201704=每日任务「定罪公文」）。剥 1-3 位尾数、仅当 quest 表认识该 subId 才接受；多前缀指向不同任务的（实测 3 例）不采信。
③对白序列层：DialogExcelConfigData（203,908 行，seq 号同样带任务前缀）是独立管线，Walk 从未见过其中 875 条剧情向文本；新增 walk 3b 段以「剧情对白（任务…）」低优先标签接入（78,807 条 story-shaped 命中）。
顺带修 brk()：标题/名字自带「」（如 NPC「减七琶音」、任务「水仙十字大冒险」）时不再叠双括号——此前 index 里真有 579 条「」。
实测（重跑 resolve_qe + build_index，旧库备份 genshin.db.bak-2026-10-27a）：qe 表 349,193→350,068 行，带具体出处 91.7%→93.7%（+7,697 条）；索引带具体标题标签文档 307,984→312,541（+4,557），出处未定仍 25,452（6.6%，构成=通用池/无名物件/系统文本）。活动对话#N 4,544→1,028、多人任务对话 -4,945（转真名）、自由对话组#N -903、任务通用对白 -3,338（多获得活动互证标签）；875 条新文本经文本去重并入既有文档、补上出处。抽查：托马找人→自由对话组（任务「定罪公文」）、203 条 剧情对白（任务「为了一切向往生命的孩子们」）等全部语义吻合。
剩余 6.6% 的诚实上限：任务通用对白（按设计无唯一归属）、物件对话 899 文件（dump 无任何表引用其 id）、Blossom 组 cityId 无城市名表、故事板 164 文件无连接。

## （旧计划存档）观测枢接入预案
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
- ~~zstd-19 对中文文本相对 gzip 几乎无增益（16.19→16.17 MB）~~ 是假象：旧 write_gz() 把 .bin.gz 喂给了 zstd（双重压缩），所以体积≈gzip 且浏览器 DecompressionStream('zstd') 解出来仍是 gzip（bad magic，被 catch 静默回退 .gz）。已修（export_static.py 现把裸字节写临时文件再压 zstd）；真实 zst 11.57 MB vs gz 17.18 MB（-33%）。新数据已确认 zst 解出 GSBN 魔数；支持 zstd 的浏览器首载少下 ~5.6 MB。

## 待做（上线）
0. ~~M4.5 出处回填~~ 已完成（见顶部状态）。剩余 ~10% 如实保留「出处未定」（实测：Talk 树里也确实没有引用方）。
1. 托管二选一：GitHub Pages（代码顺带上 GitHub）或 Cloudflare Pages；均需一次性注册免费账号（用户本人在场）。
2. 数据刷新管线：social_fetch update → export_static.py 重导出 → 部署。上线前手动跑；上线后迁 GitHub Actions。
3. 米游社/B站正文补齐（风控冷却中，9:30 cron 自动重试）后重导出，1,435 条米游社正文与 B站简介进社媒区块。
4. 语义"暗示"档为 v2（vectors.npz 400MB 不进浏览器；接免费推理接口，PLAN 已定）。
