import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(fileURLToPath(new URL(".", import.meta.url)), "dist");
const args = process.argv.slice(2);
const port = Number(args[args.indexOf("--port") + 1] || process.env.PORT || 4173);
const host = args[args.indexOf("--host") + 1] || "127.0.0.1";
const contentTypes = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon" };

createServer(async (request, response) => {
  try {
    const pathOnly = (request.url || "/").split("?", 1)[0];
    const requested = normalize(join(root, pathOnly === "/" ? "index.html" : pathOnly));
    const file = requested === root || requested.startsWith(`${root}${sep}`) ? requested : join(root, "index.html");
    await stat(file);
    response.writeHead(200, { "Content-Type": contentTypes[extname(file)] || "application/octet-stream" });
    response.end(await readFile(file));
  } catch {
    try { response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }); response.end(await readFile(join(root, "index.html"))); }
    catch { response.writeHead(503); response.end("frontend build is missing; run npm run build"); }
  }
}).listen(port, host, () => console.log(`nano-vibe frontend listening on http://${host}:${port}`));
