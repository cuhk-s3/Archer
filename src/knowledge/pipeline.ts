import { publishPassKnowledge } from "./publication.js";
import { atomicJson, digest } from "../infra/artifacts.js";
import { appendFile, mkdir, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import type { ArcherConfig } from "../config.js";
import {
  historyRoot,
  ensureCorpusScope,
  inCorpusRange,
  loadCorpusSelection,
} from "./corpus.js";
import { screenUnrelatedHistory } from "./acquisition/screening.js";
import { ANALYSIS_VERSION } from "./analysis/material.js";
import { classifyPasses } from "../rust/passes.js";
import { extractHistory, type HistoricalKnowledge } from "./history.js";

import {
  knowledgeRuntime,
  verifyProgramPair,
} from "./verification/program-pair.js";
import { synthesizePassKnowledge } from "./synthesis.js";

export const PIPELINE_VERSION = 3;
export const terminalKnowledgeStates = new Set([
  "complete",
  "verified",
  "excluded",
  "inconclusive",
]);
interface PipelineOptions {
  limit?: number;
  prId?: number;
  follow?: boolean;
  retry?: boolean;
  concurrency?: number;
}

/** B's execution gate retains cases. C only summarizes retained cases after the queue drains. */
export async function runKnowledgePipeline(
  config: ArcherConfig,
  options: PipelineOptions = {},
): Promise<void> {
  const root = historyRoot(config.outputDir),
    scope = await ensureCorpusScope(config.outputDir);
  const states = join(
    root,
    "pipeline",
    config.model.replace(/[^A-Za-z0-9_.-]/g, "_"),
  );
  await mkdir(states, { recursive: true });
  const runtime = await knowledgeRuntime();
  const concurrency = options.concurrency ?? 6;
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 16)
    throw new Error("concurrency must be between 1 and 16");
  await atomicJson(join(root, "active-pipeline.json"), {
    schema: 2,
    model: config.model,
    runtime,
    scope,
    startedAt: new Date().toISOString(),
    pid: process.pid,
  });
  let processed = 0;
  const attempted = new Set<string>();
  const keyFor = (raw: any) =>
    digest({
      pipelineVersion: PIPELINE_VERSION,
      analysisVersion: ANALYSIS_VERSION,
      head: raw.pr.headSha,
      patch: raw.pr.patch,
      body: raw.pr.body,
      issues: raw.issues,
      model: config.model,
      runtime,
    });
  const snapshot = async () => {
    const selection = await loadCorpusSelection(config.outputDir);
    const allowed = selection ? new Set(selection.prIds) : undefined;
    const files = (await readdir(join(root, "raw"))).filter(
      (n) =>
        n.endsWith(".json") &&
        (!allowed || allowed.has(Number(n.split("-")[0]))) &&
        (options.prId === undefined || n.startsWith(`${options.prId}-`)),
    );
    return Promise.all(
      files.map(async (name) => ({
        name,
        raw: JSON.parse(await readFile(join(root, "raw", name), "utf8")),
      })),
    );
  };
  const coverage = async (status: string) => {
    const counts: Record<string, number> = {};
    let total = 0;
    for (const { name, raw } of await snapshot()) {
      if (!inCorpusRange(raw.mergedAt, scope)) continue;
      total++;
      let state = "queued";
      try {
        const s = JSON.parse(await readFile(join(states, name), "utf8"));
        if (s.key === keyFor(raw)) state = s.status;
      } catch {
        /* Still queued. */
      }
      counts[state] = (counts[state] ?? 0) + 1;
    }
    const selection = await loadCorpusSelection(config.outputDir);
    const selectedTotal = selection?.prIds.length ?? total;
    if (selectedTotal > total) counts.uncollected = selectedTotal - total;
    await atomicJson(join(root, "pipeline-status.json"), {
      status,
      model: config.model,
      runtime,
      processed,
      total: selectedTotal,
      collectedTotal: total,
      counts,
      concurrency,
      updatedAt: new Date().toISOString(),
    });
    return { total: selectedTotal, counts };
  };
  await coverage("running");
  let refreshing = false;
  const timer = setInterval(() => {
    if (refreshing) return;
    refreshing = true;
    void coverage("running")
      .catch((error) => console.error(`Progress refresh: ${String(error)}`))
      .finally(() => {
        refreshing = false;
      });
  }, 15000);
  try {
    do {
      const entries = (await snapshot()).filter(({ raw }) =>
        inCorpusRange(raw.mergedAt, scope),
      );
      if (options.prId !== undefined && !entries.length)
        throw new Error(`No collected raw record for #${options.prId}`);
      entries.sort(
        (a, b) =>
          Number(
            classifyPasses(b.raw.pr.files, b.raw.pr.patch).some(
              (p) => p.kind === "pass",
            ),
          ) -
            Number(
              classifyPasses(a.raw.pr.files, a.raw.pr.patch).some(
                (p) => p.kind === "pass",
              ),
            ) || a.raw.pr.id - b.raw.pr.id,
      );
      const queue: typeof entries = [];
      for (const entry of entries) {
        if (attempted.has(entry.name)) continue;
        try {
          const prior = JSON.parse(
            await readFile(join(states, entry.name), "utf8"),
          );
          if (
            prior.key === keyFor(entry.raw) &&
            terminalKnowledgeStates.has(prior.status) &&
            !options.retry
          )
            continue;
        } catch {
          /* New case. */
        }
        queue.push(entry);
      }
      await screenUnrelatedHistory(config, root, queue);
      let cursor = 0;
      const enqueued = new Set(entries.map((e) => e.name));
      let refill: Promise<void> | undefined;
      const refillQueue = async () => {
        refill ??= (async () => {
          for (const entry of await snapshot()) {
            if (enqueued.has(entry.name)) continue;
            enqueued.add(entry.name);
            if (!inCorpusRange(entry.raw.mergedAt, scope)) continue;
            try {
              const prior = JSON.parse(
                await readFile(join(states, entry.name), "utf8"),
              );
              if (
                prior.key === keyFor(entry.raw) &&
                terminalKnowledgeStates.has(prior.status) &&
                !options.retry
              )
                continue;
            } catch {
              /* Newly collected. */
            }
            queue.push(entry);
          }
        })().finally(() => {
          refill = undefined;
        });
        await refill;
      };
      await Promise.all(
        Array.from({ length: concurrency }, async () => {
          while (processed < (options.limit ?? Infinity)) {
            if (cursor >= queue.length) {
              if (!options.follow) break;
              await refillQueue();
              if (cursor >= queue.length) {
                const collection = JSON.parse(
                  await readFile(join(root, "collection.json"), "utf8"),
                );
                if (collection.status !== "collecting") break;
                await new Promise((resolve) => setTimeout(resolve, 10000));
                continue;
              }
            }
            const { name, raw } = queue[cursor++]!;
            processed++;
            attempted.add(name);
            const key = keyFor(raw);
            const state = async (status: string, details: object = {}) =>
              atomicJson(join(states, name), {
                prId: raw.pr.id,
                key,
                status,
                model: config.model,
                updatedAt: new Date().toISOString(),
                ...details,
              });
            for (let retry = 0; retry < 3; retry++) {
              try {
                await state("analysis");
                console.log(`LLM A: analyze #${raw.pr.id} (${config.model})`);
                await extractHistory(config, 1, {
                  prId: raw.pr.id,
                  requireModel: true,
                });
                let analysis: HistoricalKnowledge | undefined;
                try {
                  analysis = JSON.parse(
                    await readFile(join(root, "records", name), "utf8"),
                  );
                } catch {
                  /* Exclusion or unresolved. */
                }
                if (!analysis || analysis.model !== config.model) {
                  let excluded = false;
                  try {
                    const s = JSON.parse(
                      await readFile(join(root, "skipped", name), "utf8"),
                    );
                    excluded = s.model === config.model;
                  } catch {
                    /* Unresolved. */
                  }
                  await state(excluded ? "excluded" : "pending-classification");
                } else {
                  await state("verification", {
                    analysisHash: digest(analysis),
                  });
                  console.log(`LLM B: execute program pair #${raw.pr.id}`);
                  const verified = await verifyProgramPair(
                    config,
                    root,
                    name,
                    analysis,
                    runtime,
                  );
                  await state(
                    verified ? "verified" : "inconclusive",
                    verified ? { pairHash: verified.certificate.pairHash } : {},
                  );
                }
                break;
              } catch (error) {
                await state("failed", {
                  error: String(error),
                  attempt: retry + 1,
                });
                console.error(
                  `Knowledge #${raw.pr.id}, attempt ${retry + 1}: ${String(error)}`,
                );
                if (retry < 2)
                  await new Promise((resolve) =>
                    setTimeout(resolve, 2000 * (retry + 1)),
                  );
              }
            }
            await appendFile(
              join(root, "pipeline-events.jsonl"),
              JSON.stringify({
                prId: raw.pr.id,
                model: config.model,
                at: new Date().toISOString(),
              }) + "\n",
            );
          }
        }),
      );
      await coverage("running");
      if (!options.follow || processed >= (options.limit ?? Infinity)) break;
      const collection = JSON.parse(
        await readFile(join(root, "collection.json"), "utf8"),
      );
      if (collection.status === "complete") {
        // Re-snapshot once more: collector may have added files while this queue ran.
        if (
          (await snapshot()).some(
            ({ name }) => !entries.some((e) => e.name === name),
          )
        )
          continue;
        break;
      }
      if (collection.status !== "collecting")
        throw new Error(`Collection needs attention: ${collection.status}`);
      await new Promise((resolve) => setTimeout(resolve, 15000));
    } while (true);
  } finally {
    clearInterval(timer);
  }
  while (refreshing) await new Promise((resolve) => setTimeout(resolve, 20));
  await coverage("summarizing");
  const summarized = await synthesizePassKnowledge(config);
  for (const { name } of await snapshot()) {
    if (!summarized.has(name.slice(0, -5))) continue;
    const file = join(states, name);
    try {
      const prior = JSON.parse(await readFile(file, "utf8"));
      if (prior.status === "verified" || prior.status === "synthesis")
        await atomicJson(file, {
          ...prior,
          status: "complete",
          updatedAt: new Date().toISOString(),
        });
    } catch {
      /* Not processed. */
    }
  }
  const { counts } = await coverage("batch-complete");
  if (counts.failed || counts["pending-classification"]) {
    await coverage("needs-attention");
    throw new Error(
      `Knowledge needs attention: ${counts.failed ?? 0} failures, ${counts["pending-classification"] ?? 0} unresolved classifications`,
    );
  }
  const collection = JSON.parse(
    await readFile(join(root, "collection.json"), "utf8"),
  );
  if (
    collection.scopeComplete &&
    Object.entries(counts).every(
      ([state, n]) =>
        ["complete", "excluded", "inconclusive"].includes(state) || n === 0,
    )
  ) {
    if (await loadCorpusSelection(config.outputDir))
      await publishPassKnowledge(config);
  }
}
