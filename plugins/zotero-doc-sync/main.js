const { Notice, Plugin, PluginSettingTab, Setting } = require("obsidian");
const { execFile } = require("child_process");
const path = require("path");

// OPTIONAL FEATURE START: MinerU cloud API settings tab.
class MinerUSettingTab extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.plugin = plugin; }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "MinerU PDF 解析" });
    containerEl.createEl("p", { text: "用于论文 PDF 的版面、公式、表格和图片解析。密钥仅保存在当前 Vault 的插件数据中。" });
    let keyInput = null;
    let keyVisible = false;
    // OPTIONAL FEATURE START: MinerU cloud API settings. Delete this whole
    // setting block and the MINERU_* environment entries in execPython to use
    // only the repository's local MinerU CLI backend.
    new Setting(containerEl).setName("MinerU API Key").setDesc("从 MinerU 官网复制的 API Token；点击保存密钥后才写入当前 Vault。")
      .addText((text) => {
        keyInput = text;
        text.setPlaceholder("粘贴 API Key").setValue(this.plugin.pluginData.mineruApiKey || "");
        text.inputEl.type = "password";
      })
      .addExtraButton((button) => button
        .setIcon("eye")
        .setTooltip("显示密钥")
        .onClick(() => {
          keyVisible = !keyVisible;
          keyInput.inputEl.type = keyVisible ? "text" : "password";
          button.setIcon(keyVisible ? "eye-off" : "eye");
          button.setTooltip(keyVisible ? "隐藏密钥" : "显示密钥");
        }))
      .addButton((button) => button
        .setButtonText("保存密钥")
        .setCta()
        .onClick(async () => {
          this.plugin.pluginData.mineruApiKey = keyInput.inputEl.value.trim();
          await this.plugin.saveSettings();
          new Notice(this.plugin.pluginData.mineruApiKey ? "MinerU API Key 已保存" : "已清除 MinerU API Key");
        }));
    new Setting(containerEl).setName("解析模型").setDesc("vlm：质量优先，适合中文论文、图表与公式；pipeline：速度优先。")
      .addDropdown((drop) => drop.addOption("vlm", "vlm（推荐：高质量）").addOption("pipeline", "pipeline（更快）").setValue(this.plugin.pluginData.mineruModel || "vlm").onChange(async (value) => { this.plugin.pluginData.mineruModel = value; await this.plugin.saveSettings(); }));
    new Setting(containerEl).setName("识别公式与表格").setDesc("建议保持开启，以便笔记引用原公式、表格和图表。")
      .addToggle((toggle) => toggle.setValue(this.plugin.pluginData.mineruRichContent !== false).onChange(async (value) => { this.plugin.pluginData.mineruRichContent = value; await this.plugin.saveSettings(); }));
    new Setting(containerEl).setName("配置检查").setDesc("检查 API Key 是否已保存；不会发送文献或产生费用。")
      .addButton((button) => button.setButtonText("检查").onClick(() => new Notice(this.plugin.pluginData.mineruApiKey ? "MinerU API Key 已保存，模型：" + (this.plugin.pluginData.mineruModel || "vlm") : "请先填写 MinerU API Key")));
    // OPTIONAL FEATURE END: MinerU cloud API settings.

    new Setting(containerEl).setName("Python 可执行文件").setDesc("可选。留空时 Windows 使用 python，其他系统使用 python3；若系统有多个 Python，请填写绝对路径。")
      .addText((text) => text.setPlaceholder(process.platform === "win32" ? "python" : "python3").setValue(this.plugin.pluginData.pythonPath || "").onChange(async (value) => {
        this.plugin.pluginData.pythonPath = value.trim();
        await this.plugin.saveSettings();
      }));
  }
}
// OPTIONAL FEATURE END: MinerU cloud API settings tab.

