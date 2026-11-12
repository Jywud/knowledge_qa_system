<script setup>
import { reactive, ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Check, Delete, Key, Plus } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import { api, clearAuth, user, refreshUser } from "../store";
import { newPasswordRules, usernameRules } from "../utils/validation";

const router = useRouter();
const users = ref([]);
const roles = ref([]);
const roleDialog = ref(false);
const roleTarget = ref(null);
const roleIds = ref([]);
const savingRoles = ref(false);
function openRoles(row) {
  roleTarget.value = row;
  roleIds.value = row.roles.map((role) => role.id);
  roleDialog.value = true;
}
async function saveRoles() {
  if (!roleIds.value.length) { ElMessage.warning("请至少选择一个角色"); return; }
  savingRoles.value = true;
  try {
    await api.put(`/users/${roleTarget.value.id}/roles`, { role_ids: [...roleIds.value] });
    if (roleTarget.value.id === user.value?.id) {
      await refreshUser();
      if (!user.value?.is_admin) router.replace("/chat");
    }
    roleDialog.value = false;
    ElMessage.success("角色已更新");
    if (user.value?.is_admin) await loadUsers();
  } catch (e) { ElMessage.error(e.response?.data?.detail || "角色更新失败"); }
  finally { savingRoles.value = false; }
}
const createDialog = ref(false);
const resetDialog = ref(false);
const resetTarget = ref(null);
const form = reactive({ username: "", password: "", role_ids: [] });
const resetForm = reactive({ password: "" });
const formRef = ref(null);
const resetFormRef = ref(null);

const createRules = {
  username: usernameRules,
  password: newPasswordRules,
  role_ids: [{ type: "array", required: true, min: 1, message: "请至少选择一个角色", trigger: "change" }],
};

const resetRules = {
  password: newPasswordRules,
};

async function loadUsers() {
  const res = await api.get("/users");
  users.value = res.data;
}

async function createUser() {
  if (!form.role_ids.length) { ElMessage.warning("请至少选择一个角色"); return; }
  await formRef.value.validate();
  try {
    form.username = form.username.trim();
    await api.post("/users", { username: form.username, password: form.password, role_ids: [...form.role_ids] });
    ElMessage.success(`用户 ${form.username} 创建成功`);
    createDialog.value = false;
    form.username = "";
    form.password = "";
    form.role_ids = [];
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
    const isSelf = resetTarget.value.id === user.value?.id;
    await api.put(`/users/${resetTarget.value.id}/password`, { password: resetForm.password });
    ElMessage.success(isSelf ? "密码重置成功，请重新登录" : `已重置 ${resetTarget.value.username} 的密码`);
    resetDialog.value = false;
    if (isSelf) {
      clearAuth();
      router.replace("/login");
    }
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

onMounted(async () => {
  try {
    const res = await api.get("/roles");
    roles.value = res.data;
    await loadUsers();
  } catch (e) { ElMessage.error(e.response?.data?.detail || "加载用户或角色失败"); }
});
</script>

<template>
  <div class="user-manage">
    <div class="toolbar">
      <el-button type="primary" :icon="Plus" @click="createDialog = true">新增用户</el-button>
    </div>

    <el-table :data="users" border>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" min-width="160" />
      <el-table-column label="角色" min-width="190">
        <template #default="{ row }">
          <el-tag v-for="role in row.roles" :key="role.id" :type="role.system_key === 'system_admin' ? 'warning' : 'info'" size="small" class="role-tag">{{ role.name }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="300">
        <template #default="{ row }">
          <el-button size="small" @click="openRoles(row)">分配角色</el-button>
          <el-button size="small" :icon="Key" @click="openReset(row)">重置密码</el-button>
          <el-button
            size="small"
            type="danger"
            plain
            :icon="Delete"
            :disabled="row.id === user?.id"
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
        <el-form-item label="角色" prop="role_ids">
          <el-select v-model="form.role_ids" multiple placeholder="请选择至少一个角色">
            <el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :icon="Check" @click="createUser">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleDialog" :title="`分配角色 - ${roleTarget?.username}`" width="440px">
      <el-select v-model="roleIds" multiple placeholder="请选择至少一个角色" style="width: 100%">
        <el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" />
      </el-select>
      <template #footer>
        <el-button @click="roleDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingRoles" @click="saveRoles">保存</el-button>
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

.role-tag { margin: 3px 5px 3px 0; }

.toolbar {
  margin-bottom: 16px;
}
</style>
