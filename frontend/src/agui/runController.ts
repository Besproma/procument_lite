import {
  ProcurementAgentClient,
  type AgentRunInput,
  type PageContext,
  type ProcurementInput,
} from "./client";
import type { AGUIEvent } from "../schemas/agui";

function newId(prefix: "run" | "message"): string {
  return `${prefix}_${crypto.randomUUID().replaceAll("-", "")}`;
}

export interface RunRequest {
  threadId: string;
  pageContext: PageContext;
  text?: string;
  procurementInput?: ProcurementInput;
}

/**
 * 管理一次在途 Run 的 AbortController。页面层不能同时从同一 tab 发两个 Run；后端
 * 数据库租约仍是跨 tab、跨进程串行的最终保证。
 */
export class AgentRunController {
  private activeAbortController: AbortController | null = null;

  constructor(private readonly client: ProcurementAgentClient) {}

  get isRunning(): boolean {
    return this.activeAbortController !== null;
  }

  async run(
    request: RunRequest,
    onStart: (runId: string, messageId: string | null) => void,
    onEvent: (event: AGUIEvent) => void,
  ): Promise<string | null> {
    if (this.activeAbortController) {
      throw new Error("当前请求仍在执行，请等待完成");
    }
    const runId = newId("run");
    const messageId = request.text ? newId("message") : null;
    const input: AgentRunInput = {
      threadId: request.threadId,
      runId,
      messages:
        request.text && messageId ? [{ id: messageId, role: "user", content: request.text }] : [],
      state: {},
      tools: [],
      context: [],
      forwardedProps: {
        pageContext: request.pageContext,
        procurementInput: request.procurementInput ?? null,
      },
    };
    this.activeAbortController = new AbortController();
    onStart(runId, messageId);
    try {
      return await this.client.run(input, onEvent, this.activeAbortController.signal);
    } finally {
      this.activeAbortController = null;
    }
  }

  cancel(): void {
    this.activeAbortController?.abort();
  }
}
