<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import MarkdownIt from "markdown-it";
import { Promotion } from "@element-plus/icons-vue";
import {
  api,
  conversations,
  currentConversationId,
  loadConversations,
  token,
  selectedKb,
} from "../store";

const messages = ref([]);
const input = ref("");
const sending = ref(false);
const THINKING_STEPS = ["正在检索知识库…", "正在整理相关内容…", "AI 正在思考中…"];
const sourceDialog = reactive({ visible: false, source: "", items: [] });
const chunkCache = {};

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

async function selectConversation(id) {
  if (!id) {
    messages.value = [];
    return;
  }
  const res = await api.get(`/conversations/${id}/messages`);
  messages.value = res.data.map((m) => ({
    role: m.role,
    content: m.content,
    sources: m.sources ? JSON.parse(m.sources) : [],
    done: true,
  }));
  scrollBottom();
}

watch(currentConversationId, selectConversation, { immediate: true });

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
  input.value = "";
  let convId = currentConversationId.value;
  const isNew = !convId;
  if (isNew) {
    const res = await api.post("/conversations", { kb_id: selectedKb.value });
    convId = res.data.id;
    conversations.value.unshift(res.data);
  }
  messages.value.push({ role: "user", content });
  const assistant = reactive({
    role: "assistant",
    content: "",
    sources: [],
    done: false,
    status: THINKING_STEPS[0],
  });
  messages.value.push(assistant);
  sending.value = true;
  scrollBottom();
  const thinkingTimer = setInterval(() => {
    if (assistant.content) return;
    const next = THINKING_STEPS.indexOf(assistant.status) + 1;
    if (next < THINKING_STEPS.length) assistant.status = THINKING_STEPS[next];
  }, 3500);

  try {
    const res = await fetch(`/api/conversations/${convId}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token.value}`,
      },
      body: JSON.stringify({ content }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
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
        }
      }
    }
  } catch (e) {
    assistant.content += `\n[请求失败] ${e.message}`;
  } finally {
    clearInterval(thinkingTimer);
    assistant.done = true;
    sending.value = false;
    if (isNew) currentConversationId.value = convId;
    loadConversations();
  }
}
</script>

<template>
  <div class="chat-layout">
    <div class="chat-area">
      <div ref="msgListRef" class="msg-list">
        <el-empty
          v-if="!messages.length"
          :description="currentConversationId ? '暂无消息，输入问题开始对话' : '输入问题即可开始对话'"
        />
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

</style>
