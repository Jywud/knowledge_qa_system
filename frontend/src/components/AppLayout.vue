<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { Collection, Lock, Setting, SwitchButton, User } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import AppSidebar from "./AppSidebar.vue";
import { newPasswordRules } from "../utils/validation";
import {
  api,
  ensureUser,
  user,
  conversations,
  currentConversationId,
  loadConversations,
  loadKnowledgeBases,
  clearAuth,
} from "../store";

const router = useRouter();

const isChat = computed(() => router.currentRoute.value.path === "/chat");
const ready = ref(false);
const passwordDialog = ref(false);
const passwordFormRef = ref(null);
const passwordForm = reactive({ oldPassword: "", newPassword: "", confirmPassword: "" });
const passwordRules = {
  oldPassword: [{ required: true, message: "请输入原密码", trigger: "blur" }],
  newPassword: newPasswordRules,
  confirmPassword: [
    { required: true, message: "请再次输入新密码", trigger: "blur" },
    {
      validator: (_, value, callback) => {
        if (value !== passwordForm.newPassword) callback(new Error("两次输入的密码不一致"));
        else callback();
      },
      trigger: "blur",
    },
  ],
};

onMounted(async () => {
  try {
    await ensureUser();
    ready.value = true;
    if (["/roles", "/users", "/settings"].includes(router.currentRoute.value.path) && !user.value?.is_admin) {
      router.replace("/chat");
    }
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
  if (command === "change-password") {
    openPasswordDialog();
  } else if (command === "logout") {
    clearAuth();
    router.push("/login");
  } else {
    router.push(`/${command}`);
  }
}

function openPasswordDialog() {
  passwordForm.oldPassword = "";
  passwordForm.newPassword = "";
  passwordForm.confirmPassword = "";
  passwordDialog.value = true;
}

async function changePassword() {
  await passwordFormRef.value.validate();
  try {
    await api.put("/auth/password", {
      old_password: passwordForm.oldPassword,
      new_password: passwordForm.newPassword,
    });
    ElMessage.success("密码修改成功，请重新登录");
    passwordDialog.value = false;
    clearAuth();
    router.replace("/login");
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || "密码修改失败");
  }
}
</script>

<template>
  <el-container class="layout">
    <el-aside v-if="isChat" width="220px">
      <AppSidebar />
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <button v-if="!isChat" class="header-brand" @click="router.push('/home')">
            <span class="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 32 32" width="14" height="14" fill="none">
                <path d="M16 3.5 27 9.75v12.5L16 28.5 5 22.25V9.75L16 3.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
                <path d="M16 10.5v11M11 13.5l10 5M21 13.5l-10 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
              </svg>
            </span>
            <span>企业智能知识库系统</span>
          </button>
        </div>
        <div class="header-actions">
          <el-dropdown v-if="user" @command="handleCommand">
            <span class="user-entry">
              <el-avatar :size="30" class="avatar">{{ user.username[0] }}</el-avatar>
              <span>{{ user.username }}</span>
              <el-tag v-if="user.is_admin" size="small" type="warning">管理员</el-tag>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :icon="Lock" command="change-password">修改密码</el-dropdown-item>
                <el-dropdown-item v-if="user.is_admin" :icon="User" command="users">用户管理</el-dropdown-item>
                <el-dropdown-item v-if="user.is_admin" :icon="User" command="roles">角色管理</el-dropdown-item>
                <el-dropdown-item :icon="Collection" command="knowledge-bases">知识库</el-dropdown-item>
                <el-dropdown-item v-if="user.is_admin" :icon="Setting" command="settings">系统设置</el-dropdown-item>
                <el-dropdown-item :icon="SwitchButton" command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main">
        <router-view v-if="ready" />
      </el-main>
    </el-container>
    <el-dialog v-model="passwordDialog" title="修改密码" width="420px">
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-width="80px">
        <el-form-item label="原密码" prop="oldPassword">
          <el-input v-model="passwordForm.oldPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="passwordForm.newPassword" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input v-model="passwordForm.confirmPassword" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialog = false">取消</el-button>
        <el-button type="primary" @click="changePassword">确定</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid var(--color-border);
  background: rgba(255, 255, 255, 0.68);
  backdrop-filter: blur(18px);
}

.header-left {
  display: flex;
  align-items: center;
  min-width: 0;
}

.header-brand {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 6px 8px;
  border: none;
  border-radius: var(--radius-md);
  background: none;
  font: inherit;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
  cursor: pointer;
  transition: background 0.18s ease;
}

.header-brand:hover {
  background: var(--color-surface-muted);
}

.header-brand .brand-mark {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  color: #fff;
  background: var(--gradient-primary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 16px;
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
