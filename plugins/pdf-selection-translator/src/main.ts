import {
  App,
  Notice,
  Plugin,
  PluginSettingTab,
  Setting,
  WorkspaceLeaf,
  setIcon,
} from "obsidian";
import { placePopup, type RectLike } from "./geometry";
import {
  DEFAULT_QWEN_MT_ENDPOINT,
  QWEN_MT_MODEL,
  translateWithQwenMt,
} from "./qwen-mt";

const PDF_VIEW_TYPE = "pdf";
const MAX_CACHE_ENTRIES = 100;
const API_KEY_SECRET_ID = "pdf-selection-translator-qwen-api-key";

interface PdfTranslatorSettings {
  targetLanguage: string;
  maxSelectionCharacters: number;
  qwenEndpoint: string;
  timeoutSeconds: number;
}

const DEFAULT_SETTINGS: PdfTranslatorSettings = {
  targetLanguage: "简体中文",
  maxSelectionCharacters: 8_000,
  qwenEndpoint: DEFAULT_QWEN_MT_ENDPOINT,
  timeoutSeconds: 30,
};

interface SelectionSnapshot {
  document: Document;
  range: Range;
  text: string;
  pointer?: PointerLocation;
}

interface PdfLeafState {
  leaf: WorkspaceLeaf;
  enabled: boolean;
  button: HTMLButtonElement;
  popup?: HTMLElement;
  snapshot?: SelectionSnapshot;
  abortController?: AbortController;
  requestId: number;
}

interface PointerLocation {
  x: number;
  y: number;
}

export default class PdfSelectionTranslatorPlugin extends Plugin {
  settings: PdfTranslatorSettings = DEFAULT_SETTINGS;

  private readonly leafStates = new Map<WorkspaceLeaf, PdfLeafState>();
  private readonly observedDocuments = new WeakSet<Document>();
  private readonly observedFrames = new WeakSet<HTMLIFrameElement>();
  private readonly selectingDocuments = new WeakSet<Document>();
  private readonly selectionTimers = new Map<Document, number>();
  private readonly translationCache = new Map<string, string>();
  private refreshTimer = 0;

  async onload(): Promise<void> {
    await this.loadSettings();
    this.addSettingTab(new PdfTranslatorSettingTab(this.app, this));

    this.addCommand({
      id: "toggle-current-pdf-selection-translation",
      name: "切换当前 PDF 的划线翻译",
      checkCallback: (checking) => {
        const leaf = this.app.workspace.activeLeaf;
        if (!leaf || leaf.view.getViewType() !== PDF_VIEW_TYPE) return false;
        if (!checking) this.toggleLeaf(leaf);
        return true;
      },
    });

    this.registerEvent(this.app.workspace.on("layout-change", () => this.queueRefresh()));
    this.registerEvent(this.app.workspace.on("active-leaf-change", () => this.queueRefresh()));
    this.registerEvent(this.app.workspace.on("file-open", () => this.queueRefresh()));
    this.registerEvent(this.app.workspace.on("resize", () => this.repositionAllPopups()));
    this.registerEvent(
      this.app.workspace.on("window-open", (_workspaceWindow, openedWindow) => {
        this.observeDocument(openedWindow.document);
        this.queueRefresh();
      }),
    );

    this.observeDocument(window.document);
    this.app.workspace.onLayoutReady(() => this.refreshPdfLeaves());
  }

  onunload(): void {
    window.clearTimeout(this.refreshTimer);
    for (const timer of this.selectionTimers.values()) window.clearTimeout(timer);
    this.selectionTimers.clear();

    for (const state of this.leafStates.values()) this.removeLeafState(state);
    this.leafStates.clear();
  }

