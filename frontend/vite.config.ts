import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  // 위키 인증 프록시(yongs-wiki.com/herongs)와 Tailscale 직접 접속이 같은 경로를 쓴다 (DCR-005)
  base: "/herongs/",
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "HERONGS",
        short_name: "HERONGS",
        description: "주식 조회·추천·매매",
        theme_color: "#111827",
        background_color: "#111827",
        display: "standalone",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
    }),
  ],
  server: {
    proxy: { "/herongs/api": "http://localhost:8000" },
  },
});
