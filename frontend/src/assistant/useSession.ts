import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import { AgentHttpError, ProcurementAgentClient, type ProcurementInput } from "../agui/client";
import {
  beginRunState,
  createInitialViewState,
  reduceAGUIEvent,
  restoreSnapshot,
  type AssistantViewState,
  type DisplayMessage,
} from "../agui/eventReducer";
import { AgentRunController } from "../agui/runController";
import { frontendConfig } from "../config/env";
import { navigateTo } from "../config/navigation";

const THREAD_STORAGE_KEY = "procurement-assistant-thread-id";

function newThreadId(): string {
  return `thread_${crypto.randomUUID().replaceAll("-", "")}`;
}

function loadOrCreateThreadId(): string {
  const existing = sessionStorage.getItem(THREAD_STORAGE_KEY);
  if (existing && /^[A-Za-z0-9_-]{8,80}$/.test(existing)) {
    return existing;
  }
  const created = newThreadId();
  sessionStorage.setItem(THREAD_STORAGE_KEY, created);
  return created;
}

/**
 * 管理一次浏览器会话中的 Thread、快照、在途 Run 和导航副作用。
 *
 * 这里的 state 不是 LangGraph 的内部状态，而是“后端事件转换成的页面投影”。
 * 页面只能通过下面暴露的几个函数发起动作，不能直接拼 AG-UI 请求。
 */
export function useSession() {
  const state = ref<AssistantViewState>(createInitialViewState(loadOrCreateThreadId()));
  const restoring = ref(true);
  const client = new ProcurementAgentClient({
    apiBaseUrl: frontendConfig.apiBaseUrl,
    userId: frontendConfig.userId,
  });
  const controller = new AgentRunController(client);
  let restoreAbortController: AbortController | null = null;
  let mounted = true;

  const sceneActive = computed(
    () => state.value.scene?.status === "running" || state.value.scene?.status === "waiting",
  );

  /** 从数据库快照恢复页面投影，不重新执行已经结束的 Graph 节点。 */
  const restore = async (threadId: string, signal?: AbortSignal): Promise<void> => {
    restoring.value = true;
    try {
      const snapshot = await client.loadSnapshot(threadId, signal);
      if (!mounted) {
        return;
      }
      state.value =
        snapshot === null ? createInitialViewState(threadId) : restoreSnapshot(threadId, snapshot);
    } catch (error: unknown) {
      if (!mounted || (error instanceof DOMException && error.name === "AbortError")) {
        return;
      }
      const message = error instanceof Error ? error.message : "会话恢复失败";
      state.value = { ...state.value, running: false, error: message };
    } finally {
      if (mounted) {
        restoring.value = false;
      }
    }
  };

  /**
   * 统一执行一次 Run：自然语言、场景按钮、表单和 Action 都走同一条 API 链路。
   * 每收到一条 SSE 事件，就用纯函数 reducer 生成一份新的页面状态。
   */
  const execute = async (
    text: string | undefined,
    procurementInput: ProcurementInput | undefined,
  ): Promise<void> => {
    const threadId = state.value.threadId;
    try {
      const traceId = await controller.run(
        {
          threadId,
          pageContext: {
            regionCode: frontendConfig.regionCode,
            locale: "zh-CN",
            currentPage: window.location.pathname,
          },
          ...(text === undefined ? {} : { text }),
          ...(procurementInput === undefined ? {} : { procurementInput }),
        },
        (runId, messageId) => {
          const userMessage: DisplayMessage | undefined =
            text && messageId
              ? { id: messageId, role: "user", content: text, streaming: false }
              : undefined;
          state.value = beginRunState(state.value, runId, userMessage);
        },
        (event) => {
          state.value = reduceAGUIEvent(state.value, event);
        },
      );
      state.value = { ...state.value, traceId, running: false };
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        state.value = { ...state.value, running: false, error: "本次请求已取消" };
        return;
      }
      const message = error instanceof Error ? error.message : "请求失败";
      const traceId = error instanceof AgentHttpError ? error.traceId : null;
      state.value = { ...state.value, running: false, error: message, traceId };
      // 后端在返回快照地址时，说明服务端已经保存了本轮结果；恢复它比继续猜测界面状态安全。
      if (error instanceof AgentHttpError && error.snapshotUrl) {
        await restore(threadId);
      }
    }
  };

  const sendText = (text: string): Promise<void> => execute(text, undefined);
  const triggerScenario = (scenarioId: "smart_routing" | "knowledge_recommendation") =>
    execute(undefined, { type: "scenario_trigger", scenarioId });
  const submitForm = (actionId: string, values: Record<string, unknown>) =>
    execute(undefined, { type: "form_submit", actionId, values });
  const submitAction = (actionId: string) =>
    execute(undefined, { type: "action", actionId, data: {} });

  const newSession = (): void => {
    controller.cancel();
    const threadId = newThreadId();
    sessionStorage.setItem(THREAD_STORAGE_KEY, threadId);
    state.value = createInitialViewState(threadId);
    restoring.value = false;
  };

  // 导航是一次性浏览器副作用。只有当前 Run 结束后才跳转，避免旧 SSE 晚到事件覆盖新页面。
  watch(
    () => [state.value.pendingNavigation, state.value.running] as const,
    ([pendingNavigation, running]) => {
      if (!pendingNavigation || running) {
        return;
      }
      try {
        navigateTo(pendingNavigation);
        state.value = { ...state.value, pendingNavigation: null };
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : "页面跳转失败";
        state.value = { ...state.value, pendingNavigation: null, error: message };
      }
    },
  );

  onMounted(() => {
    restoreAbortController = new AbortController();
    void restore(state.value.threadId, restoreAbortController.signal);
  });

  onUnmounted(() => {
    mounted = false;
    restoreAbortController?.abort();
    controller.cancel();
  });

  return {
    state,
    restoring,
    sceneActive,
    sendText,
    triggerScenario,
    submitForm,
    submitAction,
    newSession,
  };
}
