# PDF Selection Translator for Obsidian

在 Obsidian 的 PDF 标签页中开启开关后，选择 PDF 文本即可在选区旁自动显示翻译。插件直接调用阿里云百炼 `qwen-mt-flash`，不再启动 Codex CLI。

## 功能

- 每个 PDF 标签页右上角都有独立开关，不影响其他 PDF 标签页。
- 鼠标拖选或键盘扩展选区后自动翻译。
- 弹窗优先显示在选区右侧；空间不足时自动切换到左、下或上方，并始终限制在当前 PDF 标签页边界内。
- 支持窄分栏、窗口缩放、PDF 滚动和 Obsidian 弹出窗口。
- 翻译结果可复制；按 `Esc` 或点击关闭按钮可关闭。
- 相同文本在当前 Obsidian 会话内缓存，避免重复调用和计费。
- API Key 使用 Obsidian SecretStorage 保存，不写入 `data.json`、源码或构建文件。

## 模型与接口

- 模型：`qwen-mt-flash`。
- 默认接口：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`。
- 源语言：自动检测。
- 默认目标语言：简体中文（发送给接口时规范化为 `Chinese`）。

阿里云官方将 `qwen-mt-flash` 作为 Qwen-MT 的通用首选；如需最低延迟可后续切换到 `qwen-mt-lite`，如需论文级最高质量可切换到 `qwen-mt-plus`。

## 前置要求

- Obsidian 桌面版 1.11.4 或更高版本。
- 已开通阿里云百炼并拥有可调用 Qwen-MT 的 API Key。
- API Key 与 API 地址必须属于同一地域。

## 安装

### 从源码构建

```bash
pnpm install
pnpm build
```

把以下文件复制到你的 vault：

```text
<vault>/.obsidian/plugins/pdf-selection-translator/
├── main.js
├── manifest.json
└── styles.css
```

然后在 Obsidian 的“设置 → 第三方插件”中启用 **PDF Selection Translator**。

## 配置与使用

1. 打开“设置 → PDF Selection Translator”。
2. 输入阿里云百炼 API Key，点击“保存密钥”。
3. 如密钥不属于中国大陆（北京）地域，修改 API 地址。
4. 点击“测试连接”，确认模型权限并查看往返耗时。
5. 打开一个 PDF，在标签页右上角点击语言图标；按钮高亮表示已开启。
6. 选择 PDF 中的文本，翻译弹窗会自动出现在选区附近。

## 隐私与安全

- 发送给阿里云百炼：用户主动选中的 PDF 文本、源语言自动检测标志和目标语言。
- 不发送：PDF 文件本身、vault 路径、文件名和其他笔记内容。
- API Key 只从 Obsidian SecretStorage 读取，并仅作为 HTTPS 请求的 Bearer 凭据使用。
- 插件配置文件只保存目标语言、API 地址、字符上限和超时，不保存 API Key。

## 开发说明

插件使用 Obsidian `requestUrl` 调用 Qwen-MT 的 OpenAI 兼容 Chat Completions 端点。请求中只有一个 `user` 消息，并通过 `translation_options` 设置 `source_lang: "auto"` 与目标语言。PDF 阅读器目前没有公开的“文本选区”事件，因此选区捕获与工具栏按钮需要通过 PDF 视图的 DOM 完成；Obsidian 大版本更新后，相关 DOM 结构可能需要适配。
