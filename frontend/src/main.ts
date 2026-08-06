import { createApp } from "vue";
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfigProvider,
  Divider,
  Input,
  Layout,
  List,
  Tag,
  Timeline,
} from "ant-design-vue";

import App from "./App.vue";
import "ant-design-vue/dist/reset.css";
import "./styles.css";

// Vue 应用只有一个启动入口。协议解析、会话状态和页面展示都由 App 继续向下组合。
const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("页面缺少 #root 容器");
}

// 只注册页面实际使用的组件，避免把整个组件库都打入浏览器产物。
// Layout、Input、List 和 Timeline 会同时注册各自的 Header、TextArea、Item 等子组件。
const app = createApp(App);
for (const component of [
  Alert,
  Badge,
  Button,
  Card,
  ConfigProvider,
  Divider,
  Input,
  Layout,
  List,
  Tag,
  Timeline,
]) {
  app.use(component);
}
app.mount(rootElement);
