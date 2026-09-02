# Zotero Doc Sync

Obsidian 桌面插件，用于定期运行 `system/zotero-sync/sync_zotero_doc.py`，随后扫描并处理知识任务。

安装时将本目录复制为：

```text
<vault>/.obsidian/plugins/zotero-doc-sync/
```

插件仅保存上次健康检查时间。Zotero collection、本机路径和其他运行参数均由 `system/zotero-sync/config.json` 与 `system/knowledge/config.json` 提供。

SI 首次发现可能需要下载较大的 Supporting Information PDF，因此单次同步允许最多 5 分钟；后续检查由清单中的刷新时间缓存，不会每分钟重复下载。

## 可选逐段精读

常规 Forge Paper Note 草稿会包含两个 Obsidian 复选属性：

- `paragraph_reading`：人工确认这篇论文值得逐段精读；
- `paragraph_reading_figures`：是否额外授权分析图表，默认关闭。

勾选 `paragraph_reading` 后，在命令面板运行“开始或继续当前论文的逐段精读
（Mode A）”。插件调用本地 `paper-reading` skill 的 MODE A，将伴随笔记写到
`wiki/papers/close-reading/`；若一次未读完，属性显示 `partial`，再次运行同一命令
会从保存的定位点续读。逐段笔记与主笔记共用该论文自己的 `images_dir`。
