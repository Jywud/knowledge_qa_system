<script setup>
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { Right } from "@element-plus/icons-vue";
import { api, setAuth } from "../store";

const router = useRouter();
const loading = ref(false);
const form = reactive({ username: "", password: "" });
const formRef = ref(null);

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
    <div class="login-card">
      <h2 class="title">企业知识库问答系统</h2>
      <p class="subtitle">请使用账号密码登录</p>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" autocomplete="username" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" class="login-btn" :loading="loading" :icon="Right" @click="submit">
            登 录
          </el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--color-bg) 100%);
}

.login-card {
  width: 380px;
  padding: 40px 36px;
  background: var(--color-surface-solid);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-dialog);
}

.title {
  text-align: center;
  margin: 0 0 4px;
  font-size: 22px;
}

.subtitle {
  text-align: center;
  color: var(--color-text-muted);
  margin: 0 0 28px;
  font-size: 14px;
}

.login-btn {
  width: 100%;
}
</style>
