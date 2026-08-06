<script setup lang="ts">
import type { AgentStreamEventValue } from "../schemas/procurementEvents";

defineProps<{
  events: AgentStreamEventValue["payload"][];
}>();
</script>

<template>
  <a-card
    v-if="events.length > 0"
    size="small"
    title="处理进度"
    class="assistant-block"
    aria-live="polite"
  >
    <a-timeline>
      <a-timeline-item
        v-for="event in events"
        :key="`${event.callId}_${event.attempt}_${event.streamSequence}`"
      >
        {{ event.content }}
      </a-timeline-item>
    </a-timeline>
  </a-card>
</template>
