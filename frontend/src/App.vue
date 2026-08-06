<script setup lang="ts">
import AssistantPage from "./assistant/AssistantPage.vue";

// 主题 token 集中放在顶层，业务组件不重复写主色、圆角和字体配置。
const theme = {
  token: {
    colorPrimary: "#5277c3",
    colorInfo: "#5277c3",
    borderRadius: 10,
    colorBgLayout: "#f4f7fb",
    fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
  },
};
</script>

<template>
  <!-- 顶层组件只负责装配主题和页面，不读取 AG-UI 事件，也不做采购判断。 -->
  <!-- 关闭中文双字按钮自动插入空格，保证按钮可访问名称与后端文案完全一致。 -->
  <a-config-provider :theme="theme" :auto-insert-space-in-button="false">
    <AssistantPage />
  </a-config-provider>
</template>