  async loadSettings(): Promise<void> {
    const loaded = (await this.loadData()) as Partial<PdfTranslatorSettings> | null;
    this.settings = {
      targetLanguage: loaded?.targetLanguage ?? DEFAULT_SETTINGS.targetLanguage,
      maxSelectionCharacters:
        loaded?.maxSelectionCharacters ?? DEFAULT_SETTINGS.maxSelectionCharacters,
      qwenEndpoint: loaded?.qwenEndpoint ?? DEFAULT_SETTINGS.qwenEndpoint,
      timeoutSeconds: loaded?.timeoutSeconds ?? DEFAULT_SETTINGS.timeoutSeconds,
    };
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  getApiKey(): string | null {
    return this.app.secretStorage.getSecret(API_KEY_SECRET_ID)?.trim() || null;
  }

  setApiKey(apiKey: string): void {
    this.app.secretStorage.setSecret(API_KEY_SECRET_ID, apiKey.trim());
  }

  async testConnection(): Promise<number> {
    const apiKey = this.getApiKey();
    if (!apiKey) throw new Error("请先配置阿里云百炼 API Key。");
    const startedAt = performance.now();
    await translateWithQwenMt({
      apiKey,
      endpoint: this.settings.qwenEndpoint,
      sourceText: "Translation connection test.",
      targetLanguage: this.settings.targetLanguage,
      timeoutMs: this.settings.timeoutSeconds * 1_000,
    });
    return Math.round(performance.now() - startedAt);
  }

  private queueRefresh(): void {
    window.clearTimeout(this.refreshTimer);
    this.refreshTimer = window.setTimeout(() => this.refreshPdfLeaves(), 50);
  }

  private refreshPdfLeaves(): void {
    const currentLeaves = new Set<WorkspaceLeaf>();

    this.app.workspace.iterateAllLeaves((leaf) => {
      if (leaf.view.getViewType() !== PDF_VIEW_TYPE || !leaf.view.containerEl.isConnected) return;
      currentLeaves.add(leaf);
      const currentState = this.leafStates.get(leaf);
      if (!currentState || !currentState.button.isConnected) {
        if (currentState) this.removeLeafState(currentState);
        const state = this.createLeafState(leaf, currentState?.enabled ?? false);
        if (state) this.leafStates.set(leaf, state);
      }
      this.observePdfFrames(leaf);
    });

    for (const [leaf, state] of this.leafStates) {
      if (!currentLeaves.has(leaf)) {
        this.removeLeafState(state);
        this.leafStates.delete(leaf);
      }
    }
  }

  private createLeafState(leaf: WorkspaceLeaf, enabled: boolean): PdfLeafState | null {
    const header = leaf.view.containerEl.querySelector<HTMLElement>(".view-header");
    const host =
      header?.querySelector<HTMLElement>(".view-actions") ??
      header?.querySelector<HTMLElement>(".view-header-nav-buttons") ??
      header;
    if (!host) {
      this.queueRefresh();
      return null;
    }

    const button = leaf.view.containerEl.ownerDocument.createElement("button");
    button.type = "button";
    button.className = "clickable-icon pdf-translator-toggle";
    const icon = button.createSpan({ cls: "pdf-translator-toggle-icon" });
    setIcon(icon, "languages");
    button.createSpan({ cls: "pdf-translator-toggle-dot" });
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.toggleLeaf(leaf);
    });
    host.prepend(button);

