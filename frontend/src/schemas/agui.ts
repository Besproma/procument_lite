import { z } from "zod";

const runStartedSchema = z
  .object({ type: z.literal("RUN_STARTED"), threadId: z.string(), runId: z.string() })
  .strict();
const runFinishedSchema = z
  .object({ type: z.literal("RUN_FINISHED"), threadId: z.string(), runId: z.string() })
  .strict();
const runErrorSchema = z
  .object({ type: z.literal("RUN_ERROR"), code: z.string(), message: z.string() })
  .strict();
const textStartSchema = z
  .object({
    type: z.literal("TEXT_MESSAGE_START"),
    messageId: z.string(),
    role: z.literal("assistant"),
  })
  .strict();
const textContentSchema = z
  .object({
    type: z.literal("TEXT_MESSAGE_CONTENT"),
    messageId: z.string(),
    delta: z.string(),
  })
  .strict();
const textEndSchema = z
  .object({ type: z.literal("TEXT_MESSAGE_END"), messageId: z.string() })
  .strict();
const customSchema = z
  .object({ type: z.literal("CUSTOM"), name: z.string(), value: z.unknown() })
  .strict();

export const aguiEventSchema = z.discriminatedUnion("type", [
  runStartedSchema,
  runFinishedSchema,
  runErrorSchema,
  textStartSchema,
  textContentSchema,
  textEndSchema,
  customSchema,
]);

export type AGUIEvent = z.infer<typeof aguiEventSchema>;

export const httpErrorSchema = z
  .object({
    code: z.string(),
    message: z.string(),
    traceId: z.string(),
    snapshotUrl: z.string().optional(),
    details: z.record(z.string(), z.string()).default({}),
  })
  .strict();

export type AgentHttpErrorBody = z.infer<typeof httpErrorSchema>;
