import { Button, Card, Space } from "antd";

import type { ActionsEventValue } from "../schemas/procurementEvents";

interface ActionBarProps {
  payload: ActionsEventValue["payload"];
  disabled: boolean;
  onAction: (actionId: string) => void;
}

/** 后端签发的一组一次性 Action；提交任一项时整组进入禁用状态。 */
export function ActionBar({ payload, disabled, onAction }: ActionBarProps) {
  return (
    <Card title={payload.title} className="assistant-block">
      <Space wrap>
        {payload.actions.map((action) => (
          <Button
            key={action.actionId}
            type={action.style === "primary" ? "primary" : "default"}
            danger={action.style === "danger"}
            disabled={disabled}
            loading={disabled}
            onClick={() => onAction(action.actionId)}
          >
            {action.label}
          </Button>
        ))}
      </Space>
    </Card>
  );
}
