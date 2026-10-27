<script setup>
import { useRouter } from "vue-router";
import { ElMessageBox } from "element-plus";
import { Delete, Plus } from "@element-plus/icons-vue";
import { api, conversations, currentConversationId, knowledgeBases, user } from "../store";

const router = useRouter();

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
    <div class="logo" title="回到首页" @click="goHome">企业知识库</div>

    <div v-if="user" class="conv-section">
      <div class="conv-header">
        <span class="conv-title">对话记录</span>
        <el-button size="small" type="primary" :icon="Plus" @click="newConversation">新建</el-button>
      </div>
      <el-scrollbar class="conv-scroll">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === currentConversationId }"
          @click="openConversation(conv.id)"
        >
            <span class="conv-name">{{ conv.title }}</span>
            <span class="conv-kb">{{ kbName(conv.kb_id) }}</span>
            <el-icon class="del-btn" @click.stop="removeConversation(conv)">
              <Delete />
            </el-icon>
        </div>
        <el-empty v-if="!conversations.length" description="暂无会话" :image-size="60" />
      </el-scrollbar>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--color-border);
  background: rgba(255, 255, 255, 0.58);
  backdrop-filter: blur(18px);
}

.logo {
  font-size: 18px;
  font-weight: bold;
  padding: 20px 16px;
}

.conv-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--color-border);
  padding: 12px;
  min-height: 0;
}

.conv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.conv-title {
  font-weight: bold;
  color: var(--color-text-secondary);
}

.conv-scroll {
  flex: 1;
}

.conv-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
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
