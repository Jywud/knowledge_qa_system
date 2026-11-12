<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { renderMarkdown } from "../utils/markdown";
import { Collection, Loading, Top } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import {
  api,
  conversations,
  currentConversationId,
  loadConversations,
  loadKnowledgeBases,
  refreshUser,
  token,
  selectedKb,
  knowledgeBases,
  clearAuth,
} from "../store";

const router = useRouter();
const messages = ref([]);
const input = ref("");
const sending = ref(false);
const kbLocked = computed(() => currentConversationId.value !== null);
const hasAvailableContent = computed(() => knowledgeBases.value.some(
  (kb) => kbSelectable(kb) && (selectedKb.value === null || kb.id === selectedKb.value)
));

function selectScope(value) {
  selectedKb.value = value === "all" ? null : value;
}

function kbSelectable(kb) {
  return kb.chunk_count > 0;
}

function kbLabel(kb) {
  return kbSelectable(kb) ? kb.name : `${kb.name}（暂无文档）`;
}
const THINKING_STEPS = ["正在检索知识库…", "正在整理相关内容…", "AI 正在思考中…"];
const sourceDialog = reactive({ visible: false, source: "", kbName: "", items: [] });
let locallyCreatedConversationId = null;

function normalizeSources(value) {
  if (typeof value === "string") {
    try { value = JSON.parse(value); } catch { return []; }
  }
  if (!Array.isArray(value)) return [];
  return value.filter((entry) => entry && (typeof entry === "object" || typeof entry === "string"))
    .map((entry) => {
      const group = typeof entry === "string" ? { source: "历史引用", excerpt: entry } : entry;
      const raw = Array.isArray(group.excerpts) && group.excerpts.length ? group.excerpts : [group];
      return {
        ...group,
        source: typeof group.source === "string" ? group.source : "历史引用",
        excerpts: raw.map((excerpt, index) => {
          const item = typeof excerpt === "string" ? { text: excerpt } : excerpt || {};
          return {
            ...item,
            index: item.index ?? group.index ?? index + 1,
            chunk_id: item.chunk_id,
            file_id: item.file_id ?? group.file_id,
            file_version: item.file_version ?? group.file_version,
            text: typeof item.text === "string" ? item.text : typeof item.excerpt === "string" ? item.excerpt : "",
          };
        }),
      };
    });
}

