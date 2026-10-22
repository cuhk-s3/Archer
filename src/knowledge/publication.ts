import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { projectRoot, type ArcherConfig } from "../config.js";
import { atomicJson, digest } from "../infra/artifacts.js";
import { historyRoot, loadCorpusSelection } from "./corpus.js";
import { readVerifiedPairs } from "./synthesis.js";
import { publishCaseArchive } from "./archive.js";

const publishedRoot = join(projectRoot, "knowledge", "rust");
interface PublishedPass {
  id: string;
  file: string;
  patterns: number;
  cases: number;
  contentHash: string;
}
interface PublishedManifest {
  schema: 1;
  model: string;
  selectedPRs: number;
  verifiedCases: number;
  patterns: number;
  passes: PublishedPass[];
  [key: string]: unknown;
}

/** Publish only a fully processed, independently executed and completely summarized corpus. */
export async function publishPassKnowledge(
  config: ArcherConfig,
): Promise<void> {
  const root = historyRoot(config.outputDir);
  const selection = await loadCorpusSelection(config.outputDir);
  const status = JSON.parse(
    await readFile(join(root, "pipeline-status.json"), "utf8"),
  );
  const collection = JSON.parse(
    await readFile(join(root, "collection.json"), "utf8"),
  );
  const index = JSON.parse(
    await readFile(join(root, "synthesis-index.json"), "utf8"),
  );
  if (
    !selection ||
    selection.status !== "ready" ||
    !collection.scopeComplete ||
    collection.selectionHash !== selection.selectionHash
  )
    throw new Error("Publication requires the complete selected corpus");
  const counts = status.counts;
  if (
    Object.entries(counts).some(
      ([key, count]) =>
        !["complete", "excluded", "inconclusive"].includes(key) &&
        Number(count) > 0,
    ) ||
    (counts.complete ?? 0) +
      (counts.excluded ?? 0) +
      (counts.inconclusive ?? 0) !==
      selection.prIds.length
  )
    throw new Error("Some selected PRs remain unprocessed");
  const pairs = await readVerifiedPairs(root, config.model);
  if (pairs.length !== index.verifiedPairs || pairs.length !== counts.complete)
    throw new Error(
      "Published case count must match execution certificates and summaries",
    );
  const archive = await publishCaseArchive({
    runtimeRoot: root,
    destination: publishedRoot,
    buildRoot: config.buildRoot,
    model: config.model,
    selection,
    pairs,
  });
  const passes: PublishedPass[] = [];
  await mkdir(join(publishedRoot, "passes"), { recursive: true });
  for (const pass of index.passes) {
    if (!/^[A-Z][A-Za-z0-9_]*$/.test(pass.id))
      throw new Error("Invalid pass identifier");
    const text = await readFile(
      join(root, "synthesized-passes", config.model, `${pass.id}.md`),
      "utf8",
    );
    const file = `passes/${pass.id}.md`;
    await writeFile(join(publishedRoot, file), text);
    passes.push({
      id: pass.id,
      file,
      patterns: pass.patterns,
      cases: pairs.filter((p) => p.certificate.passIds.includes(pass.id))
        .length,
      contentHash: digest(text),
    });
  }
  passes.sort((a, b) => a.id.localeCompare(b.id));
  const cases = pairs.map((p) => ({
    caseId: `${p.analysis.prId}-${p.analysis.headSha}`,
    prId: p.analysis.prId,
    sourceUrl: p.analysis.sourceUrl,
    mergedAt: p.analysis.mergedAt,
    passIds: p.certificate.passIds,
    summary: p.analysis.summary,
    trigger: p.analysis.trigger,
    inputs: p.certificate.pair.inputs,
    originalOutput: p.certificate.oracles.find((o) => o.label === "original")!
      .result.stdout,
    transformedOutput: p.certificate.oracles.find(
      (o) => o.label === "transformed",
    )!.result.stdout,
    analysisHash: p.certificate.analysisHash,
    pairHash: p.certificate.pairHash,
    metadata: `metadata/${p.analysis.prId}.json`,
    localCase: `cases/${p.analysis.prId}/case.json`,
  }));
  await atomicJson(join(publishedRoot, "cases.json"), {
    schema: 1,
    model: config.model,
    cases,
  });
  const manifest: PublishedManifest = {
    schema: 1,
    model: config.model,
    since: selection.since,
    until: selection.until,
    selectedPRs: selection.prIds.length,
    selectionHash: selection.selectionHash,
    verifiedCases: pairs.length,
    archivedMetadata: archive.metadata,
    localCases: archive.cases,
    caseArtifactsVersioned: false,
    excludedPRs: counts.excluded,
    noCounterexamplePRs: counts.inconclusive,
    patterns: passes.reduce((n, p) => n + p.patterns, 0),
    passes,
    workflow: {
      A: "describe historical transformation",
      B: "generate and execute program pairs; retain concrete differences",
      C: "summarize every retained description per pass; no rejection role",
    },
    validation: {
      scope: "historical-transformation-program-pair",
      toolchain: pairs[0]?.certificate.runtime.toolchain,
      rustcVersion: pairs[0]?.certificate.runtime.rustcVersion,
      miriVersion: pairs[0]?.certificate.runtime.miriVersion,
    },
    publishedAt: new Date().toISOString(),
  };
  await atomicJson(join(publishedRoot, "manifest.json"), manifest);
  await writeFile(
    join(publishedRoot, "README.md"),
    [
      "# Rust MIR pass knowledge",
      "",
      `Historical merge dates: **${selection.since} through ${selection.until}**.`,
      "",
      `${manifest.selectedPRs} selected PRs processed: **${manifest.verifiedCases}** retained concrete counterexamples, ${counts.excluded} source-backed exclusions, ${counts.inconclusive} cases without a validated counterexample.`,
      `${passes.length} actual passes, **${manifest.patterns}** summarized patterns.`,
      "",
      "A describes the historical wrong transformation. B generates and executes original/transformed program pairs with fixed Rust/Miri; defined repeatable differences retain a case. C summarizes every retained description for its pass and cannot reject cases. These are concrete-input examples, not universal proofs or current rustc bug claims.",
      "",
      "## Contents",
      "",
      "- `passes/`: the knowledge read by review; one file per actual pass.",
      "- `catalog/`: pass classification definitions and pinned source snapshots used to rebuild them.",
      "- `cases.json`: retained case index, upstream PR links, triggering conditions, tested outputs and evidence hashes.",
      "- `metadata/`: one JSON file for each validated or inconclusive case, with upstream metadata, source references, analysis and unresolved reasons. Source-backed exclusions remain only in runtime caches.",
      "- `cases/`: ignored local artifacts: retained validation records, Rust programs and compiler-emitted MIR. These are not committed; `localCase` links require a local export.",
      "- `history.json` / `selection.json`: validated and inconclusive PRs with links to their metadata; excluded PRs are omitted.",
      "- `manifest.json`: corpus scope, counts, compiler versions and summary content hashes.",
      "",
      "Validated and inconclusive case metadata, descriptions and pass summaries are versioned. Inconclusive cases are retained for follow-up but do not enter pass summaries. Program pairs and detailed validation artifacts stay local in the ignored `cases/` directory; full raw patches, intermediate attempts and verbose logs remain in `service_data/reviews/knowledge/history/`.",
      "",
      "## Pass index",
      "",
      "| Pass | Cases | Patterns |",
      "| --- | ---: | ---: |",
      ...passes.map(
        (p) => `| [${p.id}](${p.file}) | ${p.cases} | ${p.patterns} |`,
      ),
      "",
    ].join("\n"),
  );
  console.log(
    `Published ${passes.length} pass knowledge files to ${publishedRoot}`,
  );
}

