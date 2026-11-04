<script setup>
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { ChatDotRound, Document, Lock, Right, Search, User } from "@element-plus/icons-vue";
import { api, setAuth } from "../store";

const router = useRouter();
const loading = ref(false);
const form = reactive({ username: "", password: "" });
const formRef = ref(null);
const year = new Date().getFullYear();

const rules = {
  username: [{ required: true, message: "请输入用户名", trigger: "blur" }],
  password: [{ required: true, message: "请输入密码", trigger: "blur" }],
};

async function submit() {
  await formRef.value.validate();
  loading.value = true;
  try {
    const res = await api.post("/auth/login", form);
    setAuth(res.data.token, res.data.user);
    ElMessage.success("登录成功");
    router.push("/home");
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || "登录失败");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <section class="hero">
      <div class="hero-grid" aria-hidden="true"></div>
      <div class="hero-glow hero-glow-a" aria-hidden="true"></div>
      <div class="hero-glow hero-glow-b" aria-hidden="true"></div>

      <div class="hero-body">
        <div class="brand">
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="20" height="20" fill="none">
              <path d="M16 3.5 27 9.75v12.5L16 28.5 5 22.25V9.75L16 3.5Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
              <path d="M16 10.5v11M11 13.5l10 5M21 13.5l-10 5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
            </svg>
          </span>
          <span class="brand-name">企业智能知识库系统</span>
        </div>

        <p class="eyebrow">ENTERPRISE KNOWLEDGE INTELLIGENCE</p>
        <h1 class="hero-title">让企业知识<br />真正被用起来</h1>
        <p class="hero-desc">基于 RAG 混合检索与多轮对话的企业级知识问答平台，把散落的文档转化为可被随时调用的团队智慧。</p>

        <ul class="features">
          <li>
            <span class="feature-icon"><el-icon><Document /></el-icon></span>
            <div>
              <strong>多知识库管理</strong>
              <span>文档解析、智能分块与向量化一站式完成</span>
            </div>
          </li>
          <li>
            <span class="feature-icon"><el-icon><Search /></el-icon></span>
            <div>
              <strong>混合检索引擎</strong>
              <span>语义向量与关键词融合排序，命中更准</span>
            </div>
          </li>
          <li>
            <span class="feature-icon"><el-icon><ChatDotRound /></el-icon></span>
            <div>
              <strong>多轮对话与引用</strong>
              <span>上下文记忆、自动摘要与来源可追溯</span>
            </div>
          </li>
        </ul>
      </div>

      <p class="hero-foot">© {{ year }} Enterprise Knowledge Intelligence</p>
    </section>

    <section class="panel">
      <div class="mobile-brand">
        <span class="brand-mark small" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="16" height="16" fill="none">
            <path d="M16 3.5 27 9.75v12.5L16 28.5 5 22.25V9.75L16 3.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
            <path d="M16 10.5v11M11 13.5l10 5M21 13.5l-10 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
          </svg>
        </span>
        <span>企业智能知识库系统</span>
      </div>

      <div class="form-wrap">
        <header class="form-head">
          <h2>欢迎回来</h2>
          <p>登录以继续访问您的知识工作台</p>
        </header>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          size="large"
          label-position="top"
          hide-required-asterisk
          class="login-form"
          @keyup.enter="submit"
        >
          <el-form-item label="账号" prop="username">
            <el-input v-model="form.username" placeholder="请输入账号" autocomplete="username">
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              show-password
              autocomplete="current-password"
            >
              <template #prefix>
                <el-icon><Lock /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          <el-button type="primary" class="login-btn" :loading="loading" @click="submit">
            登录
            <el-icon class="btn-icon"><Right /></el-icon>
          </el-button>
        </el-form>
      </div>

      <p class="panel-foot">受企业内网保护 · 请勿共享账号凭证</p>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  min-height: 100vh;
  background: var(--color-bg);
}

/* ---------- Left hero ---------- */
.hero {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
  padding: 56px 64px 40px;
  background: var(--gradient-hero);
  color: var(--color-ink-text);
}

.hero-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(148, 163, 255, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 255, 0.07) 1px, transparent 1px);
  background-size: 56px 56px;
  mask-image: radial-gradient(120% 90% at 20% 0%, #000 25%, transparent 78%);
}

.hero-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  pointer-events: none;
}

