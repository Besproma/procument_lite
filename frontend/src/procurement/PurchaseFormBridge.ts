import type { ProductView } from "../schemas/procurementEvents";

export type PurchasableProduct = ProductView;

export interface AddProductResult {
  success: boolean;
  message: string;
}

/**
 * 申购单边界。商品卡只认识此接口，不知道当前是本地 Demo 还是公司宿主页面。
 */
export interface PurchaseFormBridge {
  addProduct(product: PurchasableProduct): Promise<AddProductResult>;
}
