<script setup>
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { ArrowRight, ChatDotRound, Collection, FolderOpened, Grid } from "@element-plus/icons-vue";
import {
  conversations,
  currentConversationId,
  knowledgeBases,
  loadConversations,
  loadKnowledgeBases,
  user,
} from "../store";

const router = useRouter();

const kbCount = computed(() => knowledgeBases.value.length);
const docCount = computed(() => knowledgeBases.value.reduce((sum, kb) => sum + kb.file_count, 0));
const chunkCount = computed(() => knowledgeBases.value.reduce((sum, kb) => sum + kb.chunk_count, 0));
const recentConversations = computed(() => conversations.value.slice(0, 3));

function goChat() {
  router.push("/chat");
}

function goKnowledgeBases() {
  router.push("/knowledge-bases");
}

function openConversation(id) {
  currentConversationId.value = id;
  router.push("/chat");
}

function kbName(kbId) {
  if (!kbId) return "全部知识库";
  return knowledgeBases.value.find((kb) => kb.id === kbId)?.name ?? "未知知识库";
}

onMounted(async () => {
  await Promise.all([loadConversations(), loadKnowledgeBases()]);
});
</script>

<template>
  <div class="home">
    <div class="background"></div>
    <div class="pattern"></div>
    <header class="topbar">
      <div class="brand">✦ 企业知识库</div>
      <div class="topbar-actions">
        <button class="top-link" type="button" @click="goChat"><el-icon><ChatDotRound /></el-icon>对话问答</button>
        <button class="top-link" type="button" @click="goKnowledgeBases"><el-icon><Collection /></el-icon>知识库</button>
        <div v-if="user" class="top-user">{{ user.username[0] }}</div>
      </div>
    </header>
    <div class="content">
      <section class="hero">
        <div class="hero-text">
          <span class="pill">✦ 企业知识问答平台</span>
          <h1>把分散的知识<br />变成 <span class="highlight">一次提问</span></h1>
          <p>从制度手册到技术文档，统一入库、智能检索、流式回答。支持多知识库切换与完整对话记忆。</p>
          <div class="actions">
            <button class="btn primary" type="button" @click="goChat"><el-icon><ChatDotRound /></el-icon>立即开始</button>
            <button class="btn ghost" type="button" @click="goKnowledgeBases"><el-icon><FolderOpened /></el-icon>查看知识库</button>
          </div>
          <div class="metrics">
            <div class="metric"><strong>{{ kbCount }}</strong><span>知识库</span></div>
            <div class="metric"><strong>{{ docCount }}</strong><span>文档</span></div>
            <div class="metric"><strong>{{ chunkCount }}</strong><span>知识分块</span></div>
            <div class="metric"><strong>{{ conversations.length }}</strong><span>会话</span></div>
          </div>
        </div>
        <div class="preview">
          <div class="preview-header">
            <strong>智能问答预览</strong>
            <span>流式生成</span>
          </div>
          <div class="chat">
            <div class="message question">新版合同审批流程中财务的职责是什么？</div>
            <div class="message answer">
              财务需完成合同金额复核与付款方式确认，随后同步至审批链路。
              <div class="sources"><span>合同管理规范.docx</span><span>财务制度.md</span></div>
            </div>
          </div>
        </div>
      </section>

      <section class="features">
        <div class="feature">
          <div class="icon"><el-icon><Grid /></el-icon></div>
          <h3>多库隔离</h3>
          <p>不同知识库独立入库与召回，问答范围始终清晰。</p>
        </div>
        <div class="feature">
          <div class="icon">⚡</div>
          <h3>流式回答</h3>
          <p>实时输出答案内容，首字响应更快，阅读体验流畅。</p>
        </div>
        <div class="feature">
          <div class="icon">🧭</div>
          <h3>答案溯源</h3>
          <p>自动引用命中的文档与分块，方便核对原始信息。</p>
        </div>
      </section>

      <section class="recent">
        <div class="recent-header">
          <h2>最近会话</h2>
          <button class="btn ghost" type="button" @click="goChat"><el-icon><ArrowRight /></el-icon>进入对话</button>
        </div>
        <div class="conversation-list">
          <div
            v-for="conversation in recentConversations"
            :key="conversation.id"
            class="conversation"
            @click="openConversation(conversation.id)"
          >
            <div class="conversation-title">{{ conversation.title }}</div>
            <div class="conversation-meta">{{ kbName(conversation.kb_id) }}</div>
          </div>
          <div v-if="!recentConversations.length" class="empty">暂无会话，开始你的第一次提问吧</div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.home {
  position: relative;
  min-height: 100vh;
  color: var(--color-text);
  background: var(--color-bg);
  overflow: auto;
}

