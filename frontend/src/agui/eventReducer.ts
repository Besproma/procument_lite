import { z } from "zod";

import { type NavigationTarget } from "../config/navigation";
import { aguiEventSchema, type AGUIEvent } from "../schemas/agui";
import {
  parseProcurementEvent,
  type ActionsEventValue,
  type AgentStreamEventValue,
  type FormEventValue,
  type OptionsEventValue,
  type ParsedProcurementEvent,
  type ProductsEventValue,
  type QueueEventValue,
  type SceneEventValue,
  type StatusEventValue,
} from "../schemas/procurementEvents";

export interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming: boolean;
}

export interface AssistantViewState {
  threadId: string;
  currentRunId: string | null;
  running: boolean;
  traceId: string | null;
  error: string | null;
  protocolError: string | null;
  messages: DisplayMessage[];
  scene: SceneEventValue["payload"] | null;
  status: StatusEventValue["payload"] | null;
  form: FormEventValue["payload"] | null;
  options: OptionsEventValue["payload"] | null;
  products: ProductsEventValue["payload"] | null;
  actions: ActionsEventValue["payload"] | null;
  queue: QueueEventValue["payload"] | null;
  agentStreams: AgentStreamEventValue["payload"][];
  pendingNavigation: NavigationTarget | null;
  lastCustomSequence: number;
  seenEventIds: ReadonlySet<string>;
}

export function createInitialViewState(threadId: string): AssistantViewState {
  return {
    threadId,
    currentRunId: null,
    running: false,
    traceId: null,
    error: null,
    protocolError: null,
    messages: [],
    scene: null,
    status: null,
    form: null,
    options: null,
    products: null,
    actions: null,
    queue: null,
    agentStreams: [],
    pendingNavigation: null,
    lastCustomSequence: 0,
    seenEventIds: new Set<string>(),
  };
}

export function beginRunState(
  state: AssistantViewState,
  runId: string,
  userMessage?: DisplayMessage,
): AssistantViewState {
  return {
    ...state,
    currentRunId: runId,
    running: true,
    error: null,
    protocolError: null,
    // 新 Run 开始时丢弃上一 Run 尚未执行的导航副作用。否则旧 SSE 连接如果稍后
    // 才结束，Vue 的 watch 可能在新场景执行期间把用户带到旧目标页面。
    pendingNavigation: null,
    agentStreams: [],
    lastCustomSequence: 0,
    seenEventIds: new Set<string>(),
    messages: userMessage ? [...state.messages, userMessage] : state.messages,
  };
}

function applyProcurementEvent(
  state: AssistantViewState,
  event: ParsedProcurementEvent,
): AssistantViewState {
  switch (event.name) {
    case "procurement.scene": {
      const scene = event.value.payload;
      const terminal = ["completed", "aborted", "expired"].includes(scene.status);
      const scenarioChanged = state.scene?.scenarioId !== scene.scenarioId;
      return {
        ...state,
        scene,
        form: terminal || scenarioChanged ? null : state.form,
        options: terminal || scenarioChanged ? null : state.options,
        actions: terminal || scenarioChanged ? null : state.actions,
        products: scenarioChanged ? null : state.products,
        queue: scenarioChanged ? null : state.queue,
        status: scenarioChanged ? null : state.status,
      };
    }
    case "procurement.status":
      return { ...state, status: event.value.payload };
    case "procurement.form":
      return { ...state, form: event.value.payload, options: null, actions: null };
    case "procurement.options":
      return { ...state, options: event.value.payload, form: null, actions: null };
    case "procurement.products":
      return { ...state, products: event.value.payload };
    case "procurement.actions":
      return { ...state, actions: event.value.payload, form: null, options: null };
    case "procurement.queue":
      return { ...state, queue: event.value.payload };
    case "procurement.navigation":
      return { ...state, pendingNavigation: event.value.payload.target };
    case "procurement.retry":
      return {
        ...state,
        error: event.value.payload.message,
        actions: {
          title: event.value.payload.message,
          groupId: `retry_${event.value.payload.actionId}`,
          actions: [
            {
              actionId: event.value.payload.actionId,
              kind: "retry",
              label: event.value.payload.label,
              style: "primary",
            },
          ],
        },
      };
    case "procurement.agent_stream":
      return { ...state, agentStreams: [...state.agentStreams, event.value.payload] };
  }
}

/**
 * 将一条已验证 AG-UI 事件不可变地合并到页面状态。
 *
 * CUSTOM 事件必须同时匹配当前 thread/run，并保持 sequence 递增。重复 eventId 只忽略，
 * 乱序或跨 Run 事件则显示协议错误，避免旧连接覆盖新场景界面。
 */
