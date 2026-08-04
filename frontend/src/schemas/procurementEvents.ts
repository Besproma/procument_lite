import { z } from "zod";

const envelope = <T extends z.ZodType>(payload: T) =>
  z
    .object({
      schema: z.literal("procurement-ui-v1"),
      threadId: z.string(),
      runId: z.string(),
      eventId: z.string(),
      sequence: z.number().int().positive(),
      payload,
    })
    .strict();

const scenePayload = z
  .object({
    // 场景 ID 已由后端静态 Catalog 校验；页面对生命周期做通用展示，因此新增 DAG
    // 不应迫使这一事件协议同步增加枚举值。具体入口按钮仍使用显式联合类型。
    scenarioId: z.string().min(1),
    status: z.enum(["running", "waiting", "completed", "aborted", "expired"]),
    reason: z.string().nullable(),
  })
  .strict();
const statusPayload = z.object({ code: z.string(), text: z.string() }).strict();
const optionPayload = z
  .object({
    title: z.string(),
    actionId: z.string(),
    multiple: z.literal(false),
    options: z.array(
      z
        .object({
          optionId: z.string(),
          label: z.string(),
          description: z.string().nullable(),
        })
        .strict(),
    ),
  })
  .strict();
const selectOption = z.object({ value: z.string(), label: z.string() }).strict();
const formField = z
  .object({
    fieldId: z.string(),
    label: z.string(),
    type: z.enum(["text", "number", "select"]),
    required: z.boolean(),
    options: z.array(selectOption),
    min: z.number().nullable(),
    max: z.number().nullable(),
    minLength: z.number().int().nonnegative().nullable(),
    maxLength: z.number().int().positive().nullable(),
  })
  .strict();
const formPayload = z
  .object({
    title: z.string(),
    actionId: z.string(),
    fields: z.array(formField).min(1),
    submitLabel: z.string(),
  })
  .strict();
const product = z
  .object({
    productId: z.string(),
    name: z.string(),
    price: z.number().nonnegative().nullable(),
    currency: z.string().nullable(),
    imageUrl: z.string().nullable(),
    deliveryText: z.string().nullable(),
    badges: z.array(z.string()),
    metadata: z.record(z.string(), z.unknown()),
  })
  .strict();
const productsPayload = z
  .object({
    title: z.string(),
    page: z.number().int().positive(),
    pageSize: z.number().int().positive(),
    hasNext: z.boolean(),
    products: z.array(product),
  })
  .strict();
const action = z
  .object({
    actionId: z.string(),
    kind: z.enum([
      "next_page",
      "append_product",
      "other_procurement_mode",
      "end_recommendation",
      "go_self_purchase",
      "go_custom_purchase",
      "retry",
      "confirm_scene_switch",
      "cancel_scene_switch",
    ]),
    label: z.string(),
    style: z.enum(["primary", "default", "danger"]),
  })
  .strict();
const actionsPayload = z
  .object({ title: z.string(), groupId: z.string(), actions: z.array(action).min(1) })
  .strict();
const queuePayload = z.object({ count: z.number().int().positive(), text: z.string() }).strict();
const navigationPayload = z
  .object({
    target: z.enum(["ioi_purchase", "self_purchase", "custom_purchase"]),
    params: z.record(z.string(), z.string()),
  })
  .strict();
const retryPayload = z
  .object({ actionId: z.string(), errorCode: z.string(), message: z.string(), label: z.string() })
  .strict();
const agentStreamPayload = z
  .object({
    callId: z.string(),
    delegateId: z.string(),
    attempt: z.number().int().positive(),
    streamSequence: z.number().int().positive(),
    kind: z.enum(["progress", "text_delta", "status"]),
    content: z.string(),
  })
  .strict();

export const procurementEventSchemas = {
  "procurement.scene": envelope(scenePayload),
  "procurement.status": envelope(statusPayload),
  "procurement.options": envelope(optionPayload),
  "procurement.form": envelope(formPayload),
  "procurement.products": envelope(productsPayload),
  "procurement.actions": envelope(actionsPayload),
  "procurement.queue": envelope(queuePayload),
  "procurement.navigation": envelope(navigationPayload),
  "procurement.retry": envelope(retryPayload),
  "procurement.agent_stream": envelope(agentStreamPayload),
} as const;

export type ProcurementEventName = keyof typeof procurementEventSchemas;
export type SceneEventValue = z.infer<(typeof procurementEventSchemas)["procurement.scene"]>;
export type StatusEventValue = z.infer<(typeof procurementEventSchemas)["procurement.status"]>;
export type OptionsEventValue = z.infer<(typeof procurementEventSchemas)["procurement.options"]>;
export type FormEventValue = z.infer<(typeof procurementEventSchemas)["procurement.form"]>;
export type ProductsEventValue = z.infer<(typeof procurementEventSchemas)["procurement.products"]>;
export type ActionsEventValue = z.infer<(typeof procurementEventSchemas)["procurement.actions"]>;
export type QueueEventValue = z.infer<(typeof procurementEventSchemas)["procurement.queue"]>;
export type NavigationEventValue = z.infer<
  (typeof procurementEventSchemas)["procurement.navigation"]
>;
export type RetryEventValue = z.infer<(typeof procurementEventSchemas)["procurement.retry"]>;
export type AgentStreamEventValue = z.infer<
  (typeof procurementEventSchemas)["procurement.agent_stream"]
>;
export type ProductView = z.infer<typeof product>;
export type ActionView = z.infer<typeof action>;
export type FormField = z.infer<typeof formField>;

export type ParsedProcurementEvent = {
  [Name in ProcurementEventName]: {
    name: Name;
    value: z.infer<(typeof procurementEventSchemas)[Name]>;
  };
}[ProcurementEventName];

/** 按固定事件名选择 Zod Schema；未知名称绝不进入组件。 */
export function parseProcurementEvent(name: string, value: unknown): ParsedProcurementEvent {
  if (!(name in procurementEventSchemas)) {
    throw new Error(`不支持的采购事件：${name}`);
  }
  const eventName = name as ProcurementEventName;
  const parsed = procurementEventSchemas[eventName].parse(value);
  return { name: eventName, value: parsed } as ParsedProcurementEvent;
}
