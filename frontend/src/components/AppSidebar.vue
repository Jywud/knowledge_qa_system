<script setup>
import { computed } from "vue";
import { useRouter } from "vue-router";
import { ElMessageBox } from "element-plus";
import { Delete, Fold, Plus } from "@element-plus/icons-vue";
import { api, conversations, currentConversationId, knowledgeBases, toggleSidebar, user } from "../store";

const router = useRouter();

const DAY_MS = 24 * 3600 * 1000;

// 按本地时间 0 点分桶：今天 / 昨天 / 近 7 天 / 更早，组内沿用接口的 id desc 排序。
const groups = computed(() => {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const buckets = [
    { label: "今天", items: [] },
    { label: "昨天", items: [] },
    { label: "近 7 天", items: [] },
    { label: "更早", items: [] },
  ];
  for (const conv of conversations.value) {
    const t = new Date(conv.created_at).getTime();
    if (!Number.isFinite(t)) buckets[3].items.push(conv);
    else if (t >= startOfToday) buckets[0].items.push(conv);
    else if (t >= startOfToday - DAY_MS) buckets[1].items.push(conv);
    else if (t >= startOfToday - 7 * DAY_MS) buckets[2].items.push(conv);
    else buckets[3].items.push(conv);
  }
  return buckets.filter((b) => b.items.length);
});

function goHome() {
  router.push("/home");
}

function newConversation() {
  currentConversationId.value = null;
  router.push("/chat");
}

function openConversation(id) {
  currentConversationId.value = id;
  router.push("/chat");
}

function kbName(kbId) {
  if (!kbId) return "全部";
  return knowledgeBases.value.find((kb) => kb.id === kbId)?.name ?? "未知库";
}

async function removeConversation(conv) {
  await ElMessageBox.confirm(`确定删除会话「${conv.title}」？`, "删除确认", { type: "warning" });
  await api.delete(`/conversations/${conv.id}`);
  conversations.value = conversations.value.filter((c) => c.id !== conv.id);
  if (currentConversationId.value === conv.id) currentConversationId.value = null;
}
</script>

<template>
  <div class="sidebar">
    <div class="brand-row">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="14" height="14" fill="none">
          <path d="M16 3.5 27 9.75v12.5L16 28.5 5 22.25V9.75L16 3.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
          <path d="M16 10.5v11M11 13.5l10 5M21 13.5l-10 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
        </svg>
      </span>
      <span class="brand-name" title="企业智能知识库系统 · 回到首页" @click="goHome">企业智能知识库系统</span>
      <button class="collapse-btn" title="收起侧边栏" @click="toggleSidebar">
        <el-icon :size="16"><Fold /></el-icon>
      </button>
    </div>

    <button class="new-chat" @click="newConversation">
      <el-icon><Plus /></el-icon>
      <span>开启新对话</span>
    </button>

    <el-scrollbar class="conv-scroll">
      <template v-for="group in groups" :key="group.label">
        <div class="group-label">{{ group.label }}</div>
        <div
          v-for="conv in group.items"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === currentConversationId }"
          @click="openConversation(conv.id)"
        >
          <span class="conv-name">{{ conv.title || "新对话" }}</span>
          <span class="conv-kb">{{ kbName(conv.kb_id) }}</span>
          <el-icon class="del-btn" @click.stop="removeConversation(conv)">
            <Delete />
          </el-icon>
        </div>
      </template>
      <el-empty v-if="!conversations.length" description="暂无会话" :image-size="60" />
    </el-scrollbar>
  </div>
</template>

<style scoped>
.sidebar {
  box-sizing: border-box;
  /* 固定 220px：折叠动画期间内容不被压缩，仅随 aside 收窄被裁切 */
  width: 220px;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 12px;
  border-right: 1px solid var(--color-border);
  background: rgba(255, 255, 255, 0.58);
  backdrop-filter: blur(18px);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0 10px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  color: #fff;
  background: var(--gradient-primary);
  flex-shrink: 0;
}

.brand-name {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.collapse-btn {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border: none;
  border-radius: var(--radius-md);
  background: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background 0.18s ease;
}

.collapse-btn:hover {
  background: var(--color-surface-muted);
}

.new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 10px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-muted);
  box-shadow: 0 1px 2px rgba(74, 66, 185, 0.05), 0 2px 8px rgba(74, 66, 185, 0.07);
  font: inherit;
  font-size: 14px;
  color: var(--color-text);
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.new-chat:hover {
  background: var(--color-primary-soft);
  border-color: var(--color-border-accent);
}

.conv-scroll {
  flex: 1;
  min-height: 0;
}

.group-label {
  padding: 10px 8px 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.conv-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 2px;
}

.conv-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-kb {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--color-text-muted);
  margin-left: 4px;
  max-width: 64px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.del-btn {
  visibility: hidden;
  flex-shrink: 0;
  color: var(--color-danger);
}

.conv-item:hover .del-btn {
  visibility: visible;
}

.conv-item:hover {
  background: var(--el-fill-color-light);
}

.conv-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
</style>
