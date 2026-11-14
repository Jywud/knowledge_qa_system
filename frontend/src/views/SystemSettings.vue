<script setup>
import { reactive, ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { Check, RefreshLeft } from "@element-plus/icons-vue";
import { api } from "../store";

const form = reactive({ chunk_size: 800, chunk_overlap: 100, top_k: 30, rerank_enabled: false, rrf_top_n: 20, top_n: 5, retrieval_min_score: 0.5 });
const formRef = ref(null);
const saving = ref(false);

const rules = {
  chunk_size: [{ required: true, message: "请输入分块大小", trigger: "blur" }],
  chunk_overlap: [
    { required: true, message: "请输入重叠窗口", trigger: "blur" },
    { validator: validateOverlap, trigger: "blur" },
  ],
  top_k: [{ required: true, message: "请输入召回候选数", trigger: "blur" }],
  rrf_top_n: [{ required: true, message: "请输入融合保留条数", trigger: "blur" }],
  top_n: [
    { required: true, message: "请输入重排保留条数", trigger: "blur" },
    { validator: validateTopN, trigger: "blur" },
  ],
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

function validateTopN(rule, value, callback) {
  if (value > form.rrf_top_n) {
    callback(new Error("重排保留条数不能大于融合保留条数"));
  } else {
    callback();
  }
}

async function saveSettings() {
  await formRef.value.validate();
  saving.value = true;
  try {
    const payload = { ...form, retrieval_min_score: Math.round(form.retrieval_min_score * 10) / 10 };
    await api.put("/settings", payload);
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
        title="分块设置只影响之后上传或更新的文件；检索参数立即生效。"
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
        <el-form-item label="召回候选数" prop="top_k">
          <el-input-number v-model="form.top_k" :min="1" :max="50" />
          <span class="field-tip">向量与关键词检索各路召回的候选条数</span>
        </el-form-item>
        <el-form-item label="融合保留条数" prop="rrf_top_n">
          <el-input-number v-model="form.rrf_top_n" :min="1" :max="100" />
          <span class="field-tip">多路召回融合后保留的候选条数</span>
        </el-form-item>
        <el-form-item label="语义重排">
          <el-switch v-model="form.rerank_enabled" />
          <span class="field-tip">开启后按相关性对候选重新排序（需在 .env 配置重排服务）</span>
        </el-form-item>
        <el-form-item label="重排保留条数" prop="top_n">
          <el-input-number v-model="form.top_n" :min="1" :max="100" :disabled="!form.rerank_enabled" />
          <span class="field-tip">重排后送入大模型的知识块数量</span>
        </el-form-item>
        <el-form-item label="相似度阈值" prop="retrieval_min_score">
          <el-slider
            v-model="form.retrieval_min_score"
            class="score-slider"
            :min="0.1"
            :max="0.9"
            :step="0.1"
            show-input
          />
          <span class="field-tip">向量召回的相关度下限，低于阈值的候选不进入融合</span>
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
  width: 100%;
  padding: 24px;
  border-radius: var(--radius-lg);
  background: var(--color-surface-solid);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-card);
}

.page-title {
  margin-bottom: 18px;
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text);
}

.notice {
  margin-bottom: 24px;
}

.field-tip {
  margin-left: 12px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.score-slider {
  width: 420px;
}
</style>
