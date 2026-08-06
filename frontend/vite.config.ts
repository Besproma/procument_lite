import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  // Vue 单文件组件由官方插件编译；协议适配层仍然是普通 TypeScript 文件。
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
});
