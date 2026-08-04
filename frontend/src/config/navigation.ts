/** 后端固定目标到部署 URL 的唯一映射。 */

export type NavigationTarget = "ioi_purchase" | "self_purchase" | "custom_purchase";

const navigationUrls: Record<NavigationTarget, string> = {
  ioi_purchase: import.meta.env.VITE_IOI_PURCHASE_URL ?? "#ioi-purchase",
  self_purchase: import.meta.env.VITE_SELF_PURCHASE_URL ?? "#self-purchase",
  custom_purchase: import.meta.env.VITE_CUSTOM_PURCHASE_URL ?? "#custom-purchase",
};

/**
 * 只跳转代码枚举中的目标，事件 payload 永远不能直接成为 window.location。
 */
export function navigateTo(target: NavigationTarget): void {
  const configuredUrl = navigationUrls[target];
  if (!configuredUrl) {
    throw new Error(`导航目标 ${target} 未配置`);
  }
  window.location.assign(configuredUrl);
}
