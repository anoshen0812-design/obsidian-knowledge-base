# Zotero Doc Sync

Obsidian 桌面插件，用于定期运行 `system/zotero-sync/sync_zotero_doc.py`，随后扫描并处理知识任务。

安装时将本目录复制为：

```text
<vault>/.obsidian/plugins/zotero-doc-sync/
```

插件仅保存上次健康检查时间。Zotero collection、本机路径和其他运行参数均由 `system/zotero-sync/config.json` 与 `system/knowledge/config.json` 提供。

