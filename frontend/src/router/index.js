import { createRouter, createWebHistory } from "vue-router";
import AppLayout from "../components/AppLayout.vue";
import { token, user, refreshUser, clearAuth } from "../store";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: AppLayout,
      children: [
        { path: "", redirect: "/home" },
        { path: "chat", component: () => import("../views/ChatView.vue") },
        { path: "knowledge-bases", component: () => import("../views/KnowledgeBases.vue") },
        { path: "files", component: () => import("../views/FileManager.vue") },
        { path: "roles", meta: { admin: true }, component: () => import("../views/RoleManage.vue") },
        { path: "users", meta: { admin: true }, component: () => import("../views/UserManage.vue") },
        { path: "settings", meta: { admin: true }, component: () => import("../views/SystemSettings.vue") },
      ],
    },
    { path: "/home", component: () => import("../views/HomeView.vue") },
    { path: "/login", component: () => import("../views/Login.vue") },
  ],
});

router.beforeEach(async (to) => {
  const isLogin = !!token.value;
  if (to.path === "/login") return isLogin ? "/chat" : true;
  if (!isLogin) return "/login";
  if (!user.value) {
    try { await refreshUser(); } catch { clearAuth(); return "/login"; }
  }
  if (to.meta.admin && !user.value?.is_admin) return "/chat";
  return true;
});

export default router;
