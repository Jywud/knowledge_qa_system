<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import MarkdownIt from "markdown-it";
import { Promotion } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import {
  api,
  conversations,
  currentConversationId,
  loadConversations,
  token,
  selectedKb,
  clearAuth,
} from "../store";

const router = useRouter();
const messages = ref([]);
const input = ref("");
const sending = ref(false);
const THINKING_STEPS = ["正在检索知识库…", "正在整理相关内容…", "AI 正在思考中…"];
const sourceDialog = reactive({ visible: false, source: "", items: [] });
const chunkCache = {};
let locallyCreatedConversationId = null;

async function fetchChunkContent(fileId, chunkIndex) {
  if (!chunkCache[fileId]) {
    const res = await api.get(`/files/${fileId}/chunks`);
    chunkCache[fileId] = res.data;
  }
  const chunk = chunkCache[fileId].find((c) => String(c.chunk_index) === String(chunkIndex));
  return chunk ? chunk.content : "";
}

async function openSourceDialog(source) {
  sourceDialog.source = source.source;
  sourceDialog.items = source.excerpts.map((excerpt) =>
    typeof excerpt === "object" ? { ...excerpt, content: "" } : { text: excerpt, content: "" }
  );
  sourceDialog.visible = true;
  for (const item of sourceDialog.items) {
    if (item.file_id != null) {
      item.content = await fetchChunkContent(item.file_id, item.chunk_index);
    }
  }
}
const msgListRef = ref(null);

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true });

function renderMarkdown(content) {
  return markdown.render(content || "");
}

const canSend = computed(() => Boolean(input.value.trim() && selectedKb.value && !sending.value));
function scrollBottom() {
  nextTick(() => {
    const el = msgListRef.value;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

function requestErrorMessage(status, detail) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => item.msg).filter((msg) => typeof msg === "string");
    if (messages.length) return messages.join("；");
  }
  if (status === 401) return "登录已过期，请重新登录";
  if (status === 403) return "没有权限访问该知识库";
  if (status === 404) return "会话或知识库不存在，请刷新后重试";
  if (status === 429) return "请求过于频繁，请稍后重试";
  if (status === 400 || status === 422) return "请求参数有误，请检查后重试";
  return "服务暂不可用，请稍后重试";
}

function handleUnauthorized(message) {
  clearAuth();
  ElMessage.error(message);
  router.replace("/login");
}

async function selectConversation(id) {
  if (!id) {
    messages.value = [];
    return;
  }
  messages.value = [];
  try {
    const res = await api.get(`/conversations/${id}/messages`);
    if (currentConversationId.value !== id) return;
    messages.value = res.data.map((m) => ({
      role: m.role,
      content: m.content,
      sources: m.sources ? JSON.parse(m.sources) : [],
      done: true,
    }));
    scrollBottom();
  } catch (error) {
    const message = requestErrorMessage(error.response?.status, error.response?.data?.detail);
    if (error.response?.status === 401) handleUnauthorized(message);
    else if (currentConversationId.value === id) ElMessage.error(message);
  }
}

watch(currentConversationId, (id) => {
  // 激活刚创建的会话时保留本地回答/错误，避免空历史将它们覆盖。
  if (id && id === locallyCreatedConversationId) {
    locallyCreatedConversationId = null;
    return;
  }
  return selectConversation(id);
}, { immediate: true });

watch(currentConversationId, (id) => {
  const conv = conversations.value.find((c) => c.id === id);
  selectedKb.value = conv ? conv.kb_id : null;
});

