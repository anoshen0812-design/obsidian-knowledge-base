# Obsidian Knowledge Base

一套将 Zotero 文献、Obsidian 实验笔记与 Codex 串联起来的本地、自生长知识库工具。

本仓库只包含插件与自动化脚本，不包含任何 PDF、笔记正文、对话记录、运行日志、Zotero 条目或本机配置。

## 目录

- `plugins/codex-note-chat/`：在当前笔记中打开可移动、八方向缩放的紧凑问答窗，按需加入来源 PDF、选中文本和出链笔记，并支持人工复核及写回对话。
- `plugins/zotero-doc-sync/`：定期同步 Zotero collection，并驱动知识任务队列。
- `knowledge-base/system/zotero-sync/`：自动发现、校验并缓存 PDF Supporting Information，供 Forge Paper Note 按需核对。
- `plugins/pdf-selection-translator/`：在 Obsidian PDF 阅读器中翻译选中文本；包含 TypeScript 源码和构建产物。
- `knowledge-base/`：Zotero PDF 镜像、PDF 文本提取、草稿生成、人工审核、知识整合和健康检查脚本。

## 安装

1. 将需要的插件目录复制到 `<vault>/.obsidian/plugins/`，并在 Obsidian 中启用。
2. 将 `knowledge-base/` 内的内容复制到 vault 根目录。
3. 分别复制两个 `config.example.json` 为 `config.json`，填写本机路径和 Zotero collection 名称。
4. 确保 Zotero 已开启本地 API，并安装 MinerU、`pdftotext` 与 Codex CLI。MinerU 是主解析器，`pdftotext` 是自动回退。
5. 在 vault 中创建 `sources/literature/`、`笔记/实验笔记/`、`extracts/papers/`、`wiki/papers/images/` 和其他 `wiki/` 所需目录。

推荐使用独立 Python 3.12 环境安装 MinerU，避免影响系统 Python：

```bash
brew install uv
uv venv --python 3.12 /path/to/mineru-environment
uv pip install --python /path/to/mineru-environment/bin/python -U "mineru[all]"
/path/to/mineru-environment/bin/mineru --version
```

首次实际解析会下载模型，请预留足够磁盘空间。把独立环境里的 `mineru`
绝对路径填入 `system/knowledge/config.json` 的 `mineru_path`。

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
- 论文属性自动获取并保留影响因子、统计年份、官方来源和核验时间；缺失时写 `null`，不以其他引用指标替代。
- `config.json`、`data.json`、队列状态、日志和生成内容已由 `.gitignore` 排除。

## PDF 解析

论文默认由 MinerU 解析双栏版面、公式、表格、图像和扫描页。流水线读取
MinerU 的 `content_list.json`，使用 `page_idx` 重新生成带 `## Page N` 的
Markdown，供 Forge Paper Note 保留可核查的 PDF 页码引用；MinerU 的完整图像缓存保存在
`extracts/papers/assets/`。真正写入论文笔记的裁图按论文隔离存入
`wiki/papers/images/<论文笔记名>/`，不会与其他论文共用目录。如果 MinerU 缺失、超时、失败或输出不足，流水线会
自动回退到 `pdftotext -layout`。只有两种方式都无法取得足够文本时，任务才会
进入 `needs_ocr`。

## Forge Paper Note 论文阅读

论文摄取只调用设备本地的 `forge-paper-note` skill，并继续遵守本知识库的来源链接、草稿审核、图片隔离和整合规则。首次处理论文前验证 skill：

```bash
python3 scripts/check-forge-paper-note.py
```

`forge-paper-note` 保存在 `$CODEX_HOME/skills/forge-paper-note/`，不会打包进本仓库。
在 `system/knowledge/config.json` 中把 `forge_python_path` 设为 Python 3.10+ 的绝对路径。
该 skill 复用了 DeepPaperNote 的确定性单论文流水线，并吸收了 PaperForge 的研究推理思想；两者均在下方保留来源说明。

## 致谢与引用

本项目使用本地 Forge Paper Note 流程。其研究审计方法参考了 Feijiang Han 维护的 [PaperForge](https://github.com/FeijiangHan/PaperForge)，确定性论文与图片流水线源自 [DeepPaperNote](https://github.com/917Dhj/DeepPaperNote)。如果在研究或项目中使用该流程，请保留相应上游引用：

> Han, Feijiang. *PaperForge*. GitHub repository. <https://github.com/FeijiangHan/PaperForge>.

```bibtex
@misc{han_paperforge,
  author       = {Feijiang Han},
  title        = {PaperForge},
  howpublished = {GitHub repository},
  url          = {https://github.com/FeijiangHan/PaperForge}
}
```
