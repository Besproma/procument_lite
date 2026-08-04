import { Empty, List, Typography } from "antd";

import type { DisplayMessage } from "../agui/eventReducer";

/** 助手文字始终按纯文本渲染，禁止 HTML 注入。 */
export function MessageList({ messages }: { messages: DisplayMessage[] }) {
  if (messages.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有消息" />;
  }
  return (
    <List
      className="message-list"
      dataSource={messages}
      renderItem={(message) => (
        <List.Item key={message.id} className={`message-row message-${message.role}`}>
          <div className="message-bubble" aria-live={message.streaming ? "polite" : "off"}>
            <Typography.Text>{message.content || "…"}</Typography.Text>
          </div>
        </List.Item>
      )}
    />
  );
}
