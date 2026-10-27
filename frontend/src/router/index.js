import { createRouter, createWebHistory } from "vue-router";
import AppLayout from "../components/AppLayout.vue";
import Login from "../views/Login.vue";
import HomeView from "../views/HomeView.vue";
import ChatView from "../views/ChatView.vue";
import FileManager from "../views/FileManager.vue";
import KnowledgeBases from "../views/KnowledgeBases.vue";
import UserManage from "../views/UserManage.vue";
import SystemSettings from "../views/SystemSettings.vue";
import { token } from "../store";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: AppLayout,
      children: [
        { path: "", redirect: "/home" },
        { path: "chat", component: ChatView },
        { path: "knowledge-bases", component: KnowledgeBases },
        { path: "files", component: FileManager },
        { path: "users", component: UserManage },
        { path: "settings", component: SystemSettings },
      ],
    },
    { path: "/home", component: HomeView },
    { path: "/login", component: Login },
  ],
});

router.beforeEach((to) => {
  const isLogin = !!token.value;
  if (to.path === "/login") return isLogin ? "/chat" : true;
  return isLogin ? true : "/login";
});

export default router;
