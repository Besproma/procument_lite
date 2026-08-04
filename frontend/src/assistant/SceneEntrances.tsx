import { Button, Card, Space, Typography } from "antd";

interface SceneEntrancesProps {
  disabled: boolean;
  onTrigger: (scenarioId: "smart_routing" | "knowledge_recommendation") => void;
}

/** 只在没有活动 DAG 时显示两个准确场景入口。 */
export function SceneEntrances({ disabled, onTrigger }: SceneEntrancesProps) {
  return (
    <Card className="scene-entrances">
      <Typography.Title level={4}>选择一个场景开始</Typography.Title>
      <Space wrap>
        <Button type="primary" disabled={disabled} onClick={() => onTrigger("smart_routing")}>
          智能分流
        </Button>
        <Button disabled={disabled} onClick={() => onTrigger("knowledge_recommendation")}>
          知识推荐
        </Button>
      </Space>
    </Card>
  );
}
