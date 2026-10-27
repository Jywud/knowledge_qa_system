<script setup>
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Delete, RefreshRight, Upload, View } from "@element-plus/icons-vue";
import { api, knowledgeBases, loadKnowledgeBases, user } from "../store";

const route = useRoute();
const files = ref([]);
const selectedKb = ref(null);
const chunkDialog = ref(false);
const chunks = ref([]);
const currentFile = ref(null);

const isAdmin = computed(() => user.value?.role === "admin");

function formatSize(size) {
  if (size < 1024) return size + " B";
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + " KB";
  return (size / 1024 / 1024).toFixed(1) + " MB";
}

async function init() {
  await loadKnowledgeBases();
  const fromQuery = Number(route.query.kb_id) || null;
  const exists = knowledgeBases.value.some((kb) => kb.id === fromQuery);
  selectedKb.value = exists ? fromQuery : knowledgeBases.value[0]?.id ?? null;
}

async function loadFiles() {
  if (!selectedKb.value) {
    files.value = [];
    return;
  }
  const res = await api.get("/files", { params: { kb_id: selectedKb.value } });
  files.value = res.data;
}

async function uploadFile({ file }) {
  const form = new FormData();
  form.append("kb_id", selectedKb.value);
  form.append("file", file);
  try {
    const res = await api.post("/files", form);
    ElMessage.success(`${res.data.filename} 上传成功，切分 ${res.data.chunk_count} 块`);
    loadFiles();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "上传失败");
  }
}

async function updateFile({ file }, row) {
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await api.put(`/files/${row.id}`, form);
    ElMessage.success(`${res.data.filename} 已更新到 v${res.data.version}，切分 ${res.data.chunk_count} 块`);
    loadFiles();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "更新失败");
  }
}

async function viewChunks(row) {
  const res = await api.get(`/files/${row.id}/chunks`);
  chunks.value = res.data;
  currentFile.value = row;
  chunkDialog.value = true;
}

async function removeFile(row) {
  await ElMessageBox.confirm(`确定删除「${row.filename}」？将同时删除其所有分块。`, "删除确认", { type: "warning" });
  await api.delete(`/files/${row.id}`);
  ElMessage.success("已删除");
  loadFiles();
}

watch(selectedKb, loadFiles);
watch(user, init, { immediate: true });
</script>

<template>
  <div class="file-manager">
    <div class="toolbar">
      <el-select
        v-model="selectedKb"
        placeholder="选择知识库"
        style="width: 240px"
      >
        <el-option
          v-for="kb in knowledgeBases"
          :key="kb.id"
          :label="kb.name"
          :value="kb.id"
        />
      </el-select>
      <template v-if="isAdmin && selectedKb">
        <el-upload
          :show-file-list="false"
          :http-request="uploadFile"
          accept=".md,.docx,.pdf,.txt"
        >
          <el-button type="primary" :icon="Upload">上传文件（md / docx / pdf / txt）</el-button>
        </el-upload>
      </template>
      <el-alert
        v-else
        :title="isAdmin ? '请先选择知识库' : '仅管理员可上传 / 更新 / 删除文件'"
        type="info"
        :closable="false"
        show-icon
      />
    </div>

    <el-table v-if="selectedKb" :data="files" border>
      <el-table-column prop="filename" label="文件名" min-width="220" />
      <el-table-column prop="file_type" label="类型" width="80" />
      <el-table-column prop="uploader" label="上传者" width="110" />
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ formatSize(row.size) }}</template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="70">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="分块数" width="90" />
      <el-table-column prop="status" label="状态" width="90" />
      <el-table-column prop="created_at" label="上传时间" width="180">
        <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :icon="View" @click="viewChunks(row)">查看分块</el-button>
          <template v-if="isAdmin">
            <el-upload
              :show-file-list="false"
              :http-request="(opt) => updateFile(opt, row)"
              accept=".md,.docx,.pdf,.txt"
              style="display: inline-block; margin: 0 6px"
            >
              <el-button size="small" type="primary" plain :icon="RefreshRight">更新</el-button>
            </el-upload>
            <el-button size="small" type="danger" plain :icon="Delete" @click="removeFile(row)">删除</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无知识库，请先创建" />

    <el-dialog v-model="chunkDialog" :title="`分块预览 - ${currentFile?.filename}`" width="800px">
      <el-table :data="chunks" border max-height="500">
        <el-table-column prop="chunk_index" label="#" width="60" />
        <el-table-column prop="page_no" label="页码" width="70" />
        <el-table-column prop="content" label="内容" show-overflow-tooltip />
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.file-manager {
  padding: 20px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
</style>
