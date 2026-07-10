import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy API sang Django dev server
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Proxy WebSocket real-time (deployment/job live update) sang backend ASGI (uvicorn).
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
