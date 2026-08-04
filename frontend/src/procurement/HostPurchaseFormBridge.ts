import type {
  AddProductResult,
  PurchasableProduct,
  PurchaseFormBridge,
} from "./PurchaseFormBridge";

/**
 * 公司既有申购单的接入边界。
 *
 * 宿主接口协议尚未提供，不能猜测 postMessage、全局函数或 HTTP 地址。生产选择 host
 * 模式时明确失败并保留商品卡，待协议确认后只替换本类映射。
 */
export class HostPurchaseFormBridge implements PurchaseFormBridge {
  addProduct(product: PurchasableProduct): Promise<AddProductResult> {
    // 参数当前不会被发送，但明确接收它可以确保后续接入宿主协议时无需改变公开接口。
    void product;
    return Promise.resolve({
      success: false,
      message: "公司申购单接口尚未配置，商品没有被加入",
    });
  }
}
