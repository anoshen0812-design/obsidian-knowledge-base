# Zotero Doc 自动同步

Obsidian 的本地插件每 60 秒检查一次 Zotero 的 `Doc` 分类，将 PDF 镜像到
`sources/literature/pdf/`，并更新：

- `sources/literature/references.bib`
- `sources/literature/index.md`
- `sources/literature/manifests/zotero-doc.json`

同步器也会识别 Zotero 中已有的 SI 子附件，并通过结构化仓储或论文正式页面
发现可公开下载的 PDF Supporting Information。验证为 PDF 后，它们会独立缓存到
`sources/literature/si/<Zotero parent key>/`，来源、哈希、检查时间和失败原因记录在
`sources/literature/manifests/supporting-information.json`。SI 失败不会阻断主论文同步，
未找到时会按 `retry_days` 延迟重试，已找到的文件按 `refresh_days` 检查更新。

SI 不会作为新论文加入知识队列，也不会默认进入模型上下文。PaperForge 仅在主文
明确指向 SI 且某个具体方法、数值、图表或推导无法从主文核实时，才读取相关 SI 页。

Zotero 和 Obsidian 必须处于运行状态，并启用“允许其他应用与 Zotero 通信”。
Zotero 没有运行时，同步会安全退出，下一轮自动重试。
若 Zotero 的 BibTeX 转换器单次报错，程序会保留上一版 `references.bib`，同时继续
更新 PDF、SI、索引、清单和知识队列；下一轮会自动重试参考文献导出。

同步完成后，程序会将新 PDF 加入知识队列，并自动处理一条待办任务：提取
PDF 文本、调用 Codex、生成 `wiki/papers/` 下的待审核草稿。草稿只有在
Obsidian 中执行“审核通过并整合当前知识笔记”后，才会更新正式概念和关系页。
草稿文件名、一级标题及索引别名统一为 `YYYY-MM-DD - 第一作者 - 文献标题`，
其中日期为草稿首次开始生成的本地日期。

手动执行一次（从 vault 根目录运行）：

```bash
python3 system/zotero-sync/sync_zotero_doc.py
```

也可以在 Obsidian 命令面板运行：

`Zotero Doc Sync: 立即同步 Zotero Doc 分类`
