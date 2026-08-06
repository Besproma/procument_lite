<script setup lang="ts">
import { ref } from "vue";

import type { ProductView, ProductsEventValue } from "../schemas/procurementEvents";
import type { PurchaseFormBridge } from "./PurchaseFormBridge";

const props = defineProps<{
  payload: ProductsEventValue["payload"];
  bridge: PurchaseFormBridge;
}>();

const emit = defineEmits<{
  productAdded: [product: ProductView];
}>();

const addingProductId = ref<string | null>(null);
const notice = ref<{ type: "success" | "error"; text: string } | null>(null);

function formatPrice(product: ProductView): string {
  return product.price === null
    ? "价格待确认"
    : `${product.currency ?? ""} ${product.price.toLocaleString()}`.trim();
}

async function addProduct(product: ProductView): Promise<void> {
  addingProductId.value = product.productId;
  notice.value = null;
  try {
    const result = await props.bridge.addProduct(product);
    notice.value = { type: result.success ? "success" : "error", text: result.message };
    if (result.success) {
      emit("productAdded", product);
    }
  } catch {
    notice.value = { type: "error", text: "加购失败，商品和推荐操作均已保留，请重试" };
  } finally {
    addingProductId.value = null;
  }
}
</script>

<template>
  <section aria-label="推荐商品" class="assistant-block product-section">
    <div class="section-heading">
      <h2>{{ payload.title }}</h2>
      <span class="secondary-text">第 {{ payload.page }} 批</span>
    </div>
    <a-alert
      v-if="notice"
      class="product-notice"
      :type="notice.type"
      :message="notice.text"
      show-icon
    />
    <div class="product-grid">
      <article v-for="product in payload.products" :key="product.productId" class="product-card">
        <img v-if="product.imageUrl" :src="product.imageUrl" :alt="product.name" />
        <div v-else class="product-placeholder" aria-hidden="true">商品图片</div>
        <div class="product-body">
          <h3>{{ product.name }}</h3>
          <strong>{{ formatPrice(product) }}</strong>
          <span v-if="product.deliveryText" class="secondary-text">{{ product.deliveryText }}</span>
          <div class="tag-row">
            <a-tag v-for="badge in product.badges" :key="badge">
              {{ badge }}
            </a-tag>
          </div>
          <a-button
            type="primary"
            block
            :loading="addingProductId === product.productId"
            @click="void addProduct(product)"
          >
            加购
          </a-button>
        </div>
      </article>
    </div>
  </section>
</template>