.background,
.pattern {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.topbar {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 36px 0;
}

.brand {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.top-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  border: 1px solid var(--color-border-accent);
  border-radius: 99px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.top-link:hover {
  color: var(--color-primary);
}

.top-user {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--gradient-primary);
  color: var(--color-on-primary);
  font-weight: 700;
}

.background {
  background:
    radial-gradient(640px 420px at 16% 8%, var(--color-mesh-purple), transparent),
    radial-gradient(760px 500px at 76% 20%, var(--color-mesh-blue), transparent),
    radial-gradient(640px 620px at 55% 96%, var(--color-mesh-pink), transparent);
  filter: blur(18px);
}

.pattern {
  background-image: radial-gradient(var(--color-pattern-dot) 1px, transparent 1px);
  background-size: 22px 22px;
}

.content {
  position: relative;
  max-width: 1180px;
  margin: 0 auto;
  padding: 48px 36px 72px;
}

.hero {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 48px;
  align-items: center;
}

.pill {
  display: inline-flex;
  padding: 9px 15px;
  border: 1px solid var(--color-surface);
  border-radius: 99px;
  background: var(--color-surface);
  color: var(--color-primary);
  font-size: 13px;
  font-weight: 650;
}

h1 {
  margin: 26px 0 20px;
  font-size: 52px;
  line-height: 1.1;
  letter-spacing: -0.04em;
}

.highlight {
  background: var(--gradient-accent);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.hero-text p {
  max-width: 540px;
  color: var(--color-text-secondary);
  font-size: 17px;
  line-height: 1.7;
}

.actions {
  display: flex;
  gap: 14px;
  margin: 28px 0;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 0 24px;
  border: 0;
  border-radius: 12px;
  font-size: 15px;
  cursor: pointer;
}

.btn.primary {
  background: var(--gradient-primary);
  color: var(--color-on-primary);
  box-shadow: var(--shadow-primary);
}

.btn.ghost {
  border: 1px solid var(--color-border-accent);
  background: var(--color-surface);
  color: var(--color-text-emphasis);
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.metric,
.preview,
.feature,
.conversation {
  border: 1px solid var(--color-surface);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(22px);
}

.metric {
  padding: 18px;
  border-radius: 18px;
}

.metric strong {
  display: block;
  font-size: 28px;
  letter-spacing: -0.03em;
}

.metric span {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.preview {
  padding: 24px;
  border-radius: 24px;
  transform: rotate(1deg);
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.preview-header span {
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
}

.chat {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 22px;
}

.message {
  max-width: 88%;
  padding: 14px 16px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.6;
}

.question {
  align-self: flex-end;
  background: var(--color-text);
  color: var(--color-on-primary);
  border-bottom-right-radius: 6px;
}

.answer {
  background: var(--color-surface);
  color: var(--color-text-secondary);
  border-bottom-left-radius: 6px;
}

.sources {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.sources span {
  padding: 4px 8px;
  border-radius: 7px;
  background: var(--color-surface-solid);
  color: var(--color-text-secondary);
  font-size: 12px;
}

.features {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
  margin: 56px 0;
}

.feature {
  padding: 30px;
  border-radius: 24px;
}

.icon {
  display: grid;
  place-items: center;
  width: 62px;
  height: 62px;
  margin-bottom: 22px;
  border-radius: 20px;
  font-size: 28px;
  background: linear-gradient(135deg, var(--color-primary-soft), var(--color-primary-blue-soft));
  color: var(--color-primary);
  box-shadow: 0 10px 22px rgba(124, 58, 237, 0.12);
}

.feature h3 {
  margin-bottom: 10px;
  font-size: 22px;
  letter-spacing: -0.02em;
}

.feature p,
.conversation-meta {
  color: var(--color-text-secondary);
  font-size: 15px;
  line-height: 1.6;
}

.recent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

.recent-header h2 {
  font-size: 28px;
  letter-spacing: -0.03em;
}

.conversation-list {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.conversation {
  padding: 22px;
  border-radius: 20px;
  cursor: pointer;
}

.conversation:hover {
  transform: translateY(-2px);
}

.conversation-title {
  margin-bottom: 8px;
  font-weight: 700;
}

.empty {
  grid-column: 1 / -1;
  padding: 32px;
  border: 1px dashed var(--color-border-accent);
  border-radius: 20px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  text-align: center;
}

@media (max-width: 900px) {
  .hero {
    grid-template-columns: 1fr;
  }

  .features,
  .conversation-list {
    grid-template-columns: 1fr;
  }
}
</style>
