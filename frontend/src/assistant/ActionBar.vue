<script setup lang="ts">
import type { ActionsEventValue } from "../schemas/procurementEvents";

defineProps<{
  payload: ActionsEventValue["payload"];
  disabled: boolean;
}>();

const emit = defineEmits<{
  action: [actionId: string];
}>();
</script>

<template>
  <a-card :title="payload.title" class="assistant-block">
    <div class="button-row">
      <a-button
        v-for="action in payload.actions"
        :key="action.actionId"
        :type="action.style === 'primary' ? 'primary' : 'default'"
        :danger="action.style === 'danger'"
        :disabled="disabled"
        :loading="disabled"
        @click="emit('action', action.actionId)"
      >
        {{ action.label }}
      </a-button>
    </div>
  </a-card>
</template>
