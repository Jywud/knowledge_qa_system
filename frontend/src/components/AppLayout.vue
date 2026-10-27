<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { Collection, Lock, Setting, SwitchButton, User } from "@element-plus/icons-vue";
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
const passwordDialog = ref(false);
const passwordFormRef = ref(null);
const passwordForm = reactive({ oldPassword: "", newPassword: "", confirmPassword: "" });
const passwordRules = {
  oldPassword: [{ required: true, message: "请输入原密码", trigger: "blur" }],
  newPassword: [
    { required: true, message: "请输入新密码", trigger: "blur" },
    { min: 6, message: "密码至少 6 位", trigger: "blur" },
  ],
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
    ElMessage.success("密码修改成功");
    passwordDialog.value = false;
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || "密码修改失败");
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
                <el-dropdown-item :icon="Lock" command="change-password">修改密码</el-dropdown-item>
                <el-dropdown-item v-if="user.role === 'admin'" :icon="User" command="users">用户管理</el-dropdown-item>
                <el-dropdown-item :icon="Collection" command="knowledge-bases">知识库</el-dropdown-item>
                <el-dropdown-item v-if="user.role === 'admin'" :icon="Setting" command="settings">系统设置</el-dropdown-item>
                <el-dropdown-item :icon="SwitchButton" command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
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