function sourceId(value) {
  if (typeof value !== "number" && !(typeof value === "string" && /^\d+$/.test(value))) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

async function loadSourceItem(item) {
  item.content = "";
  item.error = "";
  item.notice = "";
  if (!item.chunk_id || !item.file_id || !item.file_version) {
    item.notice = item.text ? "历史引用未保存精确位置，仅展示当时保存的摘要。"
      : "这条历史引用没有保存原文片段，无法精确定位。";
    return;
  }
  item.loading = true;
  try {
    const { data } = await api.get(`/chunks/${item.chunk_id}`, {
      params: { file_id: item.file_id, version: item.file_version }, timeout: 15000,
    });
    if (sourceId(data?.id) !== item.chunk_id || sourceId(data?.file_id) !== item.file_id
        || sourceId(data?.file_version) !== item.file_version || typeof data?.content !== "string") {
      item.error = "返回的原文与引用信息不符，此引用已失效。";
      return;
    }
    item.content = data.content;
    item.page_no = data.page_no;
    item.file_type = data.file_type;
  } catch (error) {
    const status = error.response?.status;
    if (status === 401) {
      item.error = "登录已过期，请重新登录";
      handleUnauthorized(item.error);
    } else if (status === 403) item.error = "没有权限查看该引用";
    else if (status === 404) item.error = "原文片段已不存在，文件可能已更新或删除。";
    else if (status === 410) item.error = "原文件已更新，此引用已失效。";
    else item.error = "原文加载失败，请稍后重试。";
    if (status === 403 || status === 404) await refreshAccess();
  } finally {
    item.loading = false;
  }
}

async function openSourceDialog(source) {
  const group = normalizeSources([source])[0];
  sourceDialog.source = group?.source || "引用原文";
  sourceDialog.kbName = group?.kb_name || "";
  sourceDialog.items = (group?.excerpts || []).map((item) => ({
    ...item,
    chunk_id: sourceId(item.chunk_id), file_id: sourceId(item.file_id),
    file_version: sourceId(item.file_version), content: "", loading: false, error: "", notice: "",
  }));
  sourceDialog.visible = true;
  // 每次打开重取单块；响应只更新本次的 item，不能覆盖后来打开的弹窗。
  await Promise.all(sourceDialog.items.map((item) => loadSourceItem(item)));
}
const msgListRef = ref(null);

const canSend = computed(() => Boolean(input.value.trim() && hasAvailableContent.value && !sending.value));
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

async function refreshAccess() {
  // 刷新授权不会切换当前会话，避免覆盖仍在显示的回答或历史。
  await Promise.allSettled([loadKnowledgeBases(), refreshUser()]);
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
      sources: normalizeSources(m.sources),
      done: true,
    }));
    scrollBottom();
  } catch (error) {
    const message = requestErrorMessage(error.response?.status, error.response?.data?.detail);
    if (error.response?.status === 401) handleUnauthorized(message);
    else if (currentConversationId.value === id) ElMessage.error(message);
    if ([403, 404].includes(error.response?.status)) await refreshAccess();
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
  if (!hasAvailableContent.value) {
    ElMessage.warning(knowledgeBases.value.length ? "当前范围暂无可用文档，请联系管理员上传" : "暂无可访问的知识库，请联系管理员分配角色");
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
          assistant.sources = normalizeSources(evt.sources);
        } else if (evt.type === "error") {
          assistant.content += `\n[错误] ${evt.message}`;
          if ([403, 404].includes(evt.status) || evt.code === "permission_revoked") await refreshAccess();
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
    if (status === 403 || status === 404) await refreshAccess();
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
          <p class="welcome-desc">{{ currentConversationId ? '输入问题，AI 将基于本次会话的知识库范围为您解答' : '直接提问，AI 将检索全部可访问知识库；也可在左下角限定范围' }}</p>
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
                :key="s.file_id != null ? s.file_id + ':' + s.file_version : s.index ?? s.source"
                size="small"
                type="info"
                class="source-tag"
                @click="openSourceDialog(s)"
              >
                <span class="source-label">
                  {{ s.source }}<span v-if="s.count > 1" class="source-count"> ×{{ s.count }}</span>
                  <span v-if="s.kb_name" class="source-extra">{{ s.kb_name }}</span>
                  <span v-if="s.file_type" class="source-extra">{{ s.file_type }}</span>
                </span>
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <div class="input-area">
        <div class="composer">
          <el-input
            v-model="input"
            class="composer-input"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 8 }"
            resize="none"
            :disabled="sending"
            aria-label="问题输入"
            :placeholder="knowledgeBases.length ? '输入问题，Ctrl+Enter 发送' : '暂无可访问的知识库，请联系管理员'"
            @keydown.ctrl.enter.prevent="send"
          />
          <div class="composer-toolbar">
            <el-tooltip content="会话范围已固定，切换范围请新建对话" placement="top" :disabled="!kbLocked">
              <div class="kb-control">
                <el-select
                  :model-value="selectedKb ?? 'all'"
                  @update:model-value="selectScope"
                  class="composer-kb-select"
                  :disabled="kbLocked || sending"
                  aria-label="选择知识库"
                  placeholder="全部可访问知识库"
                >
                  <template #prefix><el-icon><Collection /></el-icon></template>
                  <el-option label="全部可访问知识库" value="all" />
                  <el-option
                    v-for="kb in knowledgeBases"
                    :key="kb.id"
                    :label="kbLabel(kb)"
                    :value="kb.id"
                    :disabled="!kbSelectable(kb)"
                  />
                </el-select>
              </div>
            </el-tooltip>
            <el-button
              class="composer-send"
              type="primary"
              circle
              :loading="sending"
              :icon="Top"
              :disabled="!canSend"
              :aria-label="sending ? '正在发送' : '发送'"
              :title="sending ? '正在生成回答' : '发送（Ctrl+Enter）'"
              @click="send"
            />
          </div>
        </div>
      </div>

      <el-dialog v-model="sourceDialog.visible" :title="sourceDialog.source" width="min(840px, calc(100vw - 32px))">
        <p v-if="sourceDialog.kbName" class="source-note">知识库：{{ sourceDialog.kbName }}</p>
        <div v-for="(item, position) in sourceDialog.items" :key="position" class="source-item">
          <div class="source-item-title">
            来源{{ item.index ?? position + 1 }}
            <span v-if="item.file_version" class="source-extra">v{{ item.file_version }}</span>
            <span v-if="item.file_type === 'pdf' && item.page_no != null" class="source-extra">第 {{ item.page_no + 1 }} 页</span>
          </div>
          <div v-if="item.loading" class="source-note" role="status">
            <el-icon class="is-loading"><Loading /></el-icon> 正在加载原文…
          </div>
          <div v-if="item.error" class="source-error" role="alert">
            {{ item.error }}
            <el-button link type="primary" size="small" :disabled="item.loading" @click="loadSourceItem(item)">重试</el-button>
          </div>
          <div v-if="item.notice" class="source-note">{{ item.notice }}</div>
          <div v-if="!item.content && item.text" class="source-note">当时保存的引用摘要</div>
          <div v-if="item.content || item.text" class="source-item-content">{{ item.content || item.text }}</div>
          <div v-else-if="!item.loading" class="source-note">暂无可展示的原文内容</div>
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

.markdown-body :deep(.citation-badge) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 19px;
  height: 19px;
  padding: 0 5px;
  margin: 0 3px;
  border: 1px solid var(--color-border-accent);
  border-radius: 6px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  vertical-align: 0.3em;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
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

.source-note {
  margin: 6px 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.source-error {
  margin: 6px 0;
  color: var(--color-danger);
  font-size: 13px;
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
  flex-shrink: 0;
  padding: 12px 24px 24px;
}

.composer {
  width: 100%;
  max-width: 960px;
  margin: 0 auto;
  padding: 14px 16px 12px;
  border: 1px solid var(--color-border);
  border-radius: 24px;
  background: var(--color-surface-solid);
  box-shadow: var(--shadow-dialog);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.composer:focus-within {
  border-color: var(--color-border-accent);
  box-shadow: 0 0 0 3px var(--color-primary-soft), var(--shadow-dialog);
}

.composer-input :deep(.el-textarea__inner) {
  padding: 4px 6px 12px;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  font-size: 16px;
  line-height: 1.6;
}

.composer-input :deep(.el-textarea__inner:focus),
.composer-input :deep(.el-textarea__inner:hover) {
  box-shadow: none;
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
}

.kb-control {
  flex: 0 1 260px;
  min-width: 0;
}

.composer-kb-select {
  width: 100%;
}

.composer-kb-select :deep(.el-select__wrapper) {
  min-height: 36px;
  padding: 4px 12px;
  border-radius: 18px;
  background: var(--color-surface-solid);
}

.composer-send {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  margin-left: auto;
  font-size: 22px;
}

@media (max-width: 640px) {
  .input-area {
    padding: 10px 12px 16px;
  }

  .composer {
    padding: 12px;
    border-radius: var(--radius-xl);
  }
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
