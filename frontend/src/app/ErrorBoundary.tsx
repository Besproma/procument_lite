import { Alert, Button, Result } from "antd";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryState {
  error: Error | null;
}

/** 捕获渲染异常，避免协议或组件错误把整个页面留成空白。 */
export class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 当前没有前端日志服务，只写浏览器诊断台；不得把错误通过 Agent 对话发送。
    console.error("采购助手渲染失败", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.error) {
      return this.props.children;
    }
    return (
      <Result
        status="error"
        title="页面暂时无法显示"
        subTitle="请刷新页面恢复最后一个服务端快照。"
        extra={<Button onClick={() => window.location.reload()}>刷新页面</Button>}
      >
        <Alert type="error" message="界面发生了未处理错误" />
      </Result>
    );
  }
}
