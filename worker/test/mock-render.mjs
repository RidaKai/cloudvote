// Faux Render pour tester en local.
// Usage : node test/mock-render.mjs [port] [ok|cold|down]
import http from "node:http";

const port = Number(process.argv[2] || 8001);
const mode = process.argv[3] || "ok";
const SECRET = "dev-secret";
let calls = 0;
let closedOnce = false; // simule l'idempotence

http
  .createServer((req, res) => {
    if (req.method === "GET" && req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end('{"status":"ok"}');
    }
    if (req.method === "POST" && req.url === "/internal/close") {
      calls++;
      console.log(`[mock] appel #${calls}`);
      if (req.headers.authorization !== `Bearer ${SECRET}`) {
        res.writeHead(401, { "Content-Type": "application/json" });
        return res.end('{"detail":"Unauthorized"}');
      }
      if (mode === "down" || (mode === "cold" && calls === 1)) {
        res.writeHead(mode === "down" ? 503 : 502);
        return res.end("Service waking up");
      }
      const body = closedOnce
        ? '{"closed_positions": 0, "closed_elections": 0}'
        : '{"closed_positions": 3, "closed_elections": 1}';
      closedOnce = true;
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(body);
    }
    res.writeHead(404);
    res.end();
  })
  .listen(port, () => console.log(`[mock] http://localhost:${port} (${mode})`));
