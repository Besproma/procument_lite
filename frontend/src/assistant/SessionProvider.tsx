import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AgentHttpError, ProcurementAgentClient, type ProcurementInput } from "../agui/client";
import {
  beginRunState,
  createInitialViewState,
  reduceAGUIEvent,
  restoreSnapshot,
  type DisplayMessage,
} from "../agui/eventReducer";
import { AgentRunController } from "../agui/runController";
import { frontendConfig } from "../config/env";
import { navigateTo } from "../config/navigation";
import { SessionContext, type SessionContextValue } from "./sessionContext";

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
 * 维护当前 tab 的 thread、快照、一次在途 Run 和导航副作用。
 *
 * Graph State 永远不保存在 React 中；这里保存的只是服务端事件形成的可展示投影。
 */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState(() => createInitialViewState(loadOrCreateThreadId()));
  const [restoring, setRestoring] = useState(true);
  const client = useMemo(
    () =>
      new ProcurementAgentClient({
        apiBaseUrl: frontendConfig.apiBaseUrl,
        userId: frontendConfig.userId,
      }),
    [],
  );
  const controllerRef = useRef(new AgentRunController(client));
  const initialThreadIdRef = useRef(state.threadId);

  const restore = useCallback(
    async (threadId: string) => {
      setRestoring(true);
      try {
        const snapshot = await client.loadSnapshot(threadId);
        setState(
          snapshot === null
            ? createInitialViewState(threadId)
            : restoreSnapshot(threadId, snapshot),
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : "会话恢复失败";
        setState((previous) => ({ ...previous, running: false, error: message }));
      } finally {
        setRestoring(false);
      }
    },
    [client],
  );

  useEffect(() => {
    // 首次挂载时从服务端恢复快照。状态更新都发生在网络请求完成后的回调中，
    // 不会在 Effect 执行当下额外触发一次同步渲染。
    const threadId = initialThreadIdRef.current;
    const abortController = new AbortController();
    let active = true;

    void client
      .loadSnapshot(threadId, abortController.signal)
      .then((snapshot) => {
        if (active) {
          setState(
            snapshot === null
              ? createInitialViewState(threadId)
              : restoreSnapshot(threadId, snapshot),
          );
        }
      })
      .catch((error: unknown) => {
        if (active) {
          const message = error instanceof Error ? error.message : "会话恢复失败";
          setState((previous) => ({ ...previous, running: false, error: message }));
        }
      })
      .finally(() => {
        if (active) {
          setRestoring(false);
        }
      });

    return () => {
      active = false;
      abortController.abort();
    };
  }, [client]);

  useEffect(() => {
    if (!state.pendingNavigation || state.running) {
      return;
    }
    try {
      navigateTo(state.pendingNavigation);
      // 页面跳转属于浏览器副作用；跳转完成后必须消费掉一次性指令，避免后续渲染
      // 重复跳转。这个受条件保护的状态更新正是该 Effect 的完成动作。
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setState((previous) => ({ ...previous, pendingNavigation: null }));
    } catch (error) {
      const message = error instanceof Error ? error.message : "页面跳转失败";
      setState((previous) => ({ ...previous, pendingNavigation: null, error: message }));
    }
  }, [state.pendingNavigation, state.running]);

  const execute = useCallback(
    async (text: string | undefined, procurementInput: ProcurementInput | undefined) => {
      try {
        // controller 负责发送一次 Run。第二个回调在请求开始时更新“处理中”状态；第三个
        // 回调会被每一条 SSE 事件调用，并通过 reducer 把事件合并到当前页面状态。
        const traceId = await controllerRef.current.run(
          {
            threadId: state.threadId,
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
                ? {
                    id: messageId,
                    role: "user",
                    content: text,
                    streaming: false,
                  }
                : undefined;
            setState((previous) => beginRunState(previous, runId, userMessage));
          },
          // 使用 previous 而不是直接读取外层 state，是因为 SSE 事件可能连续到达；React
          // 会保证每一条事件都基于上一条已经合并后的最新状态继续更新。
          (event) => setState((previous) => reduceAGUIEvent(previous, event)),
        );
        setState((previous) => ({ ...previous, traceId, running: false }));
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          setState((previous) => ({ ...previous, running: false, error: "本次请求已取消" }));
          return;
        }
        const message = error instanceof Error ? error.message : "请求失败";
        const traceId = error instanceof AgentHttpError ? error.traceId : null;
        setState((previous) => ({ ...previous, running: false, error: message, traceId }));
        if (error instanceof AgentHttpError && error.snapshotUrl) {
          await restore(state.threadId);
        }
      }
    },
    [restore, state.threadId],
  );

  const value = useMemo<SessionContextValue>(
    () => ({
      state,
      restoring,
      sendText: async (text) => execute(text, undefined),
      triggerScenario: async (scenarioId) =>
        execute(undefined, { type: "scenario_trigger", scenarioId }),
      submitForm: async (actionId, values) =>
        execute(undefined, { type: "form_submit", actionId, values }),
      submitAction: async (actionId) => execute(undefined, { type: "action", actionId, data: {} }),
      newSession: () => {
        controllerRef.current.cancel();
        const threadId = newThreadId();
        sessionStorage.setItem(THREAD_STORAGE_KEY, threadId);
        setState(createInitialViewState(threadId));
        setRestoring(false);
      },
    }),
    [execute, restoring, state],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