.hero-glow-a {
  width: 460px;
  height: 460px;
  top: -140px;
  right: -120px;
  background: radial-gradient(circle, rgba(124, 58, 237, 0.55), transparent 68%);
}

.hero-glow-b {
  width: 420px;
  height: 420px;
  bottom: -160px;
  left: -100px;
  background: radial-gradient(circle, rgba(8, 145, 178, 0.42), transparent 70%);
}

.hero-body {
  position: relative;
  z-index: 1;
  max-width: 520px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 72px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  color: #fff;
  background: var(--gradient-primary);
  box-shadow: 0 10px 30px rgba(90, 60, 255, 0.45);
}

.brand-mark.small {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  box-shadow: none;
}

.brand-name {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.eyebrow {
  margin: 0 0 18px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.32em;
  color: #8b93c9;
}

.hero-title {
  margin: 0 0 20px;
  font-size: clamp(34px, 3.1vw, 48px);
  line-height: 1.16;
  font-weight: 700;
  letter-spacing: -0.01em;
  background: linear-gradient(100deg, #ffffff 12%, #c9c2ff 60%, #8fd8ff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-desc {
  margin: 0 0 44px;
  max-width: 430px;
  font-size: 15px;
  line-height: 1.75;
  color: var(--color-ink-muted);
}

.features {
  display: grid;
  gap: 18px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.features li {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.feature-icon {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 38px;
  height: 38px;
  border-radius: 11px;
  color: #cfc8ff;
  background: rgba(124, 58, 237, 0.16);
  border: 1px solid rgba(148, 140, 255, 0.26);
}

.features strong {
  display: block;
  margin-bottom: 3px;
  font-size: 14px;
  font-weight: 600;
  color: #eef0ff;
}

.features span {
  font-size: 13px;
  line-height: 1.55;
  color: var(--color-ink-muted);
}

.hero-foot {
  position: relative;
  z-index: 1;
  margin: 48px 0 0;
  font-size: 12px;
  color: #6b73a3;
}

/* ---------- Right panel ---------- */
.panel {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 48px clamp(28px, 6vw, 96px);
  background:
    radial-gradient(720px 420px at 100% 0%, rgba(124, 58, 237, 0.08), transparent 60%),
    var(--color-surface-solid);
}

.mobile-brand {
  display: none;
  align-items: center;
  gap: 10px;
  margin-bottom: 40px;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text);
}

.form-wrap {
  width: 100%;
  max-width: 380px;
  margin: 0 auto;
}

.form-head {
  margin-bottom: 30px;
}

.form-head h2 {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--color-text-emphasis);
}

.form-head p {
  margin: 0;
  font-size: 14px;
  color: var(--color-text-muted);
}

.login-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.login-form :deep(.el-input__wrapper) {
  padding: 2px 14px;
  border-radius: var(--radius-lg);
  background: #fafafe;
  box-shadow: inset 0 0 0 1px var(--color-border);
  transition: box-shadow 0.2s ease, background 0.2s ease;
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: inset 0 0 0 1px var(--color-border-accent);
}

.login-form :deep(.el-input__wrapper.is-focus) {
  background: #fff;
  box-shadow: inset 0 0 0 1px var(--color-primary), 0 0 0 4px rgba(124, 58, 237, 0.12);
}

.login-form :deep(.el-input__inner) {
  height: 44px;
  font-size: 14px;
}

.login-form :deep(.el-input__prefix) {
  color: var(--color-text-muted);
}

.login-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.login-btn {
  width: 100%;
  height: 46px;
  margin-top: 6px;
  border: none;
  border-radius: var(--radius-lg);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.02em;
  background: var(--gradient-accent);
  box-shadow: var(--shadow-primary);
  transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease;
}

.login-btn:hover {
  transform: translateY(-1px);
  filter: brightness(1.04);
  box-shadow: 0 20px 40px rgba(78, 52, 255, 0.3);
}

.login-btn:active {
  transform: translateY(0);
}

.btn-icon {
  margin-left: 8px;
}

.panel-foot {
  position: absolute;
  bottom: 24px;
  left: 0;
  right: 0;
  margin: 0;
  text-align: center;
  font-size: 12px;
  color: var(--color-text-muted);
}

@media (max-width: 900px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .hero {
    display: none;
  }

  .mobile-brand {
    display: flex;
  }

  .panel {
    min-height: 100vh;
    justify-content: flex-start;
    padding-top: 56px;
  }
}
</style>
