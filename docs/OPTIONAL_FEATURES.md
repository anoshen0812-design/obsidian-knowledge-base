# 可选功能清单

本文件对应本次贡献中新增的通用功能。每项都可整体保留或删除；删除前请先关闭 Obsidian，并删除完整标记区域，而不是只删其中一行。

| 功能 | 文件与可删除区域 | 删除后的行为 |
| --- | --- | --- |
| MinerU Cloud API | `knowledge-base/system/knowledge/mineru_api.py`；`run_pipeline.py` 的 `OPTIONAL FEATURE START/END: MinerU cloud API backend`；`zotero-doc-sync/main.js` 的 MinerU 设置区 | 仅使用基础版本的本地 MinerU CLI 和 pdftotext 回退。 |
| 云端密钥输入、保存、显示与模型选择 | `plugins/zotero-doc-sync/main.js` 的 `MinerUSettingTab`、`MINERU_*` 环境变量及其 `OPTIONAL FEATURE` 标记 | 不再在 Obsidian 中管理 MinerU Cloud API 密钥。 |
| 左侧工作流按钮 | `plugins/zotero-doc-sync/main.js` 的 `left-ribbon workflow shortcuts` 标记区 | 相同动作仍可通过命令面板执行。 |
| 安全重生成与图片收拢入口 | `plugins/zotero-doc-sync/main.js` 的 `safe redraft control` 标记区 | 保留流水线能力时，可从命令行或命令面板调用。 |
| Codex 问答模型/推理选择、来源定位、复核写回与重试 | `plugins/codex-note-chat/main.js` 中 `OPTIONAL FEATURE` 标记的交互区 | 保留基础问答窗；移除前需同时删掉对应按钮、状态和辅助函数。 |

## 兼容性原则

- 不提交 `config.json`、插件 `data.json`、PDF、笔记、解析缓存、日志或运行队列。
- 云端 API 只在用户明确选择 `pdf_extractor: "mineru-cloud"` 时调用。
- 本地 MinerU CLI 是基础版本的默认路径，不被本次可选功能替换。
- 每项功能应先在干净 Vault 中验证后再启用到生产知识库。
