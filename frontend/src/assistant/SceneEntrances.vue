<script setup lang="ts">
defineProps<{
  disabled: boolean;
}>();

const emit = defineEmits<{
  trigger: [scenarioId: "smart_routing" | "knowledge_recommendation"];
}>();
</script>

<template>
  <a-card class="scene-entrances">
    <h2>选择一个场景开始</h2>
    <div class="button-row">
      <a-button type="primary" :disabled="disabled" @click="emit('trigger', 'smart_routing')">
        智能分流
      </a-button>
      <a-button :disabled="disabled" @click="emit('trigger', 'knowledge_recommendation')">
        知识推荐
      </a-button>
    </div>
  </a-card>
</template>
