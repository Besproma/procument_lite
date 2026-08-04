/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_USER_ID?: string;
  readonly VITE_REGION_CODE?: string;
  readonly VITE_IOI_PURCHASE_URL?: string;
  readonly VITE_SELF_PURCHASE_URL?: string;
  readonly VITE_CUSTOM_PURCHASE_URL?: string;
  readonly VITE_PURCHASE_FORM_MODE?: "local" | "host";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
