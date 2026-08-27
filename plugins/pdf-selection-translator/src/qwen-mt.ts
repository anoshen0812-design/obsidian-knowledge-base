import { requestUrl, type RequestUrlResponse } from "obsidian";

export const QWEN_MT_MODEL = "qwen-mt-flash";
export const DEFAULT_QWEN_MT_ENDPOINT =
  "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions";

export interface QwenMtRequest {
  apiKey: string;
  endpoint: string;
  sourceText: string;
  targetLanguage: string;
  timeoutMs: number;
  signal?: AbortSignal;
}

interface QwenMtResponse {
  choices?: Array<{
    message?: {
      content?: string;
    };
  }>;
  error?: {
    code?: string;
    message?: string;
  };
  code?: string;
  message?: string;
}

export async function translateWithQwenMt(request: QwenMtRequest): Promise<string> {
  const apiKey = request.apiKey.trim();
  if (!apiKey) throw new Error("请先配置阿里云百炼 API Key。");

  const sourceText = request.sourceText.trim();
  if (!sourceText) throw new Error("没有可翻译的文本。");

  const targetLanguage = normalizeTargetLanguage(request.targetLanguage);
  const response = await raceRequest(
    requestUrl({
      url: normalizeEndpoint(request.endpoint),
      method: "POST",
      contentType: "application/json",
      headers: {
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: QWEN_MT_MODEL,
        messages: [{ role: "user", content: sourceText }],
        translation_options: {
          source_lang: "auto",
          target_lang: targetLanguage,
        },
      }),
      throw: false,
    }),
    request.timeoutMs,
    request.signal,
  );

  const payload = parsePayload(response);
  if (response.status < 200 || response.status >= 300) {
    throw new Error(formatApiError(response.status, payload));
  }

  const translation = payload.choices?.[0]?.message?.content?.trim();
  if (!translation) {
    throw new Error("Qwen-MT 没有返回可读的翻译内容，请重试。");
  }
  return translation;
}

function normalizeEndpoint(value: string): string {
  const endpoint = value.trim() || DEFAULT_QWEN_MT_ENDPOINT;
  const withoutTrailingSlash = endpoint.replace(/\/+$/, "");
  if (/\/chat\/completions$/i.test(withoutTrailingSlash)) return withoutTrailingSlash;
  if (/\/compatible-mode\/v1$/i.test(withoutTrailingSlash)) {
    return `${withoutTrailingSlash}/chat/completions`;
  }
  throw new Error("API 地址必须以 /compatible-mode/v1 或 /chat/completions 结尾。");
}

function normalizeTargetLanguage(value: string): string {
  const language = value.replace(/\s+/g, " ").trim().slice(0, 80);
  if (!language) throw new Error("请先设置目标语言。");

  const normalized = language.toLowerCase();
  const aliases: Record<string, string> = {
    "简体中文": "Chinese",
    "中文": "Chinese",
    "汉语": "Chinese",
    "chinese": "Chinese",
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "english": "English",
    "英语": "English",
    "英文": "English",
    "en": "English",
    "日本語": "Japanese",
    "日语": "Japanese",
    "japanese": "Japanese",
    "ja": "Japanese",
    "한국어": "Korean",
    "韩语": "Korean",
    "korean": "Korean",
    "ko": "Korean",
    "法语": "French",
    "french": "French",
    "德语": "German",
    "german": "German",
    "西班牙语": "Spanish",
    "spanish": "Spanish",
    "俄语": "Russian",
    "russian": "Russian",
  };
  return aliases[normalized] ?? language;
}

function parsePayload(response: RequestUrlResponse): QwenMtResponse {
  try {
    return response.json as QwenMtResponse;
  } catch {
    try {
      return JSON.parse(response.text) as QwenMtResponse;
    } catch {
      return { message: response.text.slice(0, 500) };
    }
  }
}

function formatApiError(status: number, payload: QwenMtResponse): string {
  const detail = payload.error?.message ?? payload.message ?? payload.error?.code ?? payload.code;
  if (status === 401 || status === 403) {
    return "阿里云百炼 API Key 无效、已过期或没有 Qwen-MT 调用权限。";
  }
  if (status === 429) return "Qwen-MT 请求过于频繁或额度不足，请稍后重试。";
  return detail ? `Qwen-MT 请求失败（${status}）：${detail}` : `Qwen-MT 请求失败（${status}）。`;
}

function raceRequest(
  request: Promise<RequestUrlResponse>,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<RequestUrlResponse> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(createAbortError());
      return;
    }

    let settled = false;
    const timeout = window.setTimeout(() => {
      finish(() => reject(new Error(`Qwen-MT 在 ${Math.round(timeoutMs / 1_000)} 秒内没有完成翻译。`)));
    }, timeoutMs);
    const abort = (): void => finish(() => reject(createAbortError()));
    const finish = (callback: () => void): void => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      signal?.removeEventListener("abort", abort);
      callback();
    };

    signal?.addEventListener("abort", abort, { once: true });
    request.then(
      (response) => finish(() => resolve(response)),
      (error: unknown) =>
        finish(() =>
          reject(error instanceof Error ? error : new Error("无法连接阿里云百炼服务。")),
        ),
    );
  });
}

function createAbortError(): Error {
  const error = new Error("翻译已取消。");
  error.name = "AbortError";
  return error;
}
