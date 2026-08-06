<script setup lang="ts">
import { reactive } from "vue";

import type { FormEventValue, FormField } from "../schemas/procurementEvents";

const props = defineProps<{
  payload: FormEventValue["payload"];
  disabled: boolean;
}>();

const emit = defineEmits<{
  submit: [actionId: string, values: Record<string, unknown>];
}>();

// 表单只保存用户在页面填写的值；服务端收到后仍会用自己的输入模型再次校验。
const values = reactive<Record<string, unknown>>({});
const errors = reactive<Record<string, string>>({});

function fieldValue(field: FormField): string | number | undefined {
  const value = values[field.fieldId];
  return typeof value === "string" || typeof value === "number" ? value : undefined;
}

function updateText(field: FormField, event: Event): void {
  values[field.fieldId] = (event.target as HTMLInputElement).value;
}

function updateNumber(field: FormField, event: Event): void {
  const rawValue = (event.target as HTMLInputElement).value;
  values[field.fieldId] = rawValue === "" ? undefined : Number(rawValue);
}

function updateSelect(field: FormField, event: Event): void {
  values[field.fieldId] = (event.target as HTMLSelectElement).value;
}

function validateField(field: FormField): string | null {
  const value = values[field.fieldId];
  if (field.required && (value === undefined || value === null || value === "")) {
    return `请填写${field.label}`;
  }
  if (typeof value === "string") {
    if (field.minLength !== null && value.length < field.minLength) {
      return `${field.label}至少需要 ${field.minLength} 个字符`;
    }
    if (field.maxLength !== null && value.length > field.maxLength) {
      return `${field.label}不能超过 ${field.maxLength} 个字符`;
    }
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return `${field.label}必须是有效数字`;
    }
    if (field.min !== null && value < field.min) {
      return `${field.label}不能小于 ${field.min}`;
    }
    if (field.max !== null && value > field.max) {
      return `${field.label}不能大于 ${field.max}`;
    }
  }
  return null;
}

function submitForm(): void {
  for (const field of props.payload.fields) {
    const error = validateField(field);
    if (error) {
      errors[field.fieldId] = error;
    } else {
      delete errors[field.fieldId];
    }
  }
  if (Object.keys(errors).length > 0) {
    return;
  }
  emit("submit", props.payload.actionId, { ...values });
}
</script>

<template>
  <a-card :title="payload.title" class="assistant-block">
    <form class="dynamic-form" @submit.prevent="submitForm">
      <div v-for="field in payload.fields" :key="field.fieldId" class="form-field">
        <label :for="`field-${field.fieldId}`">{{ field.label }}</label>

        <input
          v-if="field.type === 'text'"
          :id="`field-${field.fieldId}`"
          :value="fieldValue(field)"
          type="text"
          :maxlength="field.maxLength ?? undefined"
          :disabled="disabled"
          @input="updateText(field, $event)"
        />
        <input
          v-else-if="field.type === 'number'"
          :id="`field-${field.fieldId}`"
          :value="fieldValue(field)"
          type="number"
          :min="field.min ?? undefined"
          :max="field.max ?? undefined"
          :disabled="disabled"
          @input="updateNumber(field, $event)"
        />
        <select
          v-else
          :id="`field-${field.fieldId}`"
          :value="String(fieldValue(field) ?? '')"
          :disabled="disabled"
          @change="updateSelect(field, $event)"
        >
          <option value="" disabled>请选择</option>
          <option v-for="option in field.options" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>

        <span v-if="errors[field.fieldId]" class="field-error">{{ errors[field.fieldId] }}</span>
      </div>
      <a-button type="primary" html-type="submit" :loading="disabled">
        {{ payload.submitLabel }}
      </a-button>
    </form>
  </a-card>
</template>