/** Review uses the versioned summaries even on a fresh checkout without service_data. */
export async function loadPublishedKnowledge(
  passIds: string[],
  directory = publishedRoot,
): Promise<string | undefined> {
  let manifest: PublishedManifest;
  try {
    manifest = JSON.parse(
      await readFile(join(directory, "manifest.json"), "utf8"),
    );
  } catch (error: any) {
    if (error.code === "ENOENT") return undefined;
    throw error;
  }
  if (manifest.schema !== 1)
    throw new Error("Unsupported published knowledge manifest");
  const notes: string[] = [];
  const available = [...new Set(passIds)].filter(
    (id) =>
      /^[A-Z][A-Za-z0-9_]*$/.test(id) &&
      manifest.passes.some((p) => p.id === id),
  );
  const allowance = Math.floor(60_000 / Math.max(1, available.length));
  for (const id of available) {
    if (!/^[A-Z][A-Za-z0-9_]*$/.test(id)) continue;
    const pass = manifest.passes.find((p) => p.id === id);
    if (!pass || pass.file !== `passes/${id}.md`) continue;
    const text = await readFile(join(directory, pass.file), "utf8");
    notes.push(
      text.length > allowance
        ? text.slice(0, allowance) +
            "\n[Prompt excerpt; full pass knowledge remains in the repository.]"
        : text,
    );
  }
  return notes.length ? notes.join("\n\n").slice(0, 60_000) : undefined;
}
