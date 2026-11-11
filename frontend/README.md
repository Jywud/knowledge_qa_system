# 知识库问答前端

Vue 3 + Vite + Element Plus。完整环境准备、后端启动和部署见[根 README](../README.md)。

在本目录运行：

```powershell
npm install
npm run dev
```

开发页为 `http://localhost:5173`，`/api` 代理到本地后端 `8000` 端口。代理用实际连接地址覆盖外部转发头，后端需通过 `run.py` 启动并仅信任明确代理。

```powershell
node --test tests/*.spec.js
npm run build
```

测试使用 Node 内置测试器，覆盖聊天错误恢复、引用按块加载、Markdown 引用角标、用户缓存清理和代理头覆盖，无需真实模型。构建产物为 `dist/`，不提交到 Git。

页面位于 `src/views/`，布局位于 `src/components/`，接口及全局状态位于 `src/store.js`。引用文本转换位于 `src/utils/markdown.js`，样式复用 `src/style.css` 的主题变量。引用弹窗默认宽 840px，窄屏保留两侧各 16px 边距；缺少精确定位信息的旧引用仅显示保存摘要。
