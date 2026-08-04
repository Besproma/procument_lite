import { Button, Card, Radio, Space, Typography } from "antd";
import { useState } from "react";

import type { OptionsEventValue } from "../schemas/procurementEvents";

interface OptionSelectorProps {
  payload: OptionsEventValue["payload"];
  disabled: boolean;
  onSelect: (actionId: string, optionId: string) => void;
}

/** 多栏目时只允许选择一个 optionId；名称不用于后端反查。 */
export function OptionSelector({ payload, disabled, onSelect }: OptionSelectorProps) {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <Card title={payload.title} className="assistant-block">
      <Radio.Group
        value={selected}
        disabled={disabled}
        onChange={(event) => setSelected(String(event.target.value))}
      >
        <Space direction="vertical">
          {payload.options.map((option) => (
            <Radio key={option.optionId} value={option.optionId}>
              <Space direction="vertical" size={0}>
                <Typography.Text>{option.label}</Typography.Text>
                {option.description && (
                  <Typography.Text type="secondary">{option.description}</Typography.Text>
                )}
              </Space>
            </Radio>
          ))}
        </Space>
      </Radio.Group>
      <div className="block-actions">
        <Button
          type="primary"
          disabled={disabled || selected === null}
          loading={disabled}
          onClick={() => selected && onSelect(payload.actionId, selected)}
        >
          确认栏目
        </Button>
      </div>
    </Card>
  );
}
