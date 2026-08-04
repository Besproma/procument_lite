import "antd/dist/reset.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { AppProviders } from "./app/AppProviders";
import "./styles.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("页面缺少 #root 容器");
}

createRoot(rootElement).render(
  <StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </StrictMode>,
);