module.exports = class ZoteroDocSyncPlugin extends Plugin {
  async onload() {
    this.busy = false;
    this.pluginData = (await this.loadData()) || {};
    this.pluginData.mineruModel = this.pluginData.mineruModel || "vlm";
    this.pluginData.mineruRichContent = this.pluginData.mineruRichContent !== false;
    if (!this.pluginData.lastLintAt) {
      this.pluginData.lastLintAt = Date.now();
      await this.saveData(this.pluginData);
    }
    // OPTIONAL FEATURE: delete this line together with the MinerUSettingTab
    // block above when a deployment only uses the local MinerU CLI.
    this.addSettingTab(new MinerUSettingTab(this.app, this));

    // OPTIONAL FEATURE START: safe redraft control.
    this.addCommand({
      id: "sync-now",
      name: "立即同步 Zotero 并处理下一条知识任务",
      callback: () => this.runCycle(true),
    });

    this.addCommand({
      id: "process-next-knowledge-task",
      name: "处理下一条知识任务",
      callback: () => this.processNext(true),
    });

    this.addCommand({
      id: "start-or-continue-paragraph-reading",
      name: "开始或继续当前论文的逐段精读",
      callback: () => this.startOrContinueParagraphReading(),
    });

    this.addCommand({
      id: "redraft-current-paper-note",
      name: "安全重生成当前论文笔记",
      callback: () => this.redraftCurrentPaperNote(),
    });

    this.addCommand({
      id: "publish-current-paper-images",
      name: "发布当前论文已引用的图片",
      callback: () => this.publishCurrentPaperImages(),
    });
    // OPTIONAL FEATURE END: safe redraft control.

    this.addCommand({
      id: "approve-and-integrate-current-note",
      name: "审核通过并整合当前知识笔记",
      callback: () => this.approveAndIntegrateCurrent(),
    });

    this.addCommand({
      id: "retry-failed-knowledge-task",
      name: "重试最早的失败知识任务",
      callback: () => this.retryFailed(),
    });

    this.addCommand({
      id: "run-wiki-health-check",
      name: "运行知识库健康检查",
      callback: () => this.runLint(true),
    });

    this.addCommand({
      id: "show-knowledge-queue-status",
      name: "显示知识任务队列状态",
      callback: () => this.showQueueStatus(),
    });

    this.addRibbonIcon("refresh-cw", "同步 Zotero 并生成知识笔记", () => {
      this.runCycle(true);
    });
    // OPTIONAL FEATURE START: left-ribbon workflow shortcuts.
    this.addRibbonIcon("check-circle-2", "审核通过并整合当前知识笔记", () => {
      this.approveAndIntegrateCurrent();
    });
    this.addRibbonIcon("book-open", "开始或继续当前论文的逐段精读", () => {
      this.startOrContinueParagraphReading();
    });
    this.addRibbonIcon("images", "发布当前论文已引用的图片", () => {
      this.publishCurrentPaperImages();
    });
    // OPTIONAL FEATURE END: left-ribbon workflow shortcuts.

    this.registerInterval(window.setInterval(() => this.runCycle(false), 60 * 1000));
    this.registerInterval(window.setInterval(() => this.maybeRunWeeklyLint(), 6 * 60 * 60 * 1000));

    window.setTimeout(() => this.runCycle(false), 3000);
    window.setTimeout(() => this.maybeRunWeeklyLint(), 15000);
  }

  get basePath() {
    return this.app.vault.adapter.getBasePath();
  }

  get syncScript() {
    return path.join(this.basePath, "system", "zotero-sync", "sync_zotero_doc.py");
  }

  get pipelineScript() {
    return path.join(this.basePath, "system", "knowledge", "run_pipeline.py");
  }

  async saveSettings() { await this.saveData(this.pluginData); }

  execPython(script, args, timeoutMs) {
    return new Promise((resolve, reject) => {
      execFile(
        this.pluginData.pythonPath || (process.platform === "win32" ? "python" : "python3"),
        [script, ...args],
        { timeout: timeoutMs, maxBuffer: 4 * 1024 * 1024, env: Object.assign({}, process.env, { MINERU_API_TOKEN: this.pluginData.mineruApiKey || "", MINERU_MODEL: this.pluginData.mineruModel || "vlm", MINERU_RICH_CONTENT: this.pluginData.mineruRichContent === false ? "false" : "true" }) },
        (error, stdout, stderr) => {
          if (stdout) console.log("[Knowledge Base]", stdout.trim());
          if (stderr) console.warn("[Knowledge Base]", stderr.trim());
          if (error) {
            error.stdout = stdout;
            error.stderr = stderr;
            reject(error);
          } else {
            resolve(stdout || "");
          }
        }
      );
    });
  }

  runPipeline(args, timeoutMs = 20 * 60 * 1000) {
    return this.execPython(this.pipelineScript, args, timeoutMs);
  }

  async withLock(showNotice, label, operation) {
    if (this.busy) {
      if (showNotice) new Notice("知识库任务正在运行，请稍后再试");
      return;
    }
    this.busy = true;
    if (showNotice) new Notice(`${label}已开始`);
    try {
      await operation();
      if (showNotice) new Notice(`${label}已完成`);
    } catch (error) {
      console.error(`[Knowledge Base] ${label}`, error);
      if (showNotice) new Notice(`${label}失败，请查看控制台或 system/knowledge/logs`);
    } finally {
      this.busy = false;
    }
  }

  async runCycle(showNotice) {
    return this.withLock(showNotice, "同步和知识处理", async () => {
      try {
        await this.execPython(this.syncScript, [], 5 * 60 * 1000);
      } catch (error) {
        console.warn("[Knowledge Base] Zotero sync unavailable; continuing queued knowledge work", error);
      }
      await this.runPipeline(["ingest-next"]);
    });
  }

  async processNext(showNotice) {
    return this.withLock(showNotice, "知识笔记生成", async () => {
      await this.runPipeline(["scan"]);
      await this.runPipeline(["ingest-next"]);
    });
  }

  async startOrContinueParagraphReading() {
    const file = this.app.workspace.getActiveFile();
    if (!file || !file.path.startsWith("wiki/papers/") || file.path.includes("/close-reading/")) {
      new Notice("请先打开 wiki/papers 中的主论文笔记");
      return;
    }
    const frontmatter = (this.app.metadataCache.getFileCache(file) || {}).frontmatter || {};
    if (frontmatter.type !== "paper") {
      new Notice("当前笔记不是论文主笔记");
      return;
    }
    if (frontmatter.paragraph_reading !== true && frontmatter.paragraph_reading !== "true") {
      new Notice("请先在当前笔记属性中勾选 paragraph_reading，再启动逐段精读");
      return;
    }
    return this.withLock(true, "论文逐段精读", async () => {
      await this.runPipeline(["paragraph-read", "--note", file.path], 65 * 60 * 1000);
    });
  }

  async redraftCurrentPaperNote() {
    const file = this.app.workspace.getActiveFile();
    if (!file || !file.path.startsWith("wiki/papers/") || file.path.includes("/close-reading/")) {
      new Notice("请先打开需要重生成的主论文笔记");
      return;
    }
    const frontmatter = (this.app.metadataCache.getFileCache(file) || {}).frontmatter || {};
    if (frontmatter.type !== "paper") {
      new Notice("当前笔记不是论文主笔记");
      return;
    }
    if (!window.confirm("将按当前流程重新生成这篇论文笔记。现有笔记会先归档到 system/archive/redrafts。是否继续？")) {
      return;
    }
    return this.withLock(true, "论文笔记安全重生成", async () => {
      await this.runPipeline(["redraft", "--note", file.path]);
      await this.runPipeline(["ingest-next"]);
    });
  }

  async publishCurrentPaperImages() {
    const file = this.app.workspace.getActiveFile();
    if (!file || !file.path.startsWith("wiki/papers/") || file.path.includes("/close-reading/")) {
      new Notice("请先打开需要收拢图片的主论文笔记");
      return;
    }
    const frontmatter = (this.app.metadataCache.getFileCache(file) || {}).frontmatter || {};
    if (frontmatter.type !== "paper") {
      new Notice("当前笔记不是论文主笔记");
      return;
    }
    return this.withLock(true, "论文图片收拢", async () => {
      await this.runPipeline(["publish-paper-images", "--note", file.path]);
    });
  }

  async approveAndIntegrateCurrent() {
    const file = this.app.workspace.getActiveFile();
    if (!file || !(file.path.startsWith("wiki/papers/") || file.path.startsWith("wiki/experiments/"))) {
      new Notice("请先打开 wiki/papers 或 wiki/experiments 中的草稿笔记");
      return;
    }

    return this.withLock(true, "审核与知识整合", async () => {
      await this.app.fileManager.processFrontMatter(file, (frontmatter) => {
        if (frontmatter.status !== "draft" && frontmatter.status !== "reviewed") {
          throw new Error("当前笔记不是待审核草稿");
        }
        frontmatter.status = "reviewed";
        frontmatter.reviewed = true;
        frontmatter.reviewed_at = new Date().toISOString();
      });
      await this.runPipeline(["integrate", "--note", file.path]);
    });
  }

  async retryFailed() {
    return this.withLock(true, "失败任务重试", async () => {
      await this.runPipeline(["retry-failed"]);
      await this.runPipeline(["ingest-next"]);
    });
  }

  async runLint(showNotice) {
    return this.withLock(showNotice, "知识库健康检查", async () => {
      await this.runPipeline(["lint"]);
      this.pluginData.lastLintAt = Date.now();
      await this.saveData(this.pluginData);
    });
  }

  async maybeRunWeeklyLint() {
    const weekMs = 7 * 24 * 60 * 60 * 1000;
    if (Date.now() - Number(this.pluginData.lastLintAt || 0) >= weekMs) {
      await this.runLint(false);
    }
  }

  async showQueueStatus() {
    try {
      const output = await this.runPipeline(["status"], 30 * 1000);
      const lines = output.trim().split("\n");
      const status = JSON.parse(lines[lines.length - 1]);
      const summary = Object.entries(status.counts || {})
        .map(([key, value]) => `${key}: ${value}`)
        .join("，");
      new Notice(summary || "知识任务队列为空", 8000);
    } catch (error) {
      console.error("[Knowledge Base] queue status", error);
      new Notice("无法读取知识任务队列");
    }
  }
};
