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
const editingId = ref(null);
const form = reactive({ name: "", description: "" });

const isAdmin = () => user.value?.role === "admin";

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

    <el-empty v-if="!knowledgeBases.length" description="暂无知识库" />
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
            <el-button size="small" :icon="Edit" @click="openEdit(kb)">编辑</el-button>
            <el-button size="small" type="danger" plain :icon="Delete" @click="remove(kb)">删除</el-button>
          </template>
        </div>
      </el-card>
    </div>

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
}
</style>
