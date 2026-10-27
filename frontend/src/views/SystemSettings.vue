<script setup>
import { reactive, ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { Check, RefreshLeft } from "@element-plus/icons-vue";
import { api } from "../store";

const form = reactive({ chunk_size: 800, chunk_overlap: 100, top_k: 5 });
const formRef = ref(null);
const saving = ref(false);

const rules = {
  chunk_size: [{ required: true, message: "请输入分块大小", trigger: "blur" }],
  chunk_overlap: [
    { required: true, message: "请输入重叠窗口", trigger: "blur" },
    { validator: validateOverlap, trigger: "blur" },
  ],
  top_k: [{ required: true, message: "请输入 TopK", trigger: "blur" }],
};

async function loadSettings() {
  const res = await api.get("/settings");
  Object.assign(form, res.data);
}

function validateOverlap(rule, value, callback) {
  if (value >= form.chunk_size) {
    callback(new Error("重叠窗口必须小于分块大小"));
  } else {
    callback();
  }
}

async function saveSettings() {
  await formRef.value.validate();
  saving.value = true;
  try {
    await api.put("/settings", form);
    ElMessage.success("设置已保存");
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || "保存失败");
  } finally {
    saving.value = false;
  }
}

onMounted(loadSettings);
</script>

<template>
  <div class="system-settings">
    <div class="page-card">
      <div class="page-title">系统设置</div>
      <el-alert
        class="notice"
        type="info"
        show-icon
        title="分块设置只影响之后上传或更新的文件；TopK 立即影响问答检索。"
      />

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="110px"
        class="settings-form"
      >
        <el-form-item label="分块大小" prop="chunk_size">
          <el-input-number v-model="form.chunk_size" :min="100" :max="8000" />
          <span class="field-tip">单个文本分块的最大字符数</span>
        </el-form-item>
        <el-form-item label="重叠窗口" prop="chunk_overlap">
          <el-input-number v-model="form.chunk_overlap" :min="0" :max="1000" />
          <span class="field-tip">相邻分块之间保留的重复字符数</span>
        </el-form-item>
        <el-form-item label="TopK" prop="top_k">
          <el-input-number v-model="form.top_k" :min="1" :max="50" />
          <span class="field-tip">每次问答检索的知识块数量</span>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :icon="Check" :loading="saving" @click="saveSettings">
            保存设置
          </el-button>
          <el-button :icon="RefreshLeft" @click="loadSettings">重置</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.system-settings {
  padding: 24px;
}

.page-card {
  max-width: 680px;
  padding: 24px;
  border-radius: 12px;
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #e5e7eb);
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
}

.page-title {
  margin-bottom: 18px;
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text-primary, #1f2937);
}

.notice {
  margin-bottom: 24px;
}

.field-tip {
  margin-left: 12px;
  color: var(--color-text-secondary, #64748b);
  font-size: 12px;
}
</style>
