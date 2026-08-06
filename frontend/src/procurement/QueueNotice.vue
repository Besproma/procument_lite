<script setup lang="ts">
import type { QueueEventValue } from "../schemas/procurementEvents";

defineProps<{
  payload: QueueEventValue["payload"];
}>();
</script>

<template>
  <!-- 排队文本由后端固定生成，前端只按普通文本展示。 -->
  <a-alert type="info" show-icon :message="payload.text" class="assistant-block" />
</template>
