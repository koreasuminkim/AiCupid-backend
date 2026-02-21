import "dotenv/config";
import express from "express";
import cors from "cors";
import http from "http";
import { WebSocketServer } from "ws";
import { initDB } from "./db";
import { handleConnection } from "./ws-handler";

if (!process.env.GEMINI_API_KEY || process.env.GEMINI_API_KEY === "your_gemini_api_key_here") {
  console.error("[Error] GEMINI_API_KEY is not set in .env");
  process.exit(1);
}

const PORT = Number(process.env.PORT ?? 8080);

// ── Init SQLite ───────────────────────────────────────────
initDB();

// ── Express app ───────────────────────────────────────────
const app = express();
app.use(cors({ origin: process.env.FRONTEND_ORIGIN ?? "http://localhost:3000" }));
app.use(express.json({ limit: "50mb" })); // audio payloads can be large

app.get("/health", (_req, res) => {
  res.json({ status: "ok", timestamp: new Date().toISOString() });
});

// ── HTTP + WebSocket server ───────────────────────────────
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

wss.on("connection", (ws) => {
  handleConnection(ws);
});

server.listen(PORT, () => {
  console.log(`[Server] HTTP  → http://localhost:${PORT}/health`);
  console.log(`[Server] WS   → ws://localhost:${PORT}`);
});
