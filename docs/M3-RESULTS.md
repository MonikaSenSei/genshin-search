# M3 结果（2026-10-23）

## 交付物
- 社媒语料库：index/social.db（SQLite FTS5，与 genshin.db 分库；CJK 按 M1 的 tok_cjk 单字切分约定）
  - 官网新闻（米哈游 content_v2 API，iChanId=717 全归档）：4,569 条入库 + 183 条同文重发按正文哈希去重（crossrefs 表记录替代出处）
  - 米游社官号动态流（getNewsList type=2 + getPostFull 正文）：标题流 1,435 条（2019-05 至今），正文抓取当晚触发风控（retcode 1034），已改为失败不入库、下次自动补抓（见"待补"）
  - B站官号视频简介（wbi 签名 + buvid 引导）：代码就绪（含 412/-352 风控退避重试），当晚被风控，待补抓
- 抓取器：scripts/social_fetch.py（backfill/update/search/stats；跨源按去标签正文哈希去重，逐页提交）
- 版本自动更新管线：scripts/check_update.py（每日 1 次 API 调用比对 sha；发现新版本才做 git-trees 分层 diff → gh-proxy 下载变更文件 → 重建索引/向量）；基线已写入 index/update_state.json（CNRELWin7.1.0, sha 792978e5）
- 定时维护：Hermes cron「genshin-search-daily-maintenance」（每天 9:30，job 12a2ad14881c）：社媒增量抓取 + 版本检测，发现新版本自动 --apply --rebuild，输出一句话摘要。注意：本会话为纯 CLI，任务输出为 local 存档（cron 列表可见），不会推送到聊天。
- 接口图谱与坑已沉淀至 skill game-text-corpus（references/social-official-apis.md）

## 验收
- 检索：social_fetch.py search「神铸赋形」「前瞻特别节目」→ 命中官网新闻正文+出处 URL（本机实测通过）
- 去重：同文重发 183 条识别为 crossrefs（机制实测有效）
- 版本检测：无变化路径实测（输出"无新版本：语料仍为 7.1.0"）；基线记录实测

## 与 PLAN 的出入（如实报告）
- B站动态（视频简介之外的官号文字动态）2026 年起全面登录墙：动态 tab 跳登录、polymer feed 匿名返回空、t.bilibili.com 为空壳。按 PLAN 预批的退路处理：官网新闻 + 米游社官号承载同一文案，B站保留视频简介（匿名可取）。
- 官网新闻与米游社公告正文并非逐字节相同（导语/排版有差异），跨源去重以正文哈希命中同文重发；如 M4 需要"同事件跨源聚合"，需再加标题相似度层（暂未做，数据已具备）。

## 待补（自愈，无需人工干预即会尝试）
1. 米游社 1,435 条正文与 B站视频简介：当晚两平台风控（1034/-352）；代码已按"失败不标记已知"设计，第二天 9:30 cron 的 update 会自动补抓。也可手动：`python3 scripts/social_fetch.py update`
   - 进度 2026-10-24：mys 正文已补入 139 条（老帖 1034 风控仍占多数，逐日自愈）；bili 仍 412 风控未通。
   - 已知坑：update 的增量停止条件是"整页 id 全部已知"，正文抓取失败会让该页永远算 fresh，于是每次 update 都会把米游社列表从最新翻到最旧（4700+ 条，>1500s 会被超时打断）。补抓完成前属预期行为；若长期不收敛，改为"连续 K 页 0 新增即停"。
2. 版本管线正向用例（两版本间真实 diff）：GitHub 匿名限流 60/小时被本机共享 IP 耗尽，验证顺延；机制已在 README 级 diff 上走通（正确输出"语料相关 0 个"）。7.2 数据更新落地时会自然发生一次，可手动 `python3 scripts/check_update.py --apply --rebuild` 观察。

## 命令
- 抓取/增量：python3 scripts/social_fetch.py backfill|update [--source takumi,mys,bili]
- 检索：python3 scripts/social_fetch.py search 关键词 [--limit N]
- 版本：python3 scripts/check_update.py（检查）/ --apply --rebuild（更新+重建，约 30 分钟）
