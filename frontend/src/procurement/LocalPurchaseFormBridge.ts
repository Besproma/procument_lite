import type {
  AddProductResult,
  PurchasableProduct,
  PurchaseFormBridge,
} from "./PurchaseFormBridge";

/** 本地 Demo 申购单；数据只存在当前浏览器页面，不向 Agent 后端发请求。 */
export class LocalPurchaseFormBridge implements PurchaseFormBridge {
  private readonly products = new Map<string, PurchasableProduct>();

  addProduct(product: PurchasableProduct): Promise<AddProductResult> {
    this.products.set(product.productId, product);
    return Promise.resolve({
      success: true,
      message: `已将“${product.name}”加入本地申购单`,
    });
  }

  listProducts(): PurchasableProduct[] {
    return [...this.products.values()];
  }
}
