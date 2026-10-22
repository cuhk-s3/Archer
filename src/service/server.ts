import { createServer, type ServerResponse } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { projectRoot, type ArcherConfig } from "../config.js";
import { ReviewStore } from "./store.js";
import type { ReviewRecord } from "../types.js";

export function startServer(config: ArcherConfig) {
  const store = new ReviewStore(config.outputDir);
  const root = projectRoot;
  const frontend = resolve(root, "service/frontend/index.html");
  const send = (
    response: ServerResponse,
    status: number,
    body: string,
    type = "application/json; charset=utf-8",
  ) => {
    response.writeHead(status, {
      "content-type": type,
      "access-control-allow-origin": "*",
    });
    response.end(body);
  };
  const server = createServer(async (request, response) => {
    const url = new URL(
      request.url ?? "/",
      `http://${request.headers.host ?? "localhost"}`,
    );
    try {
      if (request.method === "OPTIONS") {
        response.writeHead(204, {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET,OPTIONS",
          "access-control-allow-headers": "content-type",
        });
        response.end();
        return;
      }
      if (request.method !== "GET")
        return send(
          response,
          405,
          JSON.stringify({ error: "Method not allowed" }),
        );
      if (url.pathname === "/healthz")
        return send(
          response,
          200,
          JSON.stringify({ ok: true, runtime: "typescript", framework: "pi" }),
        );
      if (url.pathname === "/" || url.pathname === "/index.html")
        return send(
          response,
          200,
          await readFile(frontend, "utf8"),
          "text/html; charset=utf-8",
        );
      if (url.pathname === "/runtime-config.js")
        return send(
          response,
          200,
          'window.ARCHER_BACKEND_BASE_URL = "";',
          "text/javascript; charset=utf-8",
        );
      if (url.pathname === "/logo.png") {
        const logo = await readFile(resolve(root, "service/Archer.png"));
        response.writeHead(200, { "content-type": "image/png" });
        response.end(logo);
        return;
      }
      if (url.pathname === "/api/prs") {
        const records = await store.list();
        const latest = new Map<number, ReviewRecord>();
        for (const record of records)
          if (!latest.has(record.pr.id)) latest.set(record.pr.id, record);
        const prs = [...latest.values()].map((record) => ({
          pr_id: record.pr.id,
          title: record.pr.title,
          outcome: record.evidence.some((item) => item.found) ? "bug" : "clean",
          bug_count: record.evidence.filter((item) => item.found).length,
          fixed_bug_count: 0,
          version_count: new Set(
            records
              .filter((item) => item.pr.id === record.pr.id)
              .map((item) => item.pr.headSha),
          ).size,
          review_count: records.filter((item) => item.pr.id === record.pr.id)
            .length,
          effective_review_count: 1,
          latest_commit: record.pr.headSha,
          components: record.pr.components,
          updated_at: record.finishedAt,
          live: "",
        }));
        return send(response, 200, JSON.stringify({ prs }));
      }
      const reviewMatch = url.pathname.match(/^\/api\/reviews\/([^/]+)$/);
      if (reviewMatch) {
        const record = await store.get(decodeURIComponent(reviewMatch[1]!));
        return record
          ? send(response, 200, JSON.stringify(record))
          : send(response, 404, JSON.stringify({ error: "Review not found" }));
      }
      const prMatch = url.pathname.match(/^\/api\/prs\/(\d+)$/);
      if (prMatch) {
        const records = (await store.list()).filter(
          (item) => item.pr.id === Number(prMatch[1]),
        );
        return records.length
          ? send(
              response,
              200,
              JSON.stringify({ pr: records[0]!.pr, reviews: records }),
            )
          : send(response, 404, JSON.stringify({ error: "PR not found" }));
      }
      const prPage = url.pathname.match(/^\/pr\/(\d+)$/);
      if (prPage) {
        const records = (await store.list()).filter(
          (item) => item.pr.id === Number(prPage[1]),
        );
        if (!records.length)
          return send(response, 404, JSON.stringify({ error: "PR not found" }));
        return send(
          response,
          200,
          page(
            records[0]!.pr.title,
            records
              .map(
                (r) =>
                  `<p><a href="/review/${encodeURIComponent(r.id)}">${escapeHtml(r.finishedAt)} · ${escapeHtml(r.pr.headSha.slice(0, 12))}</a></p>`,
              )
              .join(""),
          ),
          "text/html; charset=utf-8",
        );
      }
      const reviewPage = url.pathname.match(/^\/review\/([^/]+)$/);
      if (reviewPage) {
        const record = await store.get(decodeURIComponent(reviewPage[1]!));
        if (!record)
          return send(
            response,
            404,
            JSON.stringify({ error: "Review not found" }),
          );
        return send(
          response,
          200,
          page(
            record.pr.title,
            `<pre>${escapeHtml(record.report)}</pre><h2>Test evidence</h2><pre>${escapeHtml(JSON.stringify(record.evidence, null, 2))}</pre>`,
          ),
          "text/html; charset=utf-8",
        );
      }
      return send(response, 404, JSON.stringify({ error: "Not found" }));
    } catch (error) {
      console.error(error);
      return send(
        response,
        500,
        JSON.stringify({
          error: error instanceof Error ? error.message : String(error),
        }),
      );
    }
  });
  server.listen(config.port, config.host, () =>
    console.log(
      `Archer review board listening at http://${config.host}:${config.port}`,
    ),
  );
  return server;
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ]!,
  );
}

function page(title: string, body: string): string {
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${escapeHtml(title)}</title><style>body{max-width:1100px;margin:40px auto;padding:0 20px;font:16px/1.6 system-ui;color:#172033}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:20px}a{color:#2458a8}</style><a href="/">← Review board</a><h1>${escapeHtml(title)}</h1>${body}</html>`;
}
