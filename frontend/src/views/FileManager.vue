<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Delete, RefreshRight, Upload, View } from "@element-plus/icons-vue";
import { api, knowledgeBases, loadKnowledgeBases, user } from "../store";

const route = useRoute();
const files = ref([]);
const uploadRef = ref(null);
let pendingUploads = 0;
let pollTimer = null;
const selectedKb = ref(null);
const chunkDialog = ref(false);
const chunks = ref([]);
const currentFile = ref(null);
const expandedChunks = ref({});

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
  schedulePolling();
}

function schedulePolling() {
  const processing = files.value.some((f) => f.status === "processing");
  if (processing && !pollTimer) {
    pollTimer = setInterval(async () => {
      const res = await api.get("/files", { params: { kb_id: selectedKb.value } });
      files.value = res.data;
      if (!files.value.some((f) => f.status === "processing")) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }, 3000);
  }
}

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
});

async function uploadFile({ file }) {
  const form = new FormData();
  form.append("kb_id", selectedKb.value);
  form.append("file", file);
  pendingUploads++;
  try {
    const res = await api.post("/files", form);
    ElMessage.success(`${res.data.filename} 已上传，正在后台解析`);
    loadFiles();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "上传失败");
  } finally {
    pendingUploads--;
    if (pendingUploads === 0) uploadRef.value?.clearFiles();
  }
}

async function updateFile({ file }, row) {
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await api.put(`/files/${row.id}`, form);
    ElMessage.success(`${res.data.filename} 已更新到 v${res.data.version}，正在后台解析`);
    loadFiles();
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "更新失败");
  }
}

async function viewChunks(row) {
  const res = await api.get(`/files/${row.id}/chunks`);
  chunks.value = res.data;
  currentFile.value = row;
  expandedChunks.value = {};
  chunkDialog.value = true;
}

function toggleChunk(chunkIndex) {
  expandedChunks.value[chunkIndex] = !expandedChunks.value[chunkIndex];
}

async function removeFile(row) {
  await ElMessageBox.confirm(`确定删除「${row.filename}」？将同时删除其所有分块。`, "删除确认", { type: "warning" });
  await api.delete(`/files/${row.id}`);
  ElMessage.success("已删除");
  loadFiles();
}

watch(selectedKb, loadFiles);
watch(user, init, { immediate: true });

const STATUS_META = {
  processing: { label: "处理中", type: "warning" },
  ready: { label: "就绪", type: "success" },
  failed: { label: "失败", type: "danger" },
  uploaded: { label: "待处理", type: "info" },
};
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
          ref="uploadRef"
          :show-file-list="false"
          :http-request="uploadFile"
          multiple
          :limit="10"
          :on-exceed="() => ElMessage.warning('单次最多上传 10 个文件')"
          accept=".md,.docx,.pdf,.txt"
        >
          <el-button type="primary" :icon="Upload">上传文件（最多 10 个）</el-button>
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

    <div v-if="selectedKb" class="table-card">
      <el-table :data="files">
        <el-table-column prop="filename" label="文件名" min-width="240" show-overflow-tooltip />
        <el-table-column prop="file_type" label="类型" width="80" />
        <el-table-column prop="uploader" label="上传者" width="100" />
        <el-table-column label="大小" width="95">
        <template #default="{ row }">{{ formatSize(row.size) }}</template>
      </el-table-column>
        <el-table-column prop="version" label="版本" width="70">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
        <el-table-column prop="chunk_count" label="分块数" width="80" />
        <el-table-column label="状态" width="95">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.status === 'failed' && row.status_message"
              :content="row.status_message"
              placement="top"
            >
              <el-tag :type="STATUS_META[row.status]?.type || 'info'" size="small">
                {{ STATUS_META[row.status]?.label || row.status }}
              </el-tag>
            </el-tooltip>
            <el-tag v-else :type="STATUS_META[row.status]?.type || 'info'" size="small">
              {{ STATUS_META[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="上传时间" width="170">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :icon="View"
              :disabled="row.status === 'processing'"
              @click="viewChunks(row)"
            >
              分块
            </el-button>
            <el-upload
              :show-file-list="false"
              :http-request="(opt) => updateFile(opt, row)"
              accept=".md,.docx,.pdf,.txt"
              style="display: inline-block; margin: 0 8px; white-space: nowrap; vertical-align: middle"
            >
              <el-button
                link
                type="primary"
                :icon="RefreshRight"
                :disabled="row.status === 'processing'"
              >
                更新
              </el-button>
            </el-upload>
            <el-button
              v-if="isAdmin"
              link
              type="danger"
              :icon="Delete"
              :disabled="row.status === 'processing'"
              @click="removeFile(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <el-empty v-else description="暂无知识库，请先创建" />

    <el-dialog v-model="chunkDialog" :title="`分块预览 - ${currentFile?.filename}`" width="800px">
      <el-table :data="chunks" border max-height="500">
        <el-table-column prop="chunk_index" label="#" width="60" />
        <el-table-column prop="page_no" label="页码" width="70" />
        <el-table-column prop="content" label="内容" min-width="500">
          <template #default="{ row }">
            <div class="chunk-content" :class="{ expanded: expandedChunks[row.chunk_index] }">
              {{ row.content }}
            </div>
            <div v-if="row.content.length > 80" class="chunk-toggle">
              <el-button link type="primary" size="small" @click="toggleChunk(row.chunk_index)">
                {{ expandedChunks[row.chunk_index] ? "折叠" : "展开" }}
              </el-button>
            </div>
          </template>
        </el-table-column>
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

.chunk-content {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.chunk-content.expanded {
  -webkit-line-clamp: unset;
}

.chunk-toggle {
  margin-top: 4px;
  text-align: right;
}

.table-card {
  padding: 8px 12px;
  background: var(--color-surface-solid);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.file-manager :deep(.el-table) {
  --el-table-header-bg-color: var(--color-surface-muted);
  --el-table-border-color: var(--color-border);
}

.file-manager :deep(.el-table th.el-table__cell) {
  color: var(--color-text-secondary);
  font-weight: 600;
}
</style>
