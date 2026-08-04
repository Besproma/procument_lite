import { Alert } from "antd";

import type { QueueEventValue } from "../schemas/procurementEvents";

/** 排队文案由后端固定生成，前端只按普通文本展示。 */
export function QueueNotice({ payload }: { payload: QueueEventValue["payload"] }) {
  return <Alert type="info" showIcon message={payload.text} className="assistant-block" />;
}
