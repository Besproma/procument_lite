import eslint from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import vue from "eslint-plugin-vue";

/**
 * Vue 前端的静态检查配置。
 *
 * Vue 单文件组件由 eslint-plugin-vue 解析，普通 TypeScript 文件继续使用
 * typescript-eslint。这里不再加载 React Hooks 规则，因为页面状态由 Vue
 * Composition API 管理。
 */
export default tseslint.config(
  { ignores: ["dist", "node_modules", "*.tsbuildinfo"] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs["flat/recommended"],
  {
    files: ["**/*.{ts,vue}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        parser: tseslint.parser,
        project: ["./tsconfig.app.json", "./tsconfig.node.json"],
        tsconfigRootDir: import.meta.dirname,
        extraFileExtensions: [".vue"],
      },
    },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "vue/multi-word-component-names": "off",
      "vue/no-v-html": "error",
      // 模板排版由 Prettier 统一，避免 ESLint 与格式化工具互相改写。
      "vue/max-attributes-per-line": "off",
      "vue/singleline-html-element-content-newline": "off",
      "vue/html-self-closing": "off",
    },
  },
  {
    // 配置文件本身是 JavaScript，不需要 TypeScript 类型信息。
    files: ["**/*.{js,mjs,cjs}"],
    ...tseslint.configs.disableTypeChecked,
  },
);