async function send() {
  const content = input.value.trim();
  if (!selectedKb.value) {
    ElMessage.warning("请先选择知识库");
    return;
  }
  if (!content || sending.value || !token.value) return;
  const kbId = selectedKb.value;
  input.value = "";
  sending.value = true;
  let convId = currentConversationId.value;
  const isNew = !convId;
  let assistant = null;
  let thinkingTimer = null;
  let reader = null;
  try {
    if (isNew) {
      const res = await api.post("/conversations", { kb_id: kbId });
      convId = res.data.id;
      conversations.value.unshift(res.data);
    }
    messages.value.push({ role: "user", content });
    assistant = reactive({ role: "assistant", content: "", sources: [], done: false, status: THINKING_STEPS[0] });
    messages.value.push(assistant);
    scrollBottom();
    thinkingTimer = setInterval(() => {
      if (assistant.content) return;
      const next = THINKING_STEPS.indexOf(assistant.status) + 1;
      if (next < THINKING_STEPS.length) assistant.status = THINKING_STEPS[next];
    }, 3500);
    const res = await fetch(`/api/conversations/${convId}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token.value}`,
      },
      body: JSON.stringify({ content, kb_id: kbId }),
    });
    if (!res.ok) {
      let detail;
      try { detail = (await res.json()).detail; } catch { /* 使用状态码兜底。 */ }
      throw Object.assign(new Error(requestErrorMessage(res.status, detail)), { status: res.status });
    }
    const conv = conversations.value.find((item) => item.id === convId);
    if (conv && !conv.kb_id) conv.kb_id = kbId;
    if (currentConversationId.value === convId) selectedKb.value = kbId;
    if (!res.body) throw new Error("服务返回空响应，请稍后重试");
    reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completed = false;
    while (!completed) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 2);
        if (!line.startsWith("data: ")) continue;
        const evt = JSON.parse(line.slice(6));
        if (evt.type === "token") {
          assistant.content += evt.content;
          scrollBottom();
        } else if (evt.type === "sources") {
          assistant.sources = evt.sources;
        } else if (evt.type === "error") {
          assistant.content += `\n[错误] ${evt.message}`;
        } else if (evt.type === "done") {
          completed = true;
          break;
        }
      }
    }
    if (!completed) throw new Error("回答中断，请重试；已收到的内容已保留");
    if (!assistant.content) throw new Error("未收到回答，请稍后重试");
  } catch (e) {
    const status = e.status ?? e.response?.status;
    const message = e.response ? requestErrorMessage(status, e.response.data?.detail)
      : e.name === "TypeError" ? "网络连接失败，请检查网络后重试"
        : e.name === "SyntaxError" ? "服务返回格式异常，请稍后重试" : e.message || "请求失败，请稍后重试";
    if (status === 401) handleUnauthorized(message);
    else if (assistant) assistant.content += `\n[请求失败] ${message}`;
    else {
      input.value = content;
      ElMessage.error(message);
    }
  } finally {
    clearInterval(thinkingTimer);
    if (reader) await reader.cancel().catch(() => {});
    if (assistant) assistant.done = true;
    sending.value = false;
    if (token.value && convId) {
      if (isNew && !currentConversationId.value) {
        locallyCreatedConversationId = convId;
        currentConversationId.value = convId;
      }
      try { await loadConversations(); } catch (error) {
        const message = requestErrorMessage(error.response?.status, error.response?.data?.detail);
        if (error.response?.status === 401) handleUnauthorized(message);
        else ElMessage.error("会话列表刷新失败，请稍后重试");
      }
    }
  }
}
</script>

<template>
  <div class="chat-layout">
    <div class="chat-area">
      <div ref="msgListRef" class="msg-list">
        <div v-if="!messages.length" class="chat-welcome">
          <h2 class="welcome-title">有什么可以帮您？</h2>
          <p class="welcome-desc">{{ currentConversationId ? '输入问题，AI 将基于所选知识库为您解答' : '选择上方知识库后输入问题，AI 将基于文档内容为您解答' }}</p>
        </div>
        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="msg-row"
          :class="msg.role"
        >
          <div class="bubble">
            <template v-if="msg.role === 'assistant'">
              <div v-if="!msg.content && !msg.done" class="thinking">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="thinking-text">{{ msg.status }}</span>
              </div>
              <div v-else class="content markdown-body">
                <span v-html="renderMarkdown(msg.content)"></span>
                <span v-if="!msg.done" class="typing-cursor"></span>
              </div>
            </template>
            <div v-else class="content">{{ msg.content }}</div>
            <div v-if="msg.sources && msg.sources.length" class="sources">
              <el-tag
                v-for="s in msg.sources"
                :key="s.index ?? s.source"
                size="small"
                type="info"
                class="source-tag"
                @click="openSourceDialog(s)"
              >
                <span class="source-label">
                  {{ s.source }}<span v-if="s.count > 1" class="source-count"> ×{{ s.count }}</span>
                  <span v-if="s.file_type" class="source-extra">{{ s.file_type }}</span>
                </span>
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <div class="input-area">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          :disabled="sending"
          :placeholder="selectedKb ? '输入问题，Ctrl+Enter 发送' : '请先选择知识库'"
          @keydown.ctrl.enter.prevent="send"
        />
        <el-button
          type="primary"
          :loading="sending"
          :icon="Promotion"
          :disabled="!canSend"
          @click="send"
        >
          发送
        </el-button>
      </div>

      <el-dialog v-model="sourceDialog.visible" :title="sourceDialog.source" width="680px">
        <div v-for="item in sourceDialog.items" :key="item.index ?? item.text" class="source-item">
          <div v-if="item.index" class="source-item-title">来源{{ item.index }}</div>
          <div class="source-item-content">{{ item.content || item.text }}</div>
        </div>
      </el-dialog>
    </div>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: 100%;
}

