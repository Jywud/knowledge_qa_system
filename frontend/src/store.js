import { ref } from "vue";
import axios from "axios";

export const api = axios.create({ baseURL: "/api", timeout: 120000 });

export const token = ref(localStorage.getItem("kqa_token") || "");

export const user = ref(JSON.parse(localStorage.getItem("kqa_user") || "null"));

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
  user.value = newUser;
  localStorage.setItem("kqa_token", newToken);
  localStorage.setItem("kqa_user", JSON.stringify(newUser));
}

export function clearAuth() {
  token.value = "";
  user.value = null;
  conversations.value = [];
  currentConversationId.value = null;
  selectedKb.value = null;
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
}
