import { createRouter, createWebHistory } from "vue-router";
import AppLayout from "../components/AppLayout.vue";
import { token } from "../store";

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
        { path: "users", component: () => import("../views/UserManage.vue") },
        { path: "settings", component: () => import("../views/SystemSettings.vue") },
      ],
    },
    { path: "/home", component: () => import("../views/HomeView.vue") },
    { path: "/login", component: () => import("../views/Login.vue") },
  ],
});

router.beforeEach((to) => {
  const isLogin = !!token.value;
  if (to.path === "/login") return isLogin ? "/chat" : true;
  return isLogin ? true : "/login";
});

export default router;