export function reduceAGUIEvent(state: AssistantViewState, event: AGUIEvent): AssistantViewState {
  // reducer 可以理解成“事件翻译器”：后端只发送标准事件，它在这里决定页面状态如何
  // 改变。Vue 组件读取新状态后自动重新渲染，最终让用户看到文字、表单、商品或按钮。
  switch (event.type) {
    case "RUN_STARTED":
      if (event.threadId !== state.threadId || event.runId !== state.currentRunId) {
        return { ...state, protocolError: "收到不属于当前请求的 RUN_STARTED" };
      }
      return state;
    case "RUN_FINISHED":
      if (event.threadId !== state.threadId || event.runId !== state.currentRunId) {
        return { ...state, protocolError: "收到不属于当前请求的 RUN_FINISHED" };
      }
      return { ...state, running: false };
    case "RUN_ERROR":
      return { ...state, running: false, error: event.message };
    case "TEXT_MESSAGE_START":
      if (state.messages.some((message) => message.id === event.messageId)) {
        return { ...state, protocolError: "重复的文字消息开始事件" };
      }
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: event.messageId, role: "assistant", content: "", streaming: true },
        ],
      };
    case "TEXT_MESSAGE_CONTENT":
      if (!state.messages.some((message) => message.id === event.messageId)) {
        return { ...state, protocolError: "文字内容事件没有对应的消息" };
      }
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.id === event.messageId
            ? { ...message, content: message.content + event.delta }
            : message,
        ),
      };
    case "TEXT_MESSAGE_END":
      if (!state.messages.some((message) => message.id === event.messageId)) {
        return { ...state, protocolError: "文字结束事件没有对应的消息" };
      }
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.id === event.messageId ? { ...message, streaming: false } : message,
        ),
      };
    case "CUSTOM": {
      try {
        const parsed = parseProcurementEvent(event.name, event.value);
        if (parsed.value.threadId !== state.threadId || parsed.value.runId !== state.currentRunId) {
          return { ...state, protocolError: "收到不属于当前 thread/run 的采购事件" };
        }
        if (state.seenEventIds.has(parsed.value.eventId)) {
          return state;
        }
        if (parsed.value.sequence <= state.lastCustomSequence) {
          return { ...state, protocolError: "采购事件 sequence 未严格递增" };
        }
        const seenEventIds = new Set(state.seenEventIds);
        seenEventIds.add(parsed.value.eventId);
        return applyProcurementEvent(
          {
            ...state,
            seenEventIds,
            lastCustomSequence: parsed.value.sequence,
          },
          parsed,
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : "未知协议错误";
        return { ...state, protocolError: `界面协议不兼容：${message}` };
      }
    }
  }
}

const snapshotSchema = z
  .object({
    threadId: z.string(),
    scenarioId: z.string().min(1).nullable(),
    scenarioStatus: z.enum(["running", "waiting", "completed", "aborted", "expired"]).nullable(),
    messages: z.array(
      z
        .object({
          messageId: z.string(),
          role: z.enum(["user", "assistant"]),
          content: z.string(),
          createdAt: z.string(),
        })
        .strict(),
    ),
    uiBlocks: z.array(z.unknown()),
    checkpointExpiresAt: z.string().nullable(),
  })
  .strict();

/** 从后端快照恢复当前投影，不重新激活历史块。 */
export function restoreSnapshot(threadId: string, rawSnapshot: unknown): AssistantViewState {
  const snapshot = snapshotSchema.parse(rawSnapshot);
  if (snapshot.threadId !== threadId) {
    throw new Error("快照 threadId 与当前会话不一致");
  }
  let state: AssistantViewState = {
    ...createInitialViewState(threadId),
    messages: snapshot.messages.map((message) => ({
      id: message.messageId,
      role: message.role,
      content: message.content,
      streaming: false,
    })),
    scene:
      snapshot.scenarioId && snapshot.scenarioStatus
        ? {
            scenarioId: snapshot.scenarioId,
            status: snapshot.scenarioStatus,
            reason: null,
          }
        : null,
  };
  for (const rawBlock of snapshot.uiBlocks) {
    const event = aguiEventSchema.parse(rawBlock);
    if (event.type !== "CUSTOM") {
      continue;
    }
    const parsed = parseProcurementEvent(event.name, event.value);
    if (parsed.value.threadId !== threadId) {
      throw new Error("快照 UI 块属于其他会话");
    }
    if (state.seenEventIds.has(parsed.value.eventId)) {
      continue;
    }
    const seenEventIds = new Set(state.seenEventIds);
    seenEventIds.add(parsed.value.eventId);
    state = applyProcurementEvent(
      // 快照可能把多个历史 Run 的最新投影合并在一起；不同 Run 的 sequence 都从 1
      // 开始，不能把它们当作同一条 SSE 流比较。当前 Run 开始后，beginRunState 会
      // 重新把 sequence 计数归零，再恢复严格递增校验。
      { ...state, seenEventIds },
      parsed,
    );
  }
  return state;
}
