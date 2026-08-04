import { Button, Card, Image, List, message, Space, Tag, Typography } from "antd";
import { useState } from "react";

import type { ProductView, ProductsEventValue } from "../schemas/procurementEvents";
import type { PurchaseFormBridge } from "./PurchaseFormBridge";

interface ProductListProps {
  payload: ProductsEventValue["payload"];
  bridge: PurchaseFormBridge;
  onProductAdded: (product: ProductView) => void;
}

/** 展示搜索服务已经排序的商品；组件不重排，也不向 Agent 提交“加购”。 */
export function ProductList({ payload, bridge, onProductAdded }: ProductListProps) {
  const [addingProductId, setAddingProductId] = useState<string | null>(null);
  const [messageApi, messageContext] = message.useMessage();

  const addProduct = async (product: ProductView) => {
    setAddingProductId(product.productId);
    try {
      const result = await bridge.addProduct(product);
      if (result.success) {
        onProductAdded(product);
        void messageApi.success(result.message);
      } else {
        void messageApi.error(result.message);
      }
    } catch {
      void messageApi.error("加购失败，商品和推荐操作均已保留，请重试");
    } finally {
      setAddingProductId(null);
    }
  };

  return (
    <section aria-label="推荐商品" className="assistant-block">
      {messageContext}
      <Space align="baseline">
        <Typography.Title level={4}>{payload.title}</Typography.Title>
        <Typography.Text type="secondary">第 {payload.page} 批</Typography.Text>
      </Space>
      <List
        grid={{ gutter: 16, column: 3 }}
        dataSource={payload.products}
        renderItem={(product) => (
          <List.Item key={product.productId}>
            <Card
              className="product-card"
              cover={
                product.imageUrl ? (
                  <Image src={product.imageUrl} alt={product.name} height={160} preview={false} />
                ) : (
                  <div className="product-placeholder" aria-hidden="true">
                    商品图片
                  </div>
                )
              }
              actions={[
                <Button
                  key="add"
                  type="primary"
                  loading={addingProductId === product.productId}
                  onClick={() => void addProduct(product)}
                >
                  加购
                </Button>,
              ]}
            >
              <Card.Meta
                title={product.name}
                description={
                  <Space direction="vertical" size={6}>
                    <Typography.Text strong>
                      {product.price === null
                        ? "价格待确认"
                        : `${product.currency ?? ""} ${product.price.toLocaleString()}`}
                    </Typography.Text>
                    {product.deliveryText && (
                      <Typography.Text type="secondary">{product.deliveryText}</Typography.Text>
                    )}
                    <Space size={[4, 4]} wrap>
                      {product.badges.map((badge) => (
                        <Tag key={badge}>{badge}</Tag>
                      ))}
                    </Space>
                  </Space>
                }
              />
            </Card>
          </List.Item>
        )}
      />
    </section>
  );
}
