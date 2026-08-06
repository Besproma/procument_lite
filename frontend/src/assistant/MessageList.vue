<script setup lang="ts">
import type { DisplayMessage } from "../agui/eventReducer";

defineProps<{
  messages: DisplayMessage[];
}>();
</script>

<template>
  <div v-if="messages.length === 0" class="empty-state">还没有消息</div>
  <ul v-else class="message-list" aria-live="polite">
    <li
      v-for="message in messages"
      :key="message.id"
      class="message-row"
      :class="`message-${message.role}`"
    >
      <span class="message-bubble">{{ message.content || "…" }}</span>
    </li>
  </ul>
</template>