    const state: PdfLeafState = { leaf, enabled, button, requestId: 0 };
    this.updateToggleAppearance(state);
    return state;
  }

  private removeLeafState(state: PdfLeafState): void {
    this.closePopup(state);
    state.button.remove();
  }

  private toggleLeaf(leaf: WorkspaceLeaf): void {
    let state = this.leafStates.get(leaf);
    if (!state) {
      this.refreshPdfLeaves();
      state = this.leafStates.get(leaf);
    }
    if (!state) return;

    if (!state.enabled && !this.getApiKey()) {
      new Notice("请先在“PDF Selection Translator”设置中配置阿里云百炼 API Key。");
      return;
    }

    state.enabled = !state.enabled;
    if (!state.enabled) this.closePopup(state);
    this.updateToggleAppearance(state);
    new Notice(state.enabled ? "当前 PDF 已开启划线翻译" : "当前 PDF 已关闭划线翻译", 1800);
  }

  private updateToggleAppearance(state: PdfLeafState): void {
    const label = state.enabled ? "划线翻译：已开启（点击关闭）" : "划线翻译：已关闭（点击开启）";
    state.button.classList.toggle("is-enabled", state.enabled);
    state.button.setAttribute("aria-pressed", String(state.enabled));
    state.button.setAttribute("aria-label", label);
    state.button.setAttribute("data-tooltip-position", "bottom");
    state.button.title = label;
  }

  private observePdfFrames(leaf: WorkspaceLeaf): void {
    this.observeDocument(leaf.view.containerEl.ownerDocument);
    for (const frame of Array.from(leaf.view.containerEl.querySelectorAll("iframe"))) {
      if (!this.observedFrames.has(frame)) {
        this.observedFrames.add(frame);
        this.registerDomEvent(frame, "load", () => {
          try {
            if (frame.contentDocument) this.observeDocument(frame.contentDocument);
          } catch {
            // Cross-origin frames cannot be inspected; Obsidian's PDF frame is same-origin.
          }
        });
      }
      try {
        if (frame.contentDocument) this.observeDocument(frame.contentDocument);
      } catch {
        // See the load handler above.
      }
    }
  }

  private observeDocument(document: Document): void {
    if (this.observedDocuments.has(document)) return;
    this.observedDocuments.add(document);

    this.registerDomEvent(document, "mouseup", (event) => {
      this.selectingDocuments.delete(document);
      if (this.isPopupTarget(event.target)) return;
      this.scheduleSelection(document, 20, { x: event.clientX, y: event.clientY });
    });
    this.registerDomEvent(document, "selectionchange", () => {
      if (this.selectingDocuments.has(document)) return;
      this.scheduleSelection(document, 260);
    });
    this.registerDomEvent(document, "keydown", (event) => {
      if (event.key === "Escape") this.closeDocumentPopups(document);
      if (event.shiftKey && event.key.startsWith("Arrow")) this.scheduleSelection(document, 80);
    });
    this.registerDomEvent(
      document,
      "pointerdown",
      (event) => {
        this.selectingDocuments.add(document);
        if (!this.isPopupTarget(event.target)) this.closeDocumentPopups(document);
      },
      { capture: true },
    );
    this.registerDomEvent(document, "pointercancel", () => this.selectingDocuments.delete(document));
    this.registerDomEvent(
      document,
      "scroll",
      () => document.defaultView?.requestAnimationFrame(() => this.repositionAllPopups()),
      { capture: true, passive: true },
    );
  }

  private scheduleSelection(document: Document, delay: number, pointer?: PointerLocation): void {
    const previous = this.selectionTimers.get(document);
    if (previous !== undefined) window.clearTimeout(previous);
    const timer = window.setTimeout(() => {
      this.selectionTimers.delete(document);
      this.handleSelection(document, pointer);
    }, delay);
    this.selectionTimers.set(document, timer);
  }

  private handleSelection(document: Document, pointer?: PointerLocation): void {
    const selection = document.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) return;

    const range = selection.getRangeAt(0);
    if (this.isNodeInAnyPopup(range.commonAncestorContainer)) return;

    const state = this.findLeafStateForNode(range.commonAncestorContainer);
    if (!state?.enabled) return;

    const text = normalizePdfSelection(selection.toString());
    if (!text) return;

    if (text.length > this.settings.maxSelectionCharacters) {
      this.closeOtherPopups(state);
      const snapshot = { document, range: range.cloneRange(), text, pointer };
      this.showPopup(state, snapshot, pointer);
      this.renderError(
        state,
        `已选择 ${text.length.toLocaleString()} 个字符，超过当前上限 ${this.settings.maxSelectionCharacters.toLocaleString()}。请缩小选区或在设置中提高上限。`,
        false,
      );
      return;
    }

    if (state.popup && state.snapshot?.text === text) return;

    this.closeOtherPopups(state);
    const snapshot = { document, range: range.cloneRange(), text, pointer };
    this.showPopup(state, snapshot, pointer);
    void this.translateSnapshot(state);
  }

  private async translateSnapshot(state: PdfLeafState): Promise<void> {
    const snapshot = state.snapshot;
    if (!snapshot || !state.popup) return;

    const requestId = ++state.requestId;
    this.renderLoading(state);
    const cacheKey = `${QWEN_MT_MODEL}\n${this.settings.targetLanguage}\n${snapshot.text}`;
    const cached = this.translationCache.get(cacheKey);
    if (cached) {
      this.translationCache.delete(cacheKey);
      this.translationCache.set(cacheKey, cached);
      this.renderTranslation(state, cached);
      return;
    }

    const apiKey = this.getApiKey();
    if (!apiKey) {
      this.renderError(state, "请在插件设置中配置阿里云百炼 API Key。", false);
      return;
    }

    state.abortController?.abort();
    const abortController = new AbortController();
    state.abortController = abortController;
    try {
      const translation = await translateWithQwenMt({
        apiKey,
        endpoint: this.settings.qwenEndpoint,
        sourceText: snapshot.text,
        targetLanguage: this.settings.targetLanguage,
        timeoutMs: this.settings.timeoutSeconds * 1_000,
        signal: abortController.signal,
      });
      if (state.requestId !== requestId || !state.popup) return;
      this.cacheTranslation(cacheKey, translation);
      this.renderTranslation(state, translation);
    } catch (error) {
      if (state.requestId !== requestId || !state.popup) return;
      const message = error instanceof Error ? error.message : "翻译失败，请重试。";
      this.renderError(state, message, true);
    } finally {
      if (state.abortController === abortController) state.abortController = undefined;
    }
  }

  private cacheTranslation(key: string, value: string): void {
    this.translationCache.set(key, value);
    if (this.translationCache.size <= MAX_CACHE_ENTRIES) return;
    const oldestKey = this.translationCache.keys().next().value as string | undefined;
    if (oldestKey) this.translationCache.delete(oldestKey);
  }

  private showPopup(
    state: PdfLeafState,
    snapshot: SelectionSnapshot,
    pointer?: PointerLocation,
  ): void {
    this.closePopup(state);
    state.snapshot = snapshot;

    const document = state.leaf.view.containerEl.ownerDocument;
    const popup = document.createElement("section");
    popup.className = "pdf-translator-popup";
    popup.setAttribute("role", "dialog");
    popup.setAttribute("aria-label", "PDF 选区翻译");
    popup.addEventListener("pointerdown", (event) => event.stopPropagation());

    const header = popup.createDiv({ cls: "pdf-translator-popup-header" });
    const title = header.createDiv({ cls: "pdf-translator-popup-title" });
    const titleIcon = title.createSpan({ cls: "pdf-translator-popup-title-icon" });
    setIcon(titleIcon, "languages");
    title.createSpan({ text: `翻译 · ${this.settings.targetLanguage}` });

    const actions = header.createDiv({ cls: "pdf-translator-popup-actions" });
    const copyButton = actions.createEl("button", {
      cls: "clickable-icon pdf-translator-copy",
      attr: { type: "button", "aria-label": "复制翻译", title: "复制翻译" },
    });
    setIcon(copyButton, "copy");
    copyButton.addEventListener("click", () => void this.copyTranslation(state));

    const closeButton = actions.createEl("button", {
      cls: "clickable-icon",
      attr: { type: "button", "aria-label": "关闭翻译", title: "关闭" },
    });
    setIcon(closeButton, "x");
    closeButton.addEventListener("click", () => this.closePopup(state));

    popup.createDiv({ cls: "pdf-translator-popup-body", attr: { "aria-live": "polite" } });
    document.body.appendChild(popup);
    state.popup = popup;

    this.positionPopup(state, pointer);
  }

  private renderLoading(state: PdfLeafState): void {
    const body = this.getPopupBody(state);
    if (!body) return;
    body.replaceChildren();
    body.addClass("is-loading");
    const loading = body.createDiv({ cls: "pdf-translator-loading" });
    loading.createSpan({ cls: "pdf-translator-spinner" });
    loading.createSpan({ text: `Qwen-MT · ${QWEN_MT_MODEL} 正在翻译…` });
    this.schedulePopupPosition(state);
  }

  private renderTranslation(state: PdfLeafState, translation: string): void {
    const body = this.getPopupBody(state);
    if (!body) return;
    body.replaceChildren();
    body.removeClass("is-loading", "is-error");
    body.createDiv({ cls: "pdf-translator-result", text: translation });
    state.popup?.setAttribute("data-translation", translation);
    this.schedulePopupPosition(state);
  }

  private renderError(state: PdfLeafState, message: string, canRetry: boolean): void {
    const body = this.getPopupBody(state);
    if (!body) return;
    body.replaceChildren();
    body.removeClass("is-loading");
    body.addClass("is-error");
    const errorRow = body.createDiv({ cls: "pdf-translator-error" });
    const errorIcon = errorRow.createSpan({ cls: "pdf-translator-error-icon" });
    setIcon(errorIcon, "circle-alert");
    errorRow.createDiv({ text: message });
    if (canRetry) {
      const retryButton = body.createEl("button", {
        cls: "mod-cta pdf-translator-retry",
        text: "重试",
        attr: { type: "button" },
      });
      retryButton.addEventListener("click", () => void this.translateSnapshot(state));
    }
    this.schedulePopupPosition(state);
  }

  private async copyTranslation(state: PdfLeafState): Promise<void> {
    const translation = state.popup?.getAttribute("data-translation");
    if (!translation) return;
    try {
      await navigator.clipboard.writeText(translation);
      new Notice("翻译已复制", 1500);
    } catch {
      new Notice("复制失败，请手动选择翻译文本。", 2200);
    }
  }

  private getPopupBody(state: PdfLeafState): HTMLElement | null {
    return state.popup?.querySelector<HTMLElement>(".pdf-translator-popup-body") ?? null;
  }

  private closePopup(state: PdfLeafState): void {
    state.abortController?.abort();
    state.abortController = undefined;
    state.requestId += 1;
    state.popup?.remove();
    state.popup = undefined;
    state.snapshot = undefined;
  }

  private closeOtherPopups(except: PdfLeafState): void {
    for (const state of this.leafStates.values()) {
      if (state !== except) this.closePopup(state);
    }
  }

  private closeDocumentPopups(document: Document): void {
    for (const state of this.leafStates.values()) {
      if (state.popup?.ownerDocument === document || state.snapshot?.document === document) {
        this.closePopup(state);
      }
    }
  }

  private schedulePopupPosition(state: PdfLeafState): void {
    state.popup?.ownerDocument.defaultView?.requestAnimationFrame(() => this.positionPopup(state));
  }

  private repositionAllPopups(): void {
    for (const state of this.leafStates.values()) {
      if (state.popup) this.positionPopup(state);
    }
  }

  private positionPopup(state: PdfLeafState, pointer?: PointerLocation): void {
    const { popup, snapshot } = state;
    if (!popup || !snapshot || !popup.isConnected) return;

    const boundaryElement =
      state.leaf.view.containerEl.querySelector<HTMLElement>(".view-content") ??
      state.leaf.view.containerEl;
    const boundary = boundaryElement.getBoundingClientRect();
    const sourceAnchor = chooseRangeRect(snapshot.range, pointer ?? snapshot.pointer);
    if (!sourceAnchor) return;
    const anchor = convertRectToDocument(sourceAnchor, snapshot.document, popup.ownerDocument);
    if (!anchor) return;

    const availableWidth = Math.max(140, boundary.width - 20);
    const availableHeight = Math.max(80, boundary.height - 20);
    popup.style.width = `${Math.min(380, availableWidth)}px`;
    popup.style.maxHeight = `${availableHeight}px`;

    const measured = popup.getBoundingClientRect();
    const placement = placePopup(anchor, boundary, {
      width: measured.width,
      height: measured.height,
    });
    popup.style.left = `${Math.round(placement.left)}px`;
    popup.style.top = `${Math.round(placement.top)}px`;
    popup.dataset.side = placement.side;
  }

  private findLeafStateForNode(node: Node): PdfLeafState | undefined {
    return Array.from(this.leafStates.values()).find(
      (state) => state.enabled && isNodeInsideView(node, getPdfSelectionRoot(state.leaf)),
    );
  }

  private isNodeInAnyPopup(node: Node): boolean {
    return Array.from(this.leafStates.values()).some((state) => state.popup?.contains(node));
  }

  private isPopupTarget(target: EventTarget | null): boolean {
    return isNodeEventTarget(target) && this.isNodeInAnyPopup(target);
  }

}

