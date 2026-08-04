import { AssistantPage } from "../assistant/AssistantPage";

/** 顶层组件只组合页面，不解析协议或处理采购业务。 */
export function App() {
  return <AssistantPage />;
}
