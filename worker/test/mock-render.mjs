// Faux service Render pour tester le Worker en local, sans base de données.
// Usage : node test/mock-render.mjs [port] [mode]
//   mode = ok       -> répond 200 immédiatement
//   mode = cold     -> la 1re requête renvoie 502 (Render qui se réveille), les suivantes 200
//   mode = down     -> renvoie toujours 503
// Le secret attendu est "dev-secret" (le même que dans .dev.vars).
import http from "node:http";

const port = Number(process.argv[2] || 8001);
const mode = process.argv[3] || "ok";
const SECRET = "dev-secret";
let calls = 0;
let closedOnce = false; // simule l'idempotence : la 2e clôture ne ferme plus rien

http
  .createServer((req, res) => {
    if (req.method === "GET" && req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end('{"status":"ok"}');
    }
    if (req.method === "POST" && req.url === "/internal/close") {
      calls++;
      const auth = req.headers.authorization || "";
      console.log(`[mock] appel #${calls} — Authorization: ${auth ? "présent" : "absent"}`);
      if (auth !== `Bearer ${SECRET}`) {
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
  .listen(port, () => console.log(`[mock] Render simulé sur http://localhost:${port} (mode ${mode})`));
