<script setup>
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import AppSidebar from "./AppSidebar.vue";
import {
  api,
  user,
  conversations,
  currentConversationId,
  loadConversations,
  loadKnowledgeBases,
  clearAuth,
  selectedKb,
  knowledgeBases,
} from "../store";

const router = useRouter();

const isChat = computed(() => router.currentRoute.value.path === "/chat");
const kbLocked = computed(() => !!currentConversationId.value);

function kbSelectable(kb) {
  return kb.chunk_count > 0;
}

function kbLabel(kb) {
  return kbSelectable(kb) ? kb.name : `${kb.name}（暂无文档）`;
}

onMounted(async () => {
  try {
    const res = await api.get("/auth/me");
    user.value = res.data;
    localStorage.setItem("kqa_user", JSON.stringify(res.data));
    await loadConversations();
    await loadKnowledgeBases();
    if (!currentConversationId.value && conversations.value.length) {
      currentConversationId.value = conversations.value[0].id;
    }
  } catch {
    clearAuth();
    router.push("/login");
  }
});

function handleCommand(command) {
  if (command === "logout") {
    clearAuth();
    router.push("/login");
  } else {
    router.push(`/${command}`);
  }
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px">
      <AppSidebar />
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="header-actions">
          <el-tooltip
            v-if="isChat && kbLocked"
            content="已绑定，切换请新建对话"
            placement="bottom"
          >
            <el-select
              v-model="selectedKb"
              class="kb-select"
              :disabled="kbLocked"
              clearable
              placeholder="全部知识库"
            >
              <el-option
                v-for="kb in knowledgeBases"
                :key="kb.id"
                :label="kbLabel(kb)"
                :value="kb.id"
                :disabled="!kbSelectable(kb)"
              />
            </el-select>
          </el-tooltip>
          <el-select
            v-else-if="isChat"
            v-model="selectedKb"
            class="kb-select"
            clearable
            placeholder="全部知识库"
          >
            <el-option
              v-for="kb in knowledgeBases"
              :key="kb.id"
              :label="kbLabel(kb)"
              :value="kb.id"
              :disabled="!kbSelectable(kb)"
            />
          </el-select>
          <el-dropdown v-if="user" @command="handleCommand">
            <span class="user-entry">
              <el-avatar :size="30" class="avatar">{{ user.username[0] }}</el-avatar>
              <span>{{ user.username }}</span>
              <el-tag v-if="user.role === 'admin'" size="small" type="warning">管理员</el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="user.role === 'admin'" command="users">用户管理</el-dropdown-item>
                <el-dropdown-item command="knowledge-bases">知识库</el-dropdown-item>
                <el-dropdown-item v-if="user.role === 'admin'" command="settings">系统设置</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}

.header {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 24px;
  border-bottom: 1px solid var(--color-border);
  background: rgba(255, 255, 255, 0.68);
  backdrop-filter: blur(18px);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.kb-select {
  width: 180px;
}

.user-entry {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  outline: none;
}

.avatar {
  background: var(--el-color-primary);
  font-size: 14px;
}

.main {
  padding: 0;
}
</style>
