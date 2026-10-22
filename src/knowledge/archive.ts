import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { atomicJson, digest } from "../infra/artifacts.js";
import type { RustPullRequest } from "../types.js";
import type { CorpusSelection } from "./corpus.js";
import type {
  PairObservation,
  VerifiedPair,
} from "./verification/program-pair.js";
import { pairSources } from "./verification/program-pair.js";
import { loadHistoricalMerges } from "./acquisition/git.js";

async function optionalJson(path: string): Promise<any> {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  }
}

/** Publish validated and inconclusive cases; keep source-backed exclusions in runtime caches. */
export async function publishCaseArchive(options: {
  runtimeRoot: string;
  destination: string;
  buildRoot: string;
  model: string;
  selection: CorpusSelection;
  pairs: VerifiedPair[];
}): Promise<{ metadata: number; cases: number }> {
  const { runtimeRoot: root, destination, selection, model, pairs } = options;
  const slug = model.replace(/[^A-Za-z0-9_.-]/g, "_");
  const allowed = new Set(selection.prIds);
  const states = new Map<number, { name: string; state: any }>();
  for (const name of await readdir(join(root, "pipeline", slug))) {
    if (!/^[0-9]+-[a-f0-9]+\.json$/.test(name)) continue;
    const state = await optionalJson(join(root, "pipeline", slug, name));
    if (!allowed.has(state?.prId)) continue;
    if (states.has(state.prId))
      throw new Error(`Ambiguous pipeline state for PR #${state.prId}`);
    states.set(state.prId, { name, state });
  }
  if (states.size !== allowed.size)
    throw new Error("Archive requires a terminal state for every selected PR");
  const retained = new Map(pairs.map((pair) => [pair.analysis.prId, pair]));
  if ([...retained.keys()].some((id) => !allowed.has(id)))
    throw new Error("Retained case is outside the selected corpus");
  const archivedIds = [...states.entries()]
    .filter(([, item]) => item.state.status !== "excluded")
    .map(([id]) => id)
    .sort((a, b) => a - b);
  const archivedHash = digest(archivedIds);
  const archived = new Set(archivedIds);
  const merges = await loadHistoricalMerges(options.buildRoot);
  const rows: object[] = [];
  await mkdir(join(destination, "metadata"), { recursive: true });
  await mkdir(join(destination, "cases"), { recursive: true });
  for (const prId of [...allowed].sort((a, b) => a - b)) {
    const { name, state } = states.get(prId)!;
    if (!["complete", "excluded", "inconclusive"].includes(state.status))
      throw new Error(`PR #${prId} is unfinished`);
    const pair = retained.get(prId);
    if ((state.status === "complete") !== Boolean(pair))
      throw new Error(`Case/archive state mismatch: #${prId}`);
    if (state.status === "excluded") continue;
    const raw = await optionalJson(join(root, "raw", name));
    if (!raw?.pr || raw.pr.id !== prId)
      throw new Error(`Missing PR source metadata: #${prId}`);
    const pr = raw.pr as RustPullRequest;
    const upstream = await optionalJson(
      join(root, "selected-metadata", `${prId}.json`),
    );
    const analysis = await optionalJson(join(root, "records", name));
    const skipped = await optionalJson(join(root, "skipped", name));
    const pairState = await optionalJson(
      join(root, "program-pairs", slug, `${name}.state.json`),
    );
    const decision =
      state.status !== "inconclusive"
        ? undefined
        : pairState?.model === model
          ? pairState
          : skipped?.headSha === pr.headSha && skipped.model === model
            ? skipped
            : undefined;
    if (pair && pair.analysis.headSha !== pr.headSha)
      throw new Error(`Case revision mismatch: #${prId}`);
    const merge = merges.get(prId);
    const pinned = merge?.headSha === pr.headSha ? merge : undefined;
    const file = `metadata/${prId}.json`;
    await atomicJson(join(destination, file), {
      schema: 1,
      pr: {
        id: prId,
        title: pr.title,
        url: pr.url,
        description: pr.body,
        author: pr.author,
        state: pr.state,
        createdAt: pr.createdAt,
        mergedAt: raw.mergedAt,
        headSha: pr.headSha,
        baseSha: pinned?.baseSha ?? pr.baseSha,
        baseShaProvenance: pinned
          ? "isolated-merge-first-parent"
          : "collected-pr-metadata",
        ...(pinned
          ? { mergeSha: pinned.mergeSha }
          : pr.mergeSha
            ? { mergeSha: pr.mergeSha }
            : {}),
        files: pr.files,
        components: pr.components,
        labels: (upstream?.labels ?? []).map((label: any) =>
          typeof label === "string" ? label : label.name,
        ),
        patchHash: digest(pr.patch),
        patchSource: pr.patchSource ?? "github-pull-patch",
        patchUrl: `${pr.url}.patch`,
      },
      issues: raw.issues ?? [],
      classification: analysis?.passes ?? decision?.passes ?? pr.passes ?? [],
      processing: {
        status: state.status,
        model,
        updatedAt: state.updatedAt,
        ...(decision
          ? {
              reason: decision.reason,
              evidence: decision.evidence ?? [],
              attempts: decision.attempts,
            }
          : {}),
        ...(pair ? { localCase: `../cases/${prId}/case.json` } : {}),
      },
      ...(analysis?.headSha === pr.headSha && analysis.model === model
        ? { analysis }
        : {}),
    });
    if (pair) {
      const directory = join(destination, "cases", String(prId));
      await mkdir(directory, { recursive: true });
      const sources = pairSources(pair.certificate.pair);
      await writeFile(join(directory, "original.rs"), sources[0]);
      await writeFile(join(directory, "transformed.rs"), sources[1]);
      const { rustc: _localExecutable, ...runtime } = pair.certificate.runtime;
      // Only diagnostic paths are normalized; observed stdout remains byte-for-byte intact.
      const normalize = (value: string) =>
        value
          .replace(/\/(?:Users|home)\/[^/\s]+/g, "<home>")
          .replace(
            /\/(?:private\/)?(?:tmp|var\/folders)\/[^\s:'"()]+/g,
            "<temporary-path>",
          );
      const portable = (observations: PairObservation[]) =>
        observations.map((observation) => ({
          ...observation,
          ...(observation.compileStderr === undefined
            ? {}
            : { compileStderr: normalize(observation.compileStderr) }),
          result: {
            ...observation.result,
            stderr: normalize(observation.result.stderr),
          },
        }));
      const artifactDirectory = join(
        root,
        "program-pair-artifacts",
        slug,
        `${prId}-${pr.headSha}`,
      );
      const artifactReceipt = await optionalJson(
        join(artifactDirectory, "artifacts.json"),
      );
      const receipt =
        artifactReceipt?.pairHash === pair.certificate.pairHash &&
        artifactReceipt.analysisHash === pair.certificate.analysisHash
          ? artifactReceipt
          : undefined;
      const mir: Record<string, object> = {};
      if (receipt) {
        for (const [i, label] of ["original", "transformed"].entries()) {
          const text = await readFile(
            join(artifactDirectory, `${label}.mir`),
            "utf8",
          );
          if (
            receipt.files[i]?.sourceHash !== digest(sources[i]) ||
            receipt.files[i]?.mirHash !== digest(text)
          )
            throw new Error(`MIR artifact hash mismatch: #${prId}`);
          const published = text.replaceAll(
            join(artifactDirectory, `${label}.rs`),
            `${label}.rs`,
          );
          await writeFile(join(directory, `${label}.mir`), published);
          mir[label] = {
            path: `${label}.mir`,
            contentHash: digest(published),
            originalArtifactHash: digest(text),
          };
        }
      } else {
        await Promise.all(
          ["original.mir", "transformed.mir"].map((name) =>
            rm(join(directory, name), { force: true }),
          ),
        );
      }
      await atomicJson(join(directory, "case.json"), {
        schema: 1,
        prId,
        caseId: `${prId}-${pr.headSha}`,
        metadata: `../../${file}`,
        validation: {
          ...pair.certificate,
          runtime,
          oracles: portable(pair.certificate.oracles),
          runs: portable(pair.certificate.runs),
        },
        files: {
          original: { path: "original.rs", contentHash: digest(sources[0]) },
          transformed: {
            path: "transformed.rs",
            contentHash: digest(sources[1]),
          },
        },
        ...(receipt ? { mir, mirFlags: receipt.flags } : {}),
        portability:
          "Executable location omitted; home and temporary paths normalized in execution diagnostics. MIR source filenames are made relative. Program text, stdout, analysis and pair hashes are unchanged.",
      });
    }
    rows.push({
      prId,
      title: pr.title,
      status: state.status,
      metadata: file,
      ...(pair ? { localCase: `cases/${prId}/case.json` } : {}),
    });
  }
  for (const name of await readdir(join(destination, "metadata"))) {
    if (
      /^[0-9]+\.json$/.test(name) &&
      !archived.has(Number(name.slice(0, -5)))
    ) {
      await rm(join(destination, "metadata", name));
    }
  }
  await atomicJson(join(destination, "history.json"), {
    schema: 1,
    model,
    since: selection.since,
    until: selection.until,
    selectionHash: archivedHash,
    sourceSelectionHash: selection.selectionHash,
    includedStatuses: ["complete", "inconclusive"],
    prs: rows,
  });
  await atomicJson(join(destination, "selection.json"), {
    schema: 1,
    status: "ready",
    since: selection.since,
    until: selection.until,
    prIds: archivedIds,
    selectionHash: archivedHash,
    sourceSelectionHash: selection.selectionHash,
    includedStatuses: ["complete", "inconclusive"],
  });
  return { metadata: rows.length, cases: retained.size };
}
