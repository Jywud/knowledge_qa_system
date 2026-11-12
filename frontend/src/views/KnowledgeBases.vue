<script setup>
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  CircleCheck,
  Delete,
  Edit,
  Folder,
  FolderOpened,
  Plus,
  Search,
} from "@element-plus/icons-vue";
import { api, knowledgeBases, loadKnowledgeBases, user } from "../store";

const router = useRouter();
const search = ref("");
const dialog = ref(false);
const accessDialog = ref(false);
const accessRoles = ref([]);
const accessName = ref("");
const accessLoading = ref(false);
let accessRequest = 0;
async function showRoles(kb) {
  const request = ++accessRequest;
  accessName.value = kb.name;
  accessRoles.value = [];
  accessLoading.value = true;
  accessDialog.value = true;
  try {
    const { data } = await api.get(`/knowledge-bases/${kb.id}/roles`);
    if (request === accessRequest) accessRoles.value = data;
  } catch (e) { ElMessage.error(e.response?.data?.detail || "加载授权角色失败"); }
  finally { if (request === accessRequest) accessLoading.value = false; }
}
const editingId = ref(null);
const form = reactive({ name: "", description: "" });

const isAdmin = () => user.value?.is_admin === true;

async function load() {
  await loadKnowledgeBases(search.value);
}

async function openCreate() {
  editingId.value = null;
  form.name = "";
  form.description = "";
  dialog.value = true;
}

function openEdit(row) {
  editingId.value = row.id;
  form.name = row.name;
  form.description = row.description;
  dialog.value = true;
}

async function submit() {
  if (!form.name.trim()) {
    ElMessage.warning("请输入知识库名称");
    return;
  }
  try {
    if (editingId.value) {
      await api.put(`/knowledge-bases/${editingId.value}`, form);
      ElMessage.success("已更新");
    } else {
      await api.post("/knowledge-bases", form);
      ElMessage.success("创建成功");
    }
    dialog.value = false;
    load();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "操作失败");
  }
}

async function enter(row) {
  router.push(`/files?kb_id=${row.id}`);
}

async function remove(row) {
  await ElMessageBox.confirm(
    `确定删除知识库「${row.name}」？其下所有文件和向量数据将被删除。`,
    "删除确认",
    { type: "warning" }
  );
  try {
    await api.delete(`/knowledge-bases/${row.id}`);
    ElMessage.success("已删除");
    load();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "删除失败");
  }
}

onMounted(load);
</script>

<template>
  <div class="kb-page">
    <div class="toolbar">
      <el-input
        v-model="search"
        placeholder="搜索知识库名称..."
        clearable
        style="width: 260px"
        @keyup.enter="load"
        @clear="load"
      />
      <el-button :icon="Search" @click="load">搜索</el-button>
      <el-button v-if="isAdmin()" type="primary" :icon="Plus" @click="openCreate">创建知识库</el-button>
    </div>

    <el-empty v-if="!knowledgeBases.length" :description="isAdmin() ? '还没有知识库，创建一个开始使用' : '还没有知识库，请联系管理员创建'">
      <el-button v-if="isAdmin()" type="primary" :icon="Plus" @click="openCreate">创建知识库</el-button>
    </el-empty>
    <div v-else class="cards">
      <el-card v-for="kb in knowledgeBases" :key="kb.id" class="kb-card" shadow="hover">
        <div class="kb-head">
          <el-icon class="kb-icon"><Folder /></el-icon>
          <span class="kb-name">{{ kb.name }}</span>
        </div>
        <p class="kb-desc">{{ kb.description || "暂无描述" }}</p>
        <div class="kb-stats">
          <el-tag size="small">{{ kb.file_count }} 个文件</el-tag>
          <el-tag size="small" type="info">{{ kb.chunk_count }} 个分块</el-tag>
        </div>
        <div class="kb-actions">
          <el-button size="small" type="primary" :icon="FolderOpened" @click="enter(kb)">进入</el-button>
          <template v-if="isAdmin()">
            <el-button size="small" @click="showRoles(kb)">授权角色</el-button>
            <el-button size="small" :icon="Edit" @click="openEdit(kb)">编辑</el-button>
            <el-button size="small" type="danger" plain :icon="Delete" @click="remove(kb)">删除</el-button>
          </template>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="accessDialog" :title="`授权角色 - ${accessName}`" width="480px">
      <div v-loading="accessLoading">
        <p>角色授权请前往角色管理调整。系统管理员始终可访问全部知识库。</p>
        <el-tag v-for="role in accessRoles" :key="role.id" :type="role.system_key ? 'warning' : 'info'" style="margin: 4px">{{ role.name }}</el-tag>
        <el-empty v-if="!accessLoading && !accessRoles.length" description="暂无授权业务角色" />
      </div>
      <template #footer><el-button @click="accessDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="dialog" :title="editingId ? '编辑知识库' : '创建知识库'" width="440px">
      <el-form label-width="70px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="知识库名称" maxlength="64" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="知识库描述（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :icon="CircleCheck" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kb-page {
  padding: 20px;
}

.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.cards {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.kb-card {
  width: 280px;
}

.kb-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.kb-icon {
  font-size: 20px;
  color: var(--el-color-primary);
}

.kb-name {
  font-weight: bold;
  font-size: 16px;
}

.kb-desc {
  color: var(--color-text-muted);
  font-size: 13px;
  margin: 10px 0;
  min-height: 36px;
  white-space: pre-wrap;
  word-break: break-word;
}

.kb-stats {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.kb-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
