import { createContext, useContext } from "react";

import type { AssistantViewState } from "../agui/eventReducer";

/**
 * 页面组件可以使用的会话操作。
 *
 * Context 只暴露界面状态和用户动作，不暴露 AgentClient、请求控制器等实现细节，
 * 因而展示组件不需要知道 AG-UI 请求是如何发送和恢复的。
 */
export interface SessionContextValue {
  state: AssistantViewState;
  restoring: boolean;
  sendText: (text: string) => Promise<void>;
  triggerScenario: (scenarioId: "smart_routing" | "knowledge_recommendation") => Promise<void>;
  submitForm: (actionId: string, values: Record<string, unknown>) => Promise<void>;
  submitAction: (actionId: string) => Promise<void>;
  newSession: () => void;
}

export const SessionContext = createContext<SessionContextValue | null>(null);

/** 获取离当前组件最近的采购助手会话；在 Provider 外误用时立即给出明确错误。 */
export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession 必须在 SessionProvider 内使用");
  }
  return context;
}