class PdfTranslatorSettingTab extends PluginSettingTab {
  constructor(app: App, private readonly plugin: PdfSelectionTranslatorPlugin) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "PDF Selection Translator" });
    containerEl.createDiv({
      cls: "setting-item-description pdf-translator-settings-intro",
      text: `选中的 PDF 文本会发送到阿里云百炼 ${QWEN_MT_MODEL}。API Key 保存在 Obsidian 安全凭据存储中，不会写入插件配置或源码。`,
    });

    let pendingApiKey = "";
    let apiKeyInput: HTMLInputElement | undefined;
    const apiKeySetting = new Setting(containerEl)
      .setName("阿里云百炼 API Key")
      .setDesc(
        this.plugin.getApiKey()
          ? "密钥已安全保存。输入新密钥并点击保存可替换。"
          : "尚未保存密钥。密钥只会进入 Obsidian 安全凭据存储。",
      );
    apiKeySetting.addText((text) => {
      apiKeyInput = text.inputEl;
      text.inputEl.type = "password";
      text.inputEl.autocomplete = "off";
      text
        .setPlaceholder(this.plugin.getApiKey() ? "已保存" : "sk-…")
        .onChange((value) => {
          pendingApiKey = value.trim();
        });
    });
    apiKeySetting.addButton((button) =>
      button.setButtonText("保存密钥").onClick(() => {
        if (!pendingApiKey) {
          new Notice("请输入 API Key。", 2200);
          return;
        }
        this.plugin.setApiKey(pendingApiKey);
        pendingApiKey = "";
        if (apiKeyInput) {
          apiKeyInput.value = "";
          apiKeyInput.placeholder = "已保存";
        }
        apiKeySetting.setDesc("密钥已安全保存。输入新密钥并点击保存可替换。");
        new Notice("阿里云百炼 API Key 已安全保存。", 2200);
      }),
    );

    new Setting(containerEl)
      .setName("API 地址")
      .setDesc("默认使用中国大陆（北京）兼容端点；如密钥属于其他地域，请填写对应地址。")
      .addText((text) => {
        text
          .setPlaceholder(DEFAULT_QWEN_MT_ENDPOINT)
          .setValue(this.plugin.settings.qwenEndpoint)
          .onChange(async (value) => {
            this.plugin.settings.qwenEndpoint = value.trim() || DEFAULT_QWEN_MT_ENDPOINT;
            await this.plugin.saveSettings();
          });
        text.inputEl.spellcheck = false;
      });

    new Setting(containerEl)
      .setName("目标语言")
      .setDesc("例如：简体中文、English、日本語。")
      .addText((text) =>
        text
          .setPlaceholder("简体中文")
          .setValue(this.plugin.settings.targetLanguage)
          .onChange(async (value) => {
            this.plugin.settings.targetLanguage = value.trim().slice(0, 80);
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("单次选择字符上限")
      .setDesc("防止误选整篇文档造成高延迟和过多 API 用量（1,000–20,000）。")
      .addText((text) => {
        text.inputEl.type = "number";
        text.inputEl.min = "1000";
        text.inputEl.max = "20000";
        text.inputEl.step = "500";
        text.setValue(String(this.plugin.settings.maxSelectionCharacters));
        text.onChange(async (value) => {
          const parsed = Number.parseInt(value, 10);
          if (!Number.isFinite(parsed)) return;
          this.plugin.settings.maxSelectionCharacters = Math.min(20_000, Math.max(1_000, parsed));
          await this.plugin.saveSettings();
        });
      });

    new Setting(containerEl)
      .setName("翻译超时")
      .setDesc("等待 Qwen-MT 完成单次翻译的最长时间（5–120 秒）。")
      .addText((text) => {
        text.inputEl.type = "number";
        text.inputEl.min = "5";
        text.inputEl.max = "120";
        text.inputEl.step = "5";
        text.setValue(String(this.plugin.settings.timeoutSeconds));
        text.onChange(async (value) => {
          const parsed = Number.parseInt(value, 10);
          if (!Number.isFinite(parsed)) return;
          this.plugin.settings.timeoutSeconds = Math.min(120, Math.max(5, parsed));
          await this.plugin.saveSettings();
        });
      });

    new Setting(containerEl)
      .setName("连接测试")
      .setDesc(`向 ${QWEN_MT_MODEL} 发送一条很短的测试文本，并显示往返耗时。`)
      .addButton((button) =>
        button.setButtonText("测试连接").onClick(async () => {
          button.setDisabled(true).setButtonText("测试中…");
          try {
            const elapsedMs = await this.plugin.testConnection();
            new Notice(`连接成功：${QWEN_MT_MODEL}，${elapsedMs} ms`, 4000);
          } catch (error) {
            new Notice(error instanceof Error ? error.message : "连接测试失败。", 5000);
          } finally {
            button.setDisabled(false).setButtonText("测试连接");
          }
        }),
      );

    containerEl.createDiv({
      cls: "setting-item-description pdf-translator-settings-note",
      text: "使用方法：打开 PDF，在该标签页右上角点击语言图标开启。随后用鼠标或键盘选择 PDF 文本，翻译弹窗会自动出现在选区附近。按 Esc 可关闭弹窗。",
    });
  }
}

function normalizePdfSelection(value: string): string {
  return value
    .replace(/\u00ad/g, "")
    .replace(/([\p{L}])-\s*\r?\n\s*(?=[\p{Ll}])/gu, "$1")
    .replace(/[\t ]+/g, " ")
    .replace(/\s*\r?\n\s*/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function chooseRangeRect(range: Range, pointer?: PointerLocation): RectLike | null {
  const rects = Array.from(range.getClientRects()).filter((rect) => rect.width > 0 && rect.height > 0);
  if (rects.length === 0) {
    const rect = range.getBoundingClientRect();
    return rect.width > 0 || rect.height > 0 ? rect : null;
  }

  if (!pointer) return rects[rects.length - 1] ?? null;
  return rects.reduce((closest, rect) => {
    const distance = distanceToRect(pointer, rect);
    return distance < closest.distance ? { rect, distance } : closest;
  }, { rect: rects[0] as DOMRect, distance: distanceToRect(pointer, rects[0] as DOMRect) }).rect;
}

function distanceToRect(point: PointerLocation, rect: RectLike): number {
  const dx = Math.max(rect.left - point.x, 0, point.x - rect.right);
  const dy = Math.max(rect.top - point.y, 0, point.y - rect.bottom);
  return dx * dx + dy * dy;
}

function convertRectToDocument(
  rect: RectLike,
  sourceDocument: Document,
  targetDocument: Document,
): RectLike | null {
  let left = rect.left;
  let top = rect.top;
  let currentDocument: Document | null = sourceDocument;

  while (currentDocument && currentDocument !== targetDocument) {
    const frame: Element | null = currentDocument.defaultView?.frameElement ?? null;
    if (!frame) return null;
    const frameRect = frame.getBoundingClientRect();
    left += frameRect.left;
    top += frameRect.top;
    currentDocument = frame.ownerDocument;
  }
  if (currentDocument !== targetDocument) return null;

  return {
    left,
    top,
    right: left + rect.width,
    bottom: top + rect.height,
    width: rect.width,
    height: rect.height,
  };
}

function isNodeInsideView(node: Node, viewContainer: HTMLElement): boolean {
  let currentNode: Node | null = node;
  let currentDocument: Document | null = node.ownerDocument;

  while (currentNode && currentDocument) {
    if (currentDocument === viewContainer.ownerDocument) return viewContainer.contains(currentNode);
    const frame: Element | null = currentDocument.defaultView?.frameElement ?? null;
    if (!frame) return false;
    currentNode = frame;
    currentDocument = frame.ownerDocument;
  }
  return false;
}

function getPdfSelectionRoot(leaf: WorkspaceLeaf): HTMLElement {
  return (
    leaf.view.containerEl.querySelector<HTMLElement>(".pdf-viewer-container") ??
    leaf.view.containerEl.querySelector<HTMLElement>(".pdf-content-container") ??
    leaf.view.containerEl.querySelector<HTMLElement>(".pdf-container") ??
    leaf.view.containerEl.querySelector<HTMLElement>(".view-content") ??
    leaf.view.containerEl
  );
}

function isNodeEventTarget(target: EventTarget | null): target is Node {
  return target !== null && typeof (target as Node).nodeType === "number";
}
