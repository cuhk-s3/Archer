import { atomicJson } from "../../infra/artifacts.js";
import { mkdir, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import type { ArcherConfig } from "../../config.js";
import { historyRoot, loadCorpusSelection, inCorpusRange } from "../corpus.js";

import { loadHistoricalMerges, readHistoricalMerge } from "./git.js";
import { fetchRustPr, githubRequest } from "../../infra/github.js";

export async function collectSelectedHistory(
  config: ArcherConfig,
): Promise<void> {
  const selection = await loadCorpusSelection(config.outputDir);
  if (!selection || selection.status !== "ready")
    throw new Error("Finish exact-date MIR preselection before collecting");
  const root = historyRoot(config.outputDir),
    merges = await loadHistoricalMerges(config.buildRoot);
  await mkdir(join(root, "raw"), { recursive: true });
  await mkdir(join(root, "inventory"), { recursive: true });
  const existing = new Map(
    (await readdir(join(root, "raw")))
      .filter((n) => n.endsWith(".json"))
      .map((n) => [Number(n.split("-")[0]), n]),
  );
  const errors: Array<{ pr: number; error: string }> = [];
  let cursor = 0,
    completed = 0,
    newRecords = 0;
  const startedAt = new Date().toISOString();
  const progress = async (status: string) =>
    atomicJson(join(root, "collection.json"), {
      status,
      pid: process.pid,
      scope: "bounded-mir-prescreen",
      selectionHash: selection.selectionHash,
      scopeComplete: status === "complete",
      since: selection.since,
      until: selection.until,
      selected: selection.prIds.length,
      completed,
      newRecords,
      errors,
      startedAt,
      updatedAt: new Date().toISOString(),
    });
  await progress("collecting");
  await Promise.all(
    Array.from({ length: 6 }, async () => {
      while (cursor < selection.prIds.length) {
        const id = selection.prIds[cursor++]!;
        try {
          const item = JSON.parse(
            await readFile(
              join(root, "selected-metadata", `${id}.json`),
              "utf8",
            ),
          );
          if (!inCorpusRange(item.pull_request?.merged_at, selection))
            throw new Error("Selected PR outside exact merge date range");
          const merge = merges.get(id);
          let name = existing.get(id);
          if (name && merge && !name.includes(merge.headSha)) name = undefined;
          if (!name) {
            const repository = process.env.ARCHER_HISTORY_GIT_REPO;
            const pr =
              merge && repository
                ? await readHistoricalMerge(
                    item,
                    merge,
                    repository,
                    config.githubToken,
                  )
                : await fetchRustPr(id, config.githubToken);
            name = `${id}-${pr.headSha}.json`;
            // Preserve linked reports and all references; fetch at most three bodies per PR.
            const issueRefs = [
              ...pr.body.matchAll(
                /(?:fix(?:es|ed)?|clos(?:es|ed)|resolv(?:es|ed))\s+(?:rust-lang\/rust)?#(\d+)/gi,
              ),
            ].map((m) => Number(m[1]));
            const issues: Array<{
                number: number;
                title: string;
                body: string;
                url: string;
              }> = [],
              issueErrors: Array<{ number: number; status: number }> = [];
            const headers: Record<string, string> = {
              Accept: "application/vnd.github+json",
            };
            if (config.githubToken)
              headers.Authorization = `Bearer ${config.githubToken}`;
            for (const number of [...new Set(issueRefs)].slice(0, 3)) {
              const response = await githubRequest(
                `https://api.github.com/repos/rust-lang/rust/issues/${number}`,
                headers,
              );
              if (!response.ok) {
                issueErrors.push({ number, status: response.status });
                await response.body?.cancel();
                continue;
              }
              const issue: any = await response.json();
              issues.push({
                number: issue.number,
                title: issue.title,
                body: issue.body ?? "",
                url: issue.html_url,
              });
            }
            await atomicJson(join(root, "raw", name), {
              pr,
              mergedAt: item.pull_request.merged_at,
              collectedAt: new Date().toISOString(),
              issues,
              issueRefs,
              issueErrors,
              issueStatus: issueErrors.length
                ? "partially-loaded"
                : "loaded-up-to-three",
              patchProvenance: {
                kind: pr.patchSource ?? "github-pr-patch",
                ...(merge
                  ? {
                      mergeSha: merge.mergeSha,
                      mergeFirstParent: merge.baseSha,
                      headSha: merge.headSha,
                    }
                  : {}),
              },
            });
            existing.set(id, name);
            newRecords++;
          }
          await atomicJson(join(root, "inventory", `${id}.json`), {
            id,
            title: item.title,
            url: item.html_url,
            labels: item.labels?.map((l: any) =>
              typeof l === "string" ? l : l.name,
            ),
            files: merge?.files,
            selectionHash: selection.selectionHash,
            decision: "selected-for-pass-analysis",
            rawFile: name,
          });
          completed++;
          if (completed % 25 === 0)
            console.log(
              `Selected MIR collection: ${completed}/${selection.prIds.length} (${newRecords} new)`,
            );
        } catch (error) {
          errors.push({ pr: id, error: String(error) });
          console.error(`Selected #${id}: ${String(error)}`);
        }
        await progress("collecting");
      }
    }),
  );
  await progress(errors.length ? "finished-with-errors" : "complete");
  if (errors.length)
    throw new Error(`${errors.length} selected MIR PRs need collection retry`);
  console.log(`Selected MIR collection complete: ${completed} PRs`);
}
