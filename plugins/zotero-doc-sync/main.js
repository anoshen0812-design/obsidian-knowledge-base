const { Notice, Plugin } = require("obsidian");
const { execFile } = require("child_process");
const path = require("path");

module.exports = class ZoteroDocSyncPlugin extends Plugin {
  async onload() {
    this.busy = false;
    this.pluginData = (await this.loadData()) || {};
    if (!this.pluginData.lastLintAt) {
      this.pluginData.lastLintAt = Date.now();
      await this.saveData(this.pluginData);
    }

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
      name: "开始或继续当前论文的逐段精读（Mode A）",
      callback: () => this.startOrContinueParagraphReading(),
    });

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

  execPython(script, args, timeoutMs) {
    return new Promise((resolve, reject) => {
      execFile(
        "/usr/bin/python3",
        [script, ...args],
        { timeout: timeoutMs, maxBuffer: 4 * 1024 * 1024 },
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
    if (!file || !/^wiki\/papers\/[^/]+\.md$/.test(file.path)) {
      new Notice("请先打开 wiki/papers 下的主论文笔记");
      return;
    }
    const frontmatter = this.app.metadataCache.getFileCache(file)?.frontmatter || {};
    if (frontmatter.paragraph_reading !== true && frontmatter.paragraph_reading !== "true") {
      new Notice("请先在当前笔记属性中勾选 paragraph_reading");
      return;
    }

    return this.withLock(true, "逐段精读", async () => {
      await this.runPipeline(
        ["paragraph-read", "--note", file.path],
        65 * 60 * 1000
      );
      const companionPath = path.posix.join(
        "wiki",
        "papers",
        "close-reading",
        file.name
      );
      const companion = this.app.vault.getAbstractFileByPath(companionPath);
      if (companion) {
        await this.app.workspace.getLeaf("tab").openFile(companion);
      }
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
