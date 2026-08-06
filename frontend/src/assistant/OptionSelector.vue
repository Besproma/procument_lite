<script setup lang="ts">
import { ref } from "vue";

import type { OptionsEventValue } from "../schemas/procurementEvents";

defineProps<{
  payload: OptionsEventValue["payload"];
  disabled: boolean;
}>();

const emit = defineEmits<{
  select: [actionId: string, optionId: string];
}>();

const selected = ref<string | null>(null);
</script>

<template>
  <a-card :title="payload.title" class="assistant-block">
    <div class="option-list">
      <label v-for="option in payload.options" :key="option.optionId" class="option-item">
        <input v-model="selected" type="radio" :value="option.optionId" :disabled="disabled" />
        <span>
          <strong>{{ option.label }}</strong>
          <small v-if="option.description">{{ option.description }}</small>
        </span>
      </label>
    </div>
    <div class="block-actions">
      <a-button
        type="primary"
        :disabled="disabled || selected === null"
        :loading="disabled"
        @click="selected && emit('select', payload.actionId, selected)"
      >
        确认栏目
      </a-button>
    </div>
  </a-card>
</template>
