import { atomicJson, digest } from "../../src/infra/artifacts.js";
/** Fast metadata/files preselection. No LLM calls and no historical compiler builds. */
import * as http from "node:http";
import { mkdir, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import { getKnowledgeConfig } from "../../src/config.js";
import { parseHistoricalMerges } from "../../src/knowledge/acquisition/git.js";
import {
  historyRoot,
  inCorpusRange,
  ensureCorpusScope,
} from "../../src/knowledge/corpus.js";

import { githubRequest } from "../../src/infra/github.js";

const config = getKnowledgeConfig();
http.setGlobalProxyFromEnv?.();
const root = historyRoot(config.outputDir),
  scope = await ensureCorpusScope(config.outputDir);
await mkdir(join(root, "selected-metadata"), { recursive: true });
const text = await readFile(
  join(config.buildRoot, "historical-merge-files.txt"),
  "utf8",
);
const merges = parseHistoricalMerges(text);
const aggregates = new Set(
  text
    .split("\x1e")
    .filter((b) =>
      /^.*\tAuto merge of #\d+ - .*:rollup(?:-|,)/.test(b.split("\n")[0]!),
    )
    .map((b) => Number(b.split("\n")[0]!.match(/Auto merge of #(\d+)/)![1])),
);
const relevant = (f: string) =>
  /^compiler\/rustc_mir_(transform|dataflow)\/|^tests\/mir-opt\//.test(f);
const ids = new Set(
  [...merges.values()]
    .filter((p) => !aggregates.has(p.id) && p.files.some(relevant))
    .map((p) => p.id),
);
const cached = new Map<number, any>();
for (const name of await readdir(join(root, "search"))) {
  const d = JSON.parse(await readFile(join(root, "search", name), "utf8"));
  for (const p of d.items ?? []) cached.set(p.number, p);
}
const labelCounts: Record<string, number> = {};
for (const name of await readdir(join(config.buildRoot, "prescreen"))) {
  if (!/^label-/.test(name)) continue;
  const d = JSON.parse(
    await readFile(join(config.buildRoot, "prescreen", name), "utf8"),
  );
  labelCounts[name.slice(6, -5)] = d.total_count;
  if (name === "label-A-miri.json") continue; // Tool ownership label is not MIR optimization evidence.
  if (d.incomplete_results || d.total_count > (d.items?.length ?? 0))
    throw new Error(`Incomplete label enumeration: ${name}`);
  for (const p of d.items ?? []) {
    cached.set(p.number, p);
    if (!aggregates.has(p.number)) ids.add(p.number);
  }
}
if (ids.size > 1000)
  throw new Error(
    `Two-year preselection has ${ids.size} candidates, above the authorized 1000 cap`,
  );
const preliminary = [...ids].sort((a, b) => a - b);
await atomicJson(join(root, "selection.json"), {
  schema: 1,
  ...scope,
  prIds: preliminary,
  selectionHash: digest(preliminary),
  status: "checking-merge-dates",
  method:
    "MIR transform/dataflow/mir-opt files OR MIR optimization labels; exclude aggregate rollups",
  labelCounts,
  boundaryBuffer: true,
  updatedAt: new Date().toISOString(),
});
const headers: Record<string, string> = {
  Accept: "application/vnd.github+json",
};
if (config.githubToken) headers.Authorization = `Bearer ${config.githubToken}`;
const selected: number[] = [],
  excluded: any[] = [],
  errors: any[] = [];
let cursor = 0,
  finished = 0;
await Promise.all(
  Array.from({ length: 6 }, async () => {
    while (cursor < preliminary.length) {
      const id = preliminary[cursor++]!;
      try {
        let item = cached.get(id);
        try {
          item = JSON.parse(
            await readFile(
              join(root, "selected-metadata", `${id}.json`),
              "utf8",
            ),
          );
        } catch {}
        if (!item) {
          const r = await githubRequest(
            `https://api.github.com/repos/rust-lang/rust/pulls/${id}`,
            headers,
          );
          if (r.status === 404) {
            await atomicJson(join(root, "selected-metadata", `${id}.json`), {
              number: id,
              notRustPR: true,
            });
            excluded.push({
              id,
              reason: "foreign-subtree-merge-not-a-rust-PR",
            });
            finished++;
            continue;
          }
          if (!r.ok) throw new Error(`PR metadata ${r.status}`);
          const p: any = await r.json();
          if (
            inCorpusRange(p.merged_at, scope) &&
            p.head.sha !== merges.get(id)?.headSha &&
            merges.has(id)
          )
            throw new Error(
              "Git/GitHub head revision mismatch within selected period",
            );
          item = {
            number: p.number,
            title: p.title,
            body: p.body,
            html_url: p.html_url,
            user: p.user,
            created_at: p.created_at,
            updated_at: p.updated_at,
            labels: p.labels,
            pull_request: { merged_at: p.merged_at },
            headSha: p.head.sha,
            mergeSha: p.merge_commit_sha,
          };
        }
        await atomicJson(join(root, "selected-metadata", `${id}.json`), item);
        if (item.notRustPR)
          excluded.push({ id, reason: "foreign-subtree-merge-not-a-rust-PR" });
        else if (!inCorpusRange(item.pull_request?.merged_at, scope))
          excluded.push({
            id,
            reason: "outside-exact-GitHub-merge-date-range",
            mergedAt: item.pull_request?.merged_at,
          });
        else if (/^Rollup of \d+ pull requests/i.test(item.title))
          excluded.push({ id, reason: "aggregate-rollup" });
        else selected.push(id);
      } catch (error) {
        errors.push({ id, error: String(error) });
      }
      finished++;
      if (finished % 50 === 0)
        console.log(`Preselection metadata: ${finished}/${preliminary.length}`);
    }
  }),
);
if (errors.length) {
  await atomicJson(join(root, "prescreen-errors.json"), errors);
  throw new Error(`${errors.length} preselection lookups failed; rerun safely`);
}
selected.sort((a, b) => a - b);
const manifest = {
  schema: 1,
  ...scope,
  prIds: selected,
  selectionHash: digest(selected),
  status: "ready",
  method:
    "MIR transform/dataflow/mir-opt files OR MIR optimization labels; exclude aggregate rollups",
  labelCounts,
  preliminaryCandidates: preliminary.length,
  excluded,
  selectedCount: selected.length,
  updatedAt: new Date().toISOString(),
};
await atomicJson(join(root, "selection.json"), manifest);
await atomicJson(
  join(config.buildRoot, "prescreen", "selection-report.json"),
  manifest,
);
console.log(`Bounded two-year MIR selection ready: ${selected.length} PRs.`);
