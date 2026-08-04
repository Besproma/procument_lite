/** 前端唯一读取 Vite 环境变量的位置。 */

export interface FrontendConfig {
  apiBaseUrl: string;
  userId: string;
  regionCode: string | null;
  purchaseFormMode: "local" | "host";
}

function withoutTrailingSlash(value: string): string {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

/**
 * 生成经过校验的公开配置。
 *
 * Vite 的 VITE_* 值会进入浏览器静态文件，所以这里永远不能读取 API Key、数据库 DSN
 * 或外围凭据。生产宿主应显式传 userId；默认值只服务于本地 Demo。
 */
export function loadFrontendConfig(): FrontendConfig {
  const userId = import.meta.env.VITE_USER_ID ?? "demo_user";
  if (!/^[A-Za-z0-9_.:@-]{1,128}$/.test(userId)) {
    throw new Error("VITE_USER_ID 格式不合法");
  }
  const mode = import.meta.env.VITE_PURCHASE_FORM_MODE ?? "local";
  if (mode !== "local" && mode !== "host") {
    throw new Error("VITE_PURCHASE_FORM_MODE 只允许 local 或 host");
  }
  return {
    apiBaseUrl: withoutTrailingSlash(import.meta.env.VITE_API_BASE_URL ?? ""),
    userId,
    regionCode: import.meta.env.VITE_REGION_CODE ?? "CN-SH",
    purchaseFormMode: mode,
  };
}

export const frontendConfig = loadFrontendConfig();
