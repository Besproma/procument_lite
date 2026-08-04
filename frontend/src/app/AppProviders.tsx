import { App as AntApp, ConfigProvider } from "antd";
import type { ReactNode } from "react";

import { SessionProvider } from "../assistant/SessionProvider";
import { ErrorBoundary } from "./ErrorBoundary";

/** 集中装配主题、错误边界和会话，不在业务组件中重复 Provider。 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: "#5277c3",
          colorInfo: "#5277c3",
          borderRadius: 10,
          colorBgLayout: "#f4f7fb",
          fontFamily:
            'Inter, "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, sans-serif',
        },
      }}
    >
      <AntApp>
        <ErrorBoundary>
          <SessionProvider>{children}</SessionProvider>
        </ErrorBoundary>
      </AntApp>
    </ConfigProvider>
  );
}
