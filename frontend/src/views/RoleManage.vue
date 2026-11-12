<script setup>
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Plus, Edit, Delete } from "@element-plus/icons-vue";
import { api, refreshUser, loadKnowledgeBases } from "../store";

const roles = ref([]);
const libraries = ref([]);
const dialog = ref(false);
const editingId = ref(null);
const systemRole = ref(false);
const saving = ref(false);
const form = reactive({ name: "", description: "", kb_ids: [] });
async function load() {
  const [roleRes, kbRes] = await Promise.all([api.get("/roles"), api.get("/knowledge-bases")]);
  roles.value = roleRes.data;
  libraries.value = kbRes.data;
}
function openCreate() {
  editingId.value = null;
  systemRole.value = false;
  Object.assign(form, { name: "", description: "", kb_ids: [] });
  dialog.value = true;
}
function openEdit(row) {
  editingId.value = row.id;
  systemRole.value = row.system_key === "system_admin";
  Object.assign(form, { name: row.name, description: row.description || "", kb_ids: [...row.kb_ids] });
  dialog.value = true;
}
async function saveRole() {
  if (systemRole.value) return;
  if (!form.name.trim()) { ElMessage.warning("请输入角色名称"); return; }
  saving.value = true;
  try {
    const data = { name: form.name.trim(), description: form.description, kb_ids: [...form.kb_ids] };
    if (editingId.value) await api.put(`/roles/${editingId.value}`, data);
    else await api.post("/roles", data);
    dialog.value = false;
    ElMessage.success("角色已保存");
    await load();
    await refreshUser();
    await loadKnowledgeBases();
  } catch (e) { ElMessage.error(e.response?.data?.detail || "保存角色失败"); }
  finally { saving.value = false; }
}
async function removeRole(row) {
  if (row.system_key || row.user_count) return;
  await ElMessageBox.confirm(`确定删除角色「${row.name}」？`, "删除确认", { type: "warning" });
  try {
    await api.delete(`/roles/${row.id}`);
    ElMessage.success("角色已删除");
    await load();
  } catch (e) { ElMessage.error(e.response?.data?.detail || "删除角色失败"); }
}
onMounted(async () => {
  try { await load(); } catch (e) { ElMessage.error(e.response?.data?.detail || "加载角色失败"); }
});
</script>

<template>
  <div class="role-page">
    <div class="toolbar"><el-button type="primary" :icon="Plus" @click="openCreate">新增角色</el-button></div>
    <p class="hint">员工可有多个角色，可访问知识库取各角色授权的并集。业务角色只能读取文档和问答。</p>
    <el-table :data="roles" border>
      <el-table-column prop="name" label="角色名称" min-width="160" />
      <el-table-column prop="description" label="描述" min-width="180" />
      <el-table-column label="可访问知识库" min-width="240">
        <template #default="{row}">
          <el-tag v-if="row.system_key === 'system_admin'" type="warning">全部知识库 · 系统管理</el-tag>
          <template v-else>
            <el-tag v-for="id in row.kb_ids" :key="id" class="kb-tag">{{ libraries.find(kb => kb.id === id)?.name || `知识库 ${id}` }}</el-tag>
            <span v-if="!row.kb_ids.length" class="hint">未授权知识库</span>
          </template>
        </template>
      </el-table-column>
      <el-table-column prop="user_count" label="用户数" width="90" />
      <el-table-column label="操作" width="240">
        <template #default="{row}">
          <el-button size="small" :icon="Edit" @click="openEdit(row)">{{ row.system_key ? '查看' : '编辑授权' }}</el-button>
          <el-tooltip :disabled="!row.system_key && !row.user_count" :content="row.system_key ? '内置系统管理员角色不能删除' : '请先调整使用该角色的用户'">
            <span><el-button size="small" type="danger" plain :icon="Delete" :disabled="!!row.system_key || row.user_count > 0" @click="removeRole(row)">删除</el-button></span>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>
    <el-dialog v-model="dialog" :title="systemRole ? '系统管理员角色' : editingId ? '编辑角色授权' : '新增角色'" width="560px">
      <el-form label-width="100px" :disabled="systemRole || saving">
        <el-form-item label="角色名称" required><el-input v-model="form.name" maxlength="64" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="可访问知识库">
          <p v-if="systemRole" class="hint">内置角色拥有全部知识库与系统管理权限，不能缩减。</p>
          <div v-else>
            <el-checkbox-group v-model="form.kb_ids" class="kb-options">
              <el-checkbox v-for="kb in libraries" :key="kb.id" :value="kb.id">{{ kb.name }}</el-checkbox>
            </el-checkbox-group>
            <p class="hint">{{ libraries.length ? '不勾选任何库时，该角色不能读取文档或问答。' : '暂无知识库，可先保存角色，再创建知识库并授权。' }}</p>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">{{ systemRole ? '关闭' : '取消' }}</el-button>
        <el-button v-if="!systemRole" type="primary" :loading="saving" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.role-page { padding: 20px; }
.toolbar { margin-bottom: 16px; }
.hint { color: var(--color-text-secondary); font-size: 13px; line-height: 1.6; }
.kb-tag { margin: 3px 5px 3px 0; }
.kb-options { display: flex; flex-wrap: wrap; }
</style>
