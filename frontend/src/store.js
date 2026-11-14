import { ref } from "vue";
import axios from "axios";

export const api = axios.create({ baseURL: "/api", timeout: 120000 });

export const token = ref(localStorage.getItem("kqa_token") || "");

function publicUser(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return {
    id: value.id, username: value.username, is_admin: value.is_admin === true,
    roles: Array.isArray(value.roles) ? value.roles.map(({ id, name, system_key }) => ({ id, name, system_key })) : [],
  };
}

// 浏览器缓存不能作为权限来源；启动后通过 /auth/me 重新确认身份。
localStorage.removeItem("kqa_user");
export const user = ref(null);

export async function refreshUser() {
  const { data } = await api.get("/auth/me");
  user.value = publicUser(data);
  localStorage.setItem("kqa_user", JSON.stringify(user.value));
  return user.value;
}

// 本次页面会话已确认过身份时直接复用，避免守卫与布局各调一次 /auth/me；
// 角色变更后需要强制刷新时仍用 refreshUser()。
export async function ensureUser() {
  if (!user.value) await refreshUser();
  return user.value;
}

export const conversations = ref([]);

export const currentConversationId = ref(null);

export const selectedKb = ref(null);

export const knowledgeBases = ref([]);

api.interceptors.request.use((config) => {
  if (token.value) config.headers.Authorization = `Bearer ${token.value}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) clearAuth();
    return Promise.reject(err);
  }
);

export function setAuth(newToken, newUser) {
  token.value = newToken;
  user.value = publicUser(newUser);
  localStorage.setItem("kqa_token", newToken);
  localStorage.setItem("kqa_user", JSON.stringify(user.value));
}

export function clearAuth() {
  token.value = "";
  user.value = null;
  conversations.value = [];
  currentConversationId.value = null;
  selectedKb.value = null;
  knowledgeBases.value = [];
  localStorage.removeItem("kqa_token");
  localStorage.removeItem("kqa_user");
}

export async function loadConversations() {
  if (!token.value) return;
  const res = await api.get("/conversations");
  conversations.value = res.data;
}

export async function loadKnowledgeBases(name = "") {
  if (!token.value) return;
  const res = await api.get("/knowledge-bases", { params: name ? { name } : {} });
  knowledgeBases.value = res.data;
  if (!name && selectedKb.value && !res.data.some((kb) => kb.id === selectedKb.value)) {
    selectedKb.value = null;
  }
}
