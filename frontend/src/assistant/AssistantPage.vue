<script setup lang="ts">
import { computed, ref } from "vue";

import { frontendConfig } from "../config/env";
import { HostPurchaseFormBridge } from "../procurement/HostPurchaseFormBridge";
import { LocalPurchaseFormBridge } from "../procurement/LocalPurchaseFormBridge";
import type { ProductView } from "../schemas/procurementEvents";
import ProductList from "../procurement/ProductList.vue";
import type { PurchaseFormBridge } from "../procurement/PurchaseFormBridge";
import { useSession } from "./useSession";

import ActionBar from "./ActionBar.vue";
import AgentStreamBlock from "./AgentStreamBlock.vue";
import DynamicForm from "./DynamicForm.vue";
import MessageList from "./MessageList.vue";
import OptionSelector from "./OptionSelector.vue";
import SceneEntrances from "./SceneEntrances.vue";
import QueueNotice from "../procurement/QueueNotice.vue";

const {
  state,
  restoring,
  sceneActive,
  sendText,
  triggerScenario,
  submitForm,
  submitAction,
  newSession,
} = useSession();
const draft = ref("");
const cart = ref<ProductView[]>([]);

// 商品卡只依赖这个边界接口，不知道申购单是本地 Demo 还是公司宿主页面。
const bridge: PurchaseFormBridge =
  frontendConfig.purchaseFormMode === "local"
    ? new LocalPurchaseFormBridge()
    : new HostPurchaseFormBridge();

const inputPlaceholder = computed(() =>
  sceneActive.value
    ? "可输入新需求；如识别为其他场景，系统会先向你确认切换"
    : "例如：我需要购买研发笔记本，用于办公，预算 10000 元，请推荐商品和采购模式",
);

function submitText(): void {
  const text = draft.value.trim();
  if (!text || state.value.running || restoring.value) {
    return;
  }
  draft.value = "";
  void sendText(text);
}

function addToVisibleCart(product: ProductView): void {
  cart.value = [...cart.value.filter((item) => item.productId !== product.productId), product];
}
</script>

<template>
  <a-layout class="app-shell">
    <a-layout-header class="app-header">
      <div class="header-content">
        <div>
          <h1 class="app-title">采购智能助手</h1>
          <p class="app-subtitle">商品推荐、采购模式与知识查询</p>
        </div>
        <div class="header-actions">
          <a-tag v-if="state.scene" color="blue">
            {{ state.scene.scenarioId }}
          </a-tag>
          <a-button :disabled="state.running" @click="newSession"> 新会话 </a-button>
        </div>
      </div>
    </a-layout-header>

    <a-layout>
      <a-layout-content class="assistant-content">
        <div v-if="restoring" class="restore-state" role="status">正在恢复会话…</div>

        <SceneEntrances
          v-if="!sceneActive && !state.running"
          :disabled="state.running"
          @trigger="(scenarioId) => void triggerScenario(scenarioId)"
        />

        <a-alert
          v-if="state.error"
          class="assistant-block"
          type="error"
          show-icon
          :message="state.error"
        />
        <a-alert
          v-if="state.protocolError"
          class="assistant-block"
          type="warning"
          show-icon
          :message="state.protocolError"
        />
        <a-alert
          v-if="state.status"
          class="assistant-block"
          type="info"
          show-icon
          :message="state.status.text"
        />

        <a-card class="assistant-block conversation-card">
          <MessageList :messages="state.messages" />
          <a-divider />
          <div class="composer">
            <a-textarea
              v-model:value="draft"
              :disabled="state.running || restoring"
              :placeholder="inputPlaceholder"
              :auto-size="{ minRows: 2, maxRows: 6 }"
              aria-label="消息输入"
              @keydown.enter.exact.prevent="submitText"
            />
            <a-button type="primary" :loading="state.running" @click="submitText"> 发送 </a-button>
          </div>
        </a-card>

        <AgentStreamBlock :events="state.agentStreams" />
        <DynamicForm
          v-if="state.form"
          :key="state.form.actionId"
          :payload="state.form"
          :disabled="state.running"
          @submit="(actionId, values) => void submitForm(actionId, values)"
        />
        <OptionSelector
          v-if="state.options"
          :key="state.options.actionId"
          :payload="state.options"
          :disabled="state.running"
          @select="(actionId, optionId) => void submitForm(actionId, { optionId })"
        />
        <ProductList
          v-if="state.products"
          :payload="state.products"
          :bridge="bridge"
          @product-added="addToVisibleCart"
        />
        <QueueNotice v-if="state.queue" :payload="state.queue" />
        <ActionBar
          v-if="state.actions"
          :key="state.actions.groupId"
          :payload="state.actions"
          :disabled="state.running"
          @action="(actionId) => void submitAction(actionId)"
        />

        <p v-if="state.traceId" class="trace-id">本次调用 trace_id：{{ state.traceId }}</p>
      </a-layout-content>

      <a-layout-sider width="300" theme="light" class="purchase-sider">
        <a-card>
          <template #title>
            <span>本地申购单</span>
            <a-badge :count="cart.length" :show-zero="true" color="#5277c3" />
          </template>
          <a-alert
            v-if="frontendConfig.purchaseFormMode === 'host'"
            type="warning"
            message="当前使用宿主申购单模式"
          />
          <span v-else-if="cart.length === 0" class="secondary-text">
            点击商品“加购”后会显示在这里
          </span>
          <a-list v-else size="small" :data-source="cart" item-layout="horizontal">
            <template #renderItem="{ item }">
              <a-list-item>{{ item.name }}</a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-layout-sider>
    </a-layout>
  </a-layout>
</template>
