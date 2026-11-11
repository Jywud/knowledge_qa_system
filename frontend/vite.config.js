import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        configure(proxy) {
          proxy.on("proxyReq", (proxyReq, req) => {
            const source = req.socket.remoteAddress || "unknown";
            proxyReq.setHeader("X-Forwarded-For", source);
            proxyReq.setHeader("X-Real-IP", source);
          });
        },
      },
    },
  },
});
