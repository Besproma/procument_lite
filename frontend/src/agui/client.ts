import { aguiEventSchema, httpErrorSchema, type AGUIEvent } from "../schemas/agui";

export interface PageContext {
  regionCode: string | null;
  locale: string;
  currentPage: string;
}

export type ProcurementInput =
  | { type: "scenario_trigger"; scenarioId: "smart_routing" | "knowledge_recommendation" }
  | { type: "action"; actionId: string; data: Record<string, unknown> }
  | { type: "form_submit"; actionId: string; values: Record<string, unknown> };

export interface AgentRunInput {
  threadId: string;
  runId: string;
  messages: Array<{ id: string; role: "user"; content: string }>;
  state: Record<string, never>;
  tools: never[];
  context: never[];
  forwardedProps: {
    pageContext: PageContext;
    procurementInput: ProcurementInput | null;
  };
}

export class AgentHttpError extends Error {
  readonly code: string;
  readonly traceId: string;
  readonly status: number;
  readonly snapshotUrl: string | undefined;

  constructor(
    status: number,
    body: {
      code: string;
      message: string;
      traceId: string;
      snapshotUrl?: string | undefined;
    },
  ) {
    super(body.message);
    this.name = "AgentHttpError";
    this.status = status;
    this.code = body.code;
    this.traceId = body.traceId;
    this.snapshotUrl = body.snapshotUrl;
  }
}

export interface AgentClientOptions {
  apiBaseUrl: string;
  userId: string;
}

/**
 * 读取 POST 响应中的 SSE frame，并逐条产出已经通过 Zod 的 AG-UI 事件。
 *
 * 当前实现保持在一个小适配文件中，是因为此开发环境无法安装并验证最新
 * `@ag-ui/client` 的确切 HttpAgent API。协议字段仍完全使用 AG-UI；联网锁定依赖后，
 * 只需替换此文件并运行契约测试，页面 reducer 和业务组件无需改变。
 */
export class ProcurementAgentClient {
  constructor(private readonly options: AgentClientOptions) {}

  async run(
    input: AgentRunInput,
    onEvent: (event: AGUIEvent) => void,
    signal: AbortSignal,
  ): Promise<string | null> {
    const response = await fetch(`${this.options.apiBaseUrl}/api/v1/agent`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-User-ID": this.options.userId,
      },
      body: JSON.stringify(input),
      signal,
    });
    const traceId = response.headers.get("X-Trace-ID");
    if (!response.ok) {
      const rawBody: unknown = await response.json().catch(() => null);
      const parsed = httpErrorSchema.safeParse(rawBody);
      if (!parsed.success) {
        throw new AgentHttpError(response.status, {
          code: "INVALID_ERROR_RESPONSE",
          message: "服务返回了无法识别的错误",
          traceId: traceId ?? "unknown",
        });
      }
      throw new AgentHttpError(response.status, parsed.data);
    }
    if (!response.body) {
      throw new Error("浏览器没有收到 SSE 响应流");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        this.parseFrame(frame, onEvent);
        boundary = buffer.indexOf("\n\n");
      }
      if (done) {
        if (buffer.trim()) {
          this.parseFrame(buffer, onEvent);
        }
        break;
      }
    }
    return traceId;
  }

  async loadSnapshot(threadId: string, signal?: AbortSignal): Promise<unknown> {
    // 开启 exactOptionalPropertyTypes 后，“没有 signal”与“signal 值为 undefined”
    // 是两种不同的类型。这里仅在调用方真正传入 signal 时才写入请求参数，
    // 同时也让不需要取消能力的快照恢复请求保持最简单的浏览器行为。
    const requestOptions: RequestInit = {
      headers: { "X-User-ID": this.options.userId },
    };
    if (signal !== undefined) {
      requestOptions.signal = signal;
    }

    const response = await fetch(
      `${this.options.apiBaseUrl}/api/v1/sessions/${encodeURIComponent(threadId)}/snapshot`,
      requestOptions,
    );
    if (response.status === 404) {
      // 新建 thread 在第一次 Run 之前没有数据库记录，空快照是正常状态。
      return null;
    }
    if (!response.ok) {
      const rawBody: unknown = await response.json().catch(() => null);
      const parsed = httpErrorSchema.safeParse(rawBody);
      throw new AgentHttpError(
        response.status,
        parsed.success
          ? parsed.data
          : {
              code: "SNAPSHOT_FAILED",
              message: "会话恢复失败",
              traceId: response.headers.get("X-Trace-ID") ?? "unknown",
            },
      );
    }
    return response.json() as Promise<unknown>;
  }

  private parseFrame(frame: string, onEvent: (event: AGUIEvent) => void): void {
    const data = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) {
      return;
    }
    const rawEvent: unknown = JSON.parse(data);
    onEvent(aguiEventSchema.parse(rawEvent));
  }
}
