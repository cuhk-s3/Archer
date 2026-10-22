/** Run an evaluation using only a PR-era source snapshot and published knowledge.
 * Selection/ground-truth documents must remain outside the source snapshot.
 */
import * as http from "node:http";
import { createHash } from "node:crypto";
import {
  mkdir,
  readFile,
  writeFile,
  appendFile,
  access,
} from "node:fs/promises";
import { join } from "node:path";
import { getKnowledgeConfig, projectRoot } from "../../src/config.js";
import { fetchRustPr } from "../../src/infra/github.js";
import { checked } from "../../src/infra/process.js";
import { atomicJson } from "../../src/infra/artifacts.js";
import {
  RustToolchain,
  nativeBuildEnvironment,
} from "../../src/rust/toolchain.js";
import { runReview } from "../../src/review/index.js";
import { classifyPasses } from "../../src/rust/passes.js";
import { loadPassKnowledge } from "../../src/knowledge/history.js";

const id = Number(process.argv[2]);
if (!Number.isSafeInteger(id) || id <= 0)
  throw new Error("Usage: node --import tsx scripts/review/blind.ts <PR>");
const config = getKnowledgeConfig();
http.setGlobalProxyFromEnv?.();
const root = join(projectRoot, "service_data/blind-review", String(id));
await mkdir(root, { recursive: true });
config.outputDir = join(root, "output");
const status = (state: string, details: object = {}) =>
  atomicJson(join(root, "status.json"), {
    state,
    pid: process.pid,
    pr: id,
    updatedAt: new Date().toISOString(),
    ...details,
  });
const hash = (s: string) => createHash("sha256").update(s).digest("hex");
let trace = Promise.resolve();
try {
  await status("fetching-original-pr");
  const pr = await fetchRustPr(id, config.githubToken);
  if (!pr.mergeSha) throw new Error("Evaluation requires a merged PR");
  await atomicJson(join(root, "input-pr.json"), pr);
  const knowledge = await loadPassKnowledge(
    config.outputDir,
    classifyPasses(pr.files, pr.patch),
  );
  await writeFile(join(root, "input-knowledge.txt"), knowledge);
  await atomicJson(join(root, "input-manifest.json"), {
    prId: id,
    headSha: pr.headSha,
    mergeSha: pr.mergeSha,
    model: config.model,
    prHash: hash(JSON.stringify(pr)),
    knowledgeHash: hash(knowledge),
    publishedManifestHash: hash(
      await readFile(join(projectRoot, "knowledge/rust/manifest.json"), "utf8"),
    ),
    allowedInputs: [
      "original PR metadata and patch",
      "PR merge source tree",
      "published 2024–2025 pass knowledge",
    ],
    withheldInputs: [
      "post-merge issue reports",
      "later fixes",
      "known reproducer programs",
      "selection notes",
    ],
    runStartedAt: new Date().toISOString(),
  });
  await status("building-before-and-after");
  const toolchain = new RustToolchain(
    config.buildRoot,
    config.buildTimeoutMs,
    async (p) => {
      await status("building-before-and-after", { build: p });
    },
  );
  const build = await toolchain.prepareHistorical(pr, pr.mergeSha);
  const env = await nativeBuildEnvironment();
  const baseline = (
    await checked("git", ["rev-parse", "HEAD"], { cwd: build.baseDir, env })
  ).trim();
  pr.baseSha = baseline;
  await atomicJson(join(root, "effective-input-pr.json"), pr);
  // Git archive exports only the PR-era tracked tree: no later Git history,
  // build logs, evaluation notes, previous model sessions or environment files.
  const snapshot = join(root, "source");
  const receipt = join(root, "snapshot-revision.txt");
  let ready = false;
  try {
    ready = (await readFile(receipt, "utf8")).trim() === pr.mergeSha;
  } catch {}
  if (!ready) {
    await mkdir(snapshot, { recursive: true });
    const archive = join(root, "source.tar");
    await checked(
      "git",
      ["archive", "--format=tar", `--output=${archive}`, pr.mergeSha],
      { cwd: build.patchedDir, env, timeoutMs: 600000 },
    );
    await checked("tar", ["-xf", archive, "-C", snapshot], {
      timeoutMs: 600000,
    });
    await writeFile(receipt, pr.mergeSha + "\n");
  }
  try {
    await access(join(snapshot, ".git"));
    throw new Error("Evaluation snapshot unexpectedly has Git metadata");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  await atomicJson(join(root, "build.json"), {
    ...build,
    reviewSource: snapshot,
    baselineSha: baseline,
    patchedSha: pr.mergeSha,
  });
  await status("reviewing");
  const record = await runReview(pr, config, {
    knowledge,
    build: { ...build, patchedDir: snapshot },
    onEvent: (event) => {
      // Token deltas repeat the growing message; message_end retains the full text.
      if (
        event.type === "message_update" ||
        event.type === "tool_execution_update"
      )
        return;
      trace = trace.then(() =>
        appendFile(
          join(root, "trace.jsonl"),
          JSON.stringify({ time: new Date().toISOString(), event }) + "\n",
        ),
      );
    },
  });
  await trace;
  await status("complete", {
    reviewId: record.id,
    phases: record.phases,
    strategies: record.strategies.length,
    completedDifferentialTests: record.evidence.filter(
      (e) => e.tool === "differential_test" && e.status === "ok",
    ).length,
    candidateDifferences: record.evidence.filter((e) => e.found === true)
      .length,
  });
  console.log(`Blind review complete: ${record.id}`);
} catch (error) {
  await trace;
  await status("failed", { error: String(error) });
  throw error;
}
