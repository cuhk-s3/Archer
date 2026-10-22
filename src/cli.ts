#!/usr/bin/env node
import { Command } from "commander";
import * as http from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { getConfig, getKnowledgeConfig, loadEnvironment } from "./config.js";
import { fetchRustPr } from "./infra/github.js";
import { runReview } from "./review/index.js";
import { startServer } from "./service/server.js";
import { collectHistory, extractHistory } from "./knowledge/history.js";
import { runKnowledgePipeline } from "./knowledge/pipeline.js";
import { validateHistory } from "./knowledge/verification/historical.js";
import { CORPUS_SINCE, CORPUS_UNTIL } from "./knowledge/corpus.js";

loadEnvironment();
// Node's fetch does not use HTTP(S)_PROXY by default. Enable the native
// environment proxy when available (Node 24+), including NO_PROXY handling.
if (
  process.env.HTTPS_PROXY ||
  process.env.HTTP_PROXY ||
  process.env.https_proxy ||
  process.env.http_proxy
) {
  http.setGlobalProxyFromEnv?.();
}
const cli = new Command();
cli
  .name("archer")
  .description("Rust compiler PR review powered by Pi and Miri")
  .version("0.1.0");
cli
  .command("review")
  .description(
    "Fetch a rust-lang/rust PR, build base and patched rustc, and run an evidence-driven review",
  )
  .argument("<pr>", "Rust compiler pull request number", (v) =>
    Number.parseInt(v, 10),
  )
  .option(
    "-m, --model <model>",
    "Pi model id (defaults to ARCHER_MODEL or deepseek-flash)",
  )
  .action(async (id: number, options: { model?: string }) => {
    if (!Number.isInteger(id) || id <= 0)
      throw new Error("PR number must be a positive integer");
    const config = getConfig();
    if (options.model) config.model = options.model;
    const pr = await fetchRustPr(id, config.githubToken);
    console.log(`#${pr.id} ${pr.title} (${pr.headSha.slice(0, 12)})`);
    await runReview(pr, config);
  });
cli
  .command("fetch")
  .description("Fetch and print metadata for a Rust PR without building it")
  .argument("<pr>", "Rust compiler pull request number", (v) =>
    Number.parseInt(v, 10),
  )
  .action(async (id: number) => {
    const config = getConfig();
    const pr = await fetchRustPr(id, config.githubToken);
    console.log(
      JSON.stringify(
        { ...pr, patch: `[${pr.patch.length} patch bytes]` },
        null,
        2,
      ),
    );
  });
cli
  .command("serve")
  .description("Serve the review board and JSON review API")
  .action(() => {
    startServer(getConfig());
  });
cli
  .command("validate-knowledge")
  .description(
    "Independently reproduce candidate historical bugs before admitting per-pass knowledge",
  )
  .option("--limit <number>", "Maximum candidate validations")
  .action(async (options) => {
    const limit = options.limit ? Number(options.limit) : Infinity;
    if (limit !== Infinity && (!Number.isInteger(limit) || limit < 1))
      throw new Error("limit must be positive");
    await validateHistory(getConfig(), limit);
  });
cli
  .command("knowledge-build")
  .description(
    "Run three independent knowledge LLM stages on collected 2024–2025 PRs",
  )
  .option("--model <model>", "Model for all three roles", "deepseek-flash")
  .option("--pr <number>", "Process one collected historical PR")
  .option("--limit <number>", "Maximum cases in this invocation")
  .option("--follow", "Keep processing while collection continues")
  .option("--retry", "Revisit terminal case states")
  .option("--concurrency <number>", "Concurrent historical cases (1–16)", "6")
  .action(async (options) => {
    const config = getKnowledgeConfig();
    config.model = options.model;
    const limit = options.limit ? Number(options.limit) : Infinity;
    const prId = options.pr ? Number(options.pr) : undefined;
    if (limit !== Infinity && (!Number.isInteger(limit) || limit < 1))
      throw new Error("limit must be positive");
    if (prId !== undefined && (!Number.isInteger(prId) || prId < 1))
      throw new Error("pr must be positive");
    await runKnowledgePipeline(config, {
      ...(prId === undefined ? {} : { prId }),
      limit,
      follow: !!options.follow,
      retry: !!options.retry,
      concurrency: Number(options.concurrency),
    });
  });
cli
  .command("knowledge")
  .description(
    "Build per-pass knowledge from merged Rust PRs in 2024–2025 (resumable)",
  )
  .option(
    "--limit <number>",
    "Optional batch cap; by default collect all matching historical PRs",
  )
  .option("--all", "Collect/extract all matching historical PRs (the default)")
  .option("--since <date>", "Merged on/after YYYY-MM-DD", CORPUS_SINCE)
  .option("--until <date>", "Merged on/before YYYY-MM-DD", CORPUS_UNTIL)
  .option("--query <query>", "Extra GitHub search qualifiers")
  .option("--collect-only", "Only collect raw historical PRs")
  .option("--extract-only", "Extract from existing raw records")
  .option(
    "--follow",
    "Keep extracting newly collected records until collection is complete",
  )
  .action(async (options) => {
    const config = getKnowledgeConfig();
    const limit = options.limit
      ? Number(options.limit)
      : Number.POSITIVE_INFINITY;
    if (options.limit && (!Number.isInteger(limit) || limit < 1))
      throw new Error("limit must be a positive integer");
    if (options.all && options.limit)
      throw new Error("--all and --limit are mutually exclusive");
    if (options.collectOnly && options.extractOnly)
      throw new Error("Choose collect-only or extract-only");
    if (!options.extractOnly)
      await collectHistory(config, {
        ...(options.limit ? { limit } : {}),
        since: options.since,
        until: options.until,
        query: options.query,
      });
    if (!options.collectOnly && !options.extractOnly) {
      await runKnowledgePipeline(config, { limit, follow: !!options.follow });
    } else if (options.extractOnly) {
      do {
        try {
          await extractHistory(config, limit);
        } catch (error) {
          if (!options.follow) throw error;
          console.error(`Extraction batch needs retry: ${String(error)}`);
        }
        if (!options.follow) break;
        const state = JSON.parse(
          await readFile(
            join(config.outputDir, "knowledge/history/collection.json"),
            "utf8",
          ),
        );
        if (state.status === "complete") {
          // Catch files collected while the last extraction snapshot was running.
          await extractHistory(config, limit);
          break;
        }
        if (state.status !== "collecting")
          throw new Error(`Collection needs attention: ${state.status}`);
        console.log("Waiting for more historical PRs...");
        await new Promise((resolve) => setTimeout(resolve, 30_000));
      } while (true);
    }
  });
cli.parseAsync().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
