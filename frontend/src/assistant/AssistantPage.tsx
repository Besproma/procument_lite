import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Input,
  Layout,
  List,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import { frontendConfig } from "../config/env";
import { HostPurchaseFormBridge } from "../procurement/HostPurchaseFormBridge";
import { LocalPurchaseFormBridge } from "../procurement/LocalPurchaseFormBridge";
import { ProductList } from "../procurement/ProductList";
import type { PurchasableProduct, PurchaseFormBridge } from "../procurement/PurchaseFormBridge";
import { QueueNotice } from "../procurement/QueueNotice";
import { ActionBar } from "./ActionBar";
import { AgentStreamBlock } from "./AgentStreamBlock";
import { DynamicForm } from "./DynamicForm";
import { MessageList } from "./MessageList";
import { OptionSelector } from "./OptionSelector";
import { SceneEntrances } from "./SceneEntrances";
import { useSession } from "./sessionContext";

const { Header, Content, Sider } = Layout;
const { TextArea } = Input;

function isSceneActive(status: string | undefined): boolean {
  return status === "running" || status === "waiting";
}

/** 页面只组合已经过协议校验的展示组件，不实现任何采购判断。 */
export function AssistantPage() {
  const { state, restoring, sendText, triggerScenario, submitForm, submitAction, newSession } =
    useSession();
  const [draft, setDraft] = useState("");
  const [cart, setCart] = useState<PurchasableProduct[]>([]);
  const bridge = useMemo<PurchaseFormBridge>(
    () =>
      frontendConfig.purchaseFormMode === "local"
        ? new LocalPurchaseFormBridge()
        : new HostPurchaseFormBridge(),
    [],
  );
  const sceneActive = isSceneActive(state.scene?.status);

  const submitText = () => {
    const text = draft;
    if (!text.trim() || state.running) {
      return;
    }
    setDraft("");
    void sendText(text);
  };

  const addToVisibleCart = (product: PurchasableProduct) => {
    setCart((previous) => [
      ...previous.filter((item) => item.productId !== product.productId),
      product,
    ]);
  };

  return (
    <Layout className="app-shell">
      <Header className="app-header">
        <Space className="header-content" align="center">
          <div>
            <Typography.Title level={3} className="app-title">
              采购智能助手
            </Typography.Title>
            <Typography.Text className="app-subtitle">商品推荐、采购模式与知识查询</Typography.Text>
          </div>
          <Space>
            {state.scene && <Tag color="blue">{state.scene.scenarioId}</Tag>}
            <Button onClick={newSession} disabled={state.running}>
              新会话
            </Button>
          </Space>
        </Space>
      </Header>

      <Layout>
        <Content className="assistant-content">
          <Spin spinning={restoring} tip="正在恢复会话…">
            {!sceneActive && !state.running && (
              <SceneEntrances
                disabled={state.running}
                onTrigger={(scenarioId) => void triggerScenario(scenarioId)}
              />
            )}

            {state.error && (
              <Alert className="assistant-block" type="error" showIcon message={state.error} />
            )}
            {state.protocolError && (
              <Alert
                className="assistant-block"
                type="warning"
                showIcon
                message={state.protocolError}
              />
            )}
            {state.status && (
              <Alert className="assistant-block" type="info" showIcon message={state.status.text} />
            )}

            <Card className="assistant-block conversation-card">
              <MessageList messages={state.messages} />
              <Divider />
              <Space.Compact block>
                <TextArea
                  value={draft}
                  disabled={state.running || restoring}
                  placeholder={
                    sceneActive
                      ? "可输入新需求；如识别为其他场景，系统会先向你确认切换"
                      : "例如：我需要购买研发笔记本，用于办公，预算 10000 元，请推荐商品和采购模式"
                  }
                  autoSize={{ minRows: 2, maxRows: 6 }}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      submitText();
                    }
                  }}
                />
                <Button type="primary" loading={state.running} onClick={submitText}>
                  发送
                </Button>
              </Space.Compact>
            </Card>

            <AgentStreamBlock events={state.agentStreams} />
            {state.form && (
              <DynamicForm
                key={state.form.actionId}
                payload={state.form}
                disabled={state.running}
                onSubmit={(actionId, values) => void submitForm(actionId, values)}
              />
            )}
            {state.options && (
              <OptionSelector
                key={state.options.actionId}
                payload={state.options}
                disabled={state.running}
                onSelect={(actionId, optionId) => void submitForm(actionId, { optionId })}
              />
            )}
            {state.products && (
              <ProductList
                payload={state.products}
                bridge={bridge}
                onProductAdded={addToVisibleCart}
              />
            )}
            {state.queue && <QueueNotice payload={state.queue} />}
            {state.actions && (
              <ActionBar
                key={state.actions.groupId}
                payload={state.actions}
                disabled={state.running}
                onAction={(actionId) => void submitAction(actionId)}
              />
            )}

            {state.traceId && (
              <Typography.Paragraph type="secondary" className="trace-id">
                本次调用 trace_id：{state.traceId}
              </Typography.Paragraph>
            )}
          </Spin>
        </Content>

        <Sider width={300} theme="light" className="purchase-sider">
          <Card
            title={
              <Space>
                本地申购单
                <Badge count={cart.length} showZero color="#5277c3" />
              </Space>
            }
          >
            {frontendConfig.purchaseFormMode === "host" ? (
              <Alert type="warning" message="当前使用宿主申购单模式" />
            ) : cart.length === 0 ? (
              <Typography.Text type="secondary">点击商品“加购”后会显示在这里</Typography.Text>
            ) : (
              <List
                size="small"
                dataSource={cart}
                renderItem={(product) => (
                  <List.Item key={product.productId}>{product.name}</List.Item>
                )}
              />
            )}
          </Card>
        </Sider>
      </Layout>
    </Layout>
  );
}
