# 原神文本全文检索引擎

站内可离线全文检索米哈游官方中文文本（38.6 万篇：任务/书籍/物品/技能/音频等）
与社媒帖（米游社/B站），支持说话人与出处展示、别名扩展（如"天理→法涅斯…"）。

- 检索与展示均为纯前端：`web/` 零依赖零构建，索引数据以压缩二进制容器放在 `web/data/`，浏览器内加载检索。
- 数据管线（本地运行，产物已随仓库提交）：
  - `scripts/build_index.py` 从 GDS 解包数据构建 `index/genshin.db`（FTS）
  - `scripts/social_fetch.py` 增量抓取社媒帖（每日 cron 续抓，受风控跨日自愈）
  - `scripts/resolve_qe.py` 出处回填（91%，带说话人 30.9 万条）
  - `scripts/export_static.py` 把库导出为 `web/data/` 静态容器
  - `scripts/query.py` 本地 CLI 查询（与网页端同一语义）
- 部署：Netlify（`netlify.toml` 直接发布 `web/`），推送 main 即发布。

详细里程碑与实测记录见 `docs/`。
