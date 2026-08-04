import { Card, Timeline, Typography } from "antd";

import type { AgentStreamEventValue } from "../schemas/procurementEvents";

/** 只展示后端白名单过滤后的外围进度，不展示 hidden reasoning 或原始 chunk。 */
export function AgentStreamBlock({ events }: { events: AgentStreamEventValue["payload"][] }) {
  if (events.length === 0) {
    return null;
  }
  return (
    <Card size="small" title="处理进度" className="assistant-block" aria-live="polite">
      <Timeline
        items={events.map((event) => ({
          key: `${event.callId}_${event.attempt}_${event.streamSequence}`,
          children: <Typography.Text>{event.content}</Typography.Text>,
        }))}
      />
    </Card>
  );
}
