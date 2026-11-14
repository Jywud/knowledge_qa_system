# 侧边栏 DeepSeek 布局改造设计

日期：2026-11-14　|　状态：已批准

## 背景与目标

对话页侧边栏当前为「对话记录 + 新建小按钮」的扁平列表。参考 DeepSeek 的侧边栏布局重构，并支持折叠。

## 范围

纯前端改动，后端零改动。涉及文件：

- `frontend/src/components/AppSidebar.vue` — 布局重构
- `frontend/src/components/AppLayout.vue` — 折叠后的展开按钮、aside 显隐
- `frontend/src/store.js` — 折叠状态

## 设计

### 布局（对齐 DeepSeek）

- 顶部一行：品牌标识（mark 图标 + 系统名，14px）+ 右侧折叠按钮
- 「开启新对话」全宽圆角主按钮，替代原「对话记录 + 新建」头部
- 会话按 `created_at` 本地时间分 4 组：今天 / 昨天 / 近 7 天 / 更早；组标题小字灰色；组内沿用接口现有 `id desc` 排序；空组不显示
- 条目保留知识库标签（弱化为小字灰色）；悬停显示删除按钮；当前会话高亮；空状态「暂无会话」沿用

### 折叠（已确认：完全隐藏）

- `sidebarCollapsed` ref 放 `store.js`，持久化到 `localStorage`（key `kqa_sidebar_collapsed`），刷新不丢
- 展开时：侧边栏右上角按钮触发折叠
- 折叠后：侧边栏整体隐藏（`el-aside` 不渲染），聊天区占满；顶栏左侧（`header-left`，chat 页原本为空）出现展开按钮

### 明确不做

搜索框、置顶（涉及后端加列，已确认不做）、后端改动、非 chat 页布局调整。

## 边界情况

- `created_at` 解析失败（NaN）归入「更早」
- 分组边界以浏览器本地时间 0 点计算
- 折叠状态属 UI 偏好，登出不清除

## 验证

1. `npm run build` 通过
2. dev 起前后端人工核对：分组正确（含跨天边界）、折叠/展开、新建/删除/切换会话、刷新后折叠状态保留
