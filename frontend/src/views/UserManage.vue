<script setup>
import { reactive, ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Check, Delete, Key, Plus } from "@element-plus/icons-vue";
import { api, user } from "../store";

const users = ref([]);
const createDialog = ref(false);
const resetDialog = ref(false);
const resetTarget = ref(null);
const form = reactive({ username: "", password: "", role: "user" });
const resetForm = reactive({ password: "" });
const formRef = ref(null);
const resetFormRef = ref(null);

const createRules = {
  username: [{ required: true, message: "请输入用户名", trigger: "blur" }],
  password: [
    { required: true, message: "请输入密码", trigger: "blur" },
    { min: 6, message: "密码至少 6 位", trigger: "blur" },
  ],
};

const resetRules = {
  password: [
    { required: true, message: "请输入新密码", trigger: "blur" },
    { min: 6, message: "密码至少 6 位", trigger: "blur" },
  ],
};

async function loadUsers() {
  const res = await api.get("/users");
  users.value = res.data;
}

async function createUser() {
  await formRef.value.validate();
  try {
    await api.post("/users", form);
    ElMessage.success(`用户 ${form.username} 创建成功`);
    createDialog.value = false;
    form.username = "";
    form.password = "";
    form.role = "user";
    loadUsers();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "创建失败");
  }
}

function openReset(row) {
  resetTarget.value = row;
  resetForm.password = "";
  resetDialog.value = true;
}

async function resetPassword() {
  await resetFormRef.value.validate();
  try {
    await api.put(`/users/${resetTarget.value.id}/password`, { password: resetForm.password });
    ElMessage.success(`已重置 ${resetTarget.value.username} 的密码`);
    resetDialog.value = false;
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "重置失败");
  }
}

async function removeUser(row) {
  await ElMessageBox.confirm(`确定删除用户「${row.username}」？`, "删除确认", { type: "warning" });
  try {
    await api.delete(`/users/${row.id}`);
    ElMessage.success("已删除");
    loadUsers();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "删除失败");
  }
}

function roleTag(role) {
  return role === "admin" ? "warning" : "info";
}

onMounted(loadUsers);
</script>

<template>
  <div class="user-manage">
    <div class="toolbar">
      <el-button type="primary" :icon="Plus" @click="createDialog = true">新增用户</el-button>
    </div>

    <el-table :data="users" border>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" min-width="160" />
      <el-table-column label="角色" width="110">
        <template #default="{ row }">
          <el-tag :type="roleTag(row.role)" size="small">
            {{ row.role === "admin" ? "管理员" : "普通用户" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" :icon="Key" @click="openReset(row)">重置密码</el-button>
          <el-button
            size="small"
            type="danger"
            plain
            :icon="Delete"
            :disabled="row.id === user.id"
            @click="removeUser(row)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createDialog" title="新增用户" width="420px">
      <el-form ref="formRef" :model="form" :rules="createRules" label-width="70px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :icon="Check" @click="createUser">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetDialog" :title="`重置密码 - ${resetTarget?.username}`" width="420px">
      <el-form ref="resetFormRef" :model="resetForm" :rules="resetRules" label-width="70px">
        <el-form-item label="新密码" prop="password">
          <el-input v-model="resetForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetDialog = false">取消</el-button>
        <el-button type="primary" :icon="Check" @click="resetPassword">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.user-manage {
  padding: 20px;
}

.toolbar {
  margin-bottom: 16px;
}
</style>