.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 28px 28px 36px;
}

.msg-row {
  display: flex;
  margin-bottom: 14px;
}

.msg-row.user {
  justify-content: flex-end;
}

.bubble {
  max-width: min(860px, 78%);
  padding: 14px 18px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(148, 139, 255, 0.16);
  box-shadow: 0 8px 24px rgba(82, 63, 163, 0.08);
  backdrop-filter: blur(12px);
}

.msg-row.user .bubble {
  background: var(--gradient-primary);
  color: var(--color-on-primary);
  border-bottom-right-radius: 6px;
  box-shadow: 0 10px 24px rgba(124, 58, 237, 0.2);
}

.msg-row:not(.user) .bubble {
  border-bottom-left-radius: 6px;
}

.content {
  white-space: pre-wrap;
  word-break: break-word;
}

.markdown-body {
  white-space: normal;
}

.markdown-body :deep(p) {
  margin: 0 0 10px;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin: 0 0 8px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 20px;
  margin: 0 0 10px;
}

.markdown-body :deep(blockquote) {
  padding: 8px 12px;
  border-left: 3px solid var(--el-color-primary);
  background: rgba(124, 58, 237, 0.06);
  color: var(--color-text-secondary);
}

.markdown-body :deep(pre) {
  padding: 12px;
  border-radius: var(--radius-md);
  background: rgba(23, 24, 48, 0.06);
  overflow: auto;
}

.markdown-body :deep(code) {
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 13px;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 8px 0;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 6px 8px;
  border: 1px solid var(--color-border);
  text-align: left;
}

.markdown-body :deep(a) {
  color: var(--el-color-primary);
}

.sources {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.source-extra {
  margin-left: 6px;
  color: var(--color-text-secondary);
}

.source-count {
  color: var(--color-primary);
  font-weight: 600;
}

.source-label {
  cursor: pointer;
}

.source-tag {
  cursor: pointer;
}

.source-item {
  margin-bottom: 16px;
}

.source-item:last-child {
  margin-bottom: 0;
}

.source-item-title {
  margin-bottom: 4px;
  font-weight: 600;
  color: var(--color-primary);
}

.source-item-content {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--color-text);
}

.input-area {
  display: flex;
  gap: 10px;
  padding: 14px 24px 18px;
  border-top: 1px solid var(--color-border);
  align-items: flex-end;
  background: rgba(255, 255, 255, 0.66);
  backdrop-filter: blur(18px);
}

.thinking {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
}

.thinking .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-primary);
  animation: thinking-bounce 1.2s infinite ease-in-out;
}

.thinking .dot:nth-child(2) {
  animation-delay: 0.15s;
}

.thinking .dot:nth-child(3) {
  animation-delay: 0.3s;
}

.thinking-text {
  margin-left: 6px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--color-primary);
  animation: cursor-blink 0.9s step-end infinite;
}

@keyframes thinking-bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }

  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

@keyframes cursor-blink {
  50% {
    opacity: 0;
  }
}


.chat-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 120px 24px 40px;
  text-align: center;
}
.welcome-title {
  margin: 0 0 12px;
  font-size: 28px;
  font-weight: 700;
  background: var(--gradient-primary);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.welcome-desc {
  margin: 0;
  font-size: 15px;
  color: var(--color-text-muted);
  line-height: 1.6;
}
</style>
