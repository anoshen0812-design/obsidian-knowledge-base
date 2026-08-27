# Obsidian Knowledge Base

一套将 Zotero 文献、Obsidian 实验笔记与 Codex 串联起来的本地、自生长知识库工具。

本仓库只包含插件与自动化脚本，不包含任何 PDF、笔记正文、对话记录、运行日志、Zotero 条目或本机配置。

## 目录

- `plugins/codex-note-chat/`：在当前笔记中打开可移动问答窗，按需加入来源 PDF、选中文本和出链笔记，并支持人工复核及写回对话。
- `plugins/zotero-doc-sync/`：定期同步 Zotero collection，并驱动知识任务队列。
- `plugins/pdf-selection-translator/`：在 Obsidian PDF 阅读器中翻译选中文本；包含 TypeScript 源码和构建产物。
- `knowledge-base/`：Zotero PDF 镜像、PDF 文本提取、草稿生成、人工审核、知识整合和健康检查脚本。

## 安装

1. 将需要的插件目录复制到 `<vault>/.obsidian/plugins/`，并在 Obsidian 中启用。
2. 将 `knowledge-base/` 内的内容复制到 vault 根目录。
3. 分别复制两个 `config.example.json` 为 `config.json`，填写本机路径和 Zotero collection 名称。
4. 确保 Zotero 已开启本地 API，并安装 `pdftotext` 与 Codex CLI。
5. 在 vault 中创建 `sources/literature/`、`笔记/实验笔记/`、`extracts/papers/` 和 `wiki/` 所需目录。

手动验证：

```bash
python3 system/zotero-sync/sync_zotero_doc.py
python3 system/knowledge/run_pipeline.py scan
python3 system/knowledge/run_pipeline.py status
python3 system/knowledge/run_pipeline.py ingest-next
```

## 数据边界

- `sources/literature/pdf/` 和实验笔记是原始资料，流水线只读取，不覆盖。
- 未审核草稿只进入 `wiki/papers/` 或 `wiki/experiments/`。
- 只有明确标记为 `status: reviewed` 的笔记才能更新规范知识页。
- 所有论文声明应保留来源 PDF 页码链接；不确定页码时必须标记待核对。
- `config.json`、`data.json`、队列状态、日志和生成内容已由 `.gitignore` 排除。

## PaperForge 版本

`paperforge` 分支在论文摄取阶段调用 PaperForge 阅读 skill，并继续遵守本知识库的来源链接、草稿审核和整合规则。上游 PaperForge 内容不打包在本仓库中；安装脚本会从上游仓库获取指定版本。

