import { Button, Card, Form, Input, InputNumber, Select } from "antd";

import type { FormEventValue } from "../schemas/procurementEvents";

interface DynamicFormProps {
  payload: FormEventValue["payload"];
  disabled: boolean;
  onSubmit: (actionId: string, values: Record<string, unknown>) => void;
}

/** 仅把后端允许的 text、number、select 映射成固定 Ant Design 组件。 */
export function DynamicForm({ payload, disabled, onSubmit }: DynamicFormProps) {
  return (
    <Card title={payload.title} className="assistant-block">
      <Form
        layout="vertical"
        disabled={disabled}
        onFinish={(values: Record<string, unknown>) => onSubmit(payload.actionId, values)}
      >
        {payload.fields.map((field) => {
          const rules = [
            { required: field.required, message: `请填写${field.label}` },
            ...(field.minLength === null ? [] : [{ min: field.minLength }]),
            ...(field.maxLength === null ? [] : [{ max: field.maxLength }]),
          ];
          return (
            <Form.Item key={field.fieldId} name={field.fieldId} label={field.label} rules={rules}>
              {field.type === "text" ? (
                <Input maxLength={field.maxLength ?? undefined} />
              ) : field.type === "number" ? (
                <InputNumber
                  // 后端没有设置边界时，不向 Ant Design 传入该属性；这与显式传入
                  // undefined 不同，也能避免覆盖组件自身的默认行为。
                  {...(field.min === null ? {} : { min: field.min })}
                  {...(field.max === null ? {} : { max: field.max })}
                  className="full-width-input"
                />
              ) : (
                <Select options={field.options} />
              )}
            </Form.Item>
          );
        })}
        <Button type="primary" htmlType="submit" loading={disabled}>
          {payload.submitLabel}
        </Button>
      </Form>
    </Card>
  );
}
