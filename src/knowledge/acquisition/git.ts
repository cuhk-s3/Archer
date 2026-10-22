import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { githubRequest } from "../../infra/github.js";
import { classifyPasses } from "../../rust/passes.js";
import { checked } from "../../infra/process.js";
import { nativeBuildEnvironment } from "../../rust/toolchain.js";
import type { RustPullRequest } from "../../types.js";

export interface HistoricalMerge {
  id: number;
  mergeSha: string;
  baseSha: string;
  headSha: string;
  committedAt: string;
  files: string[];
}
/** Only Rust's isolated per-PR merge commits; never infer IDs from arbitrary subjects. */
export function parseHistoricalMerges(
  text: string,
): Map<number, HistoricalMerge> {
  const result = new Map<number, HistoricalMerge>();
  for (const block of text.split("\x1e").slice(1)) {
    const [header, ...lines] = block.split("\n");
    const [mergeSha, parents, committedAt, subject] = header!.split("\t");
    const match = subject?.match(/^(?:Auto|Rollup) merge of #(\d+)\b/);
    const pair = parents?.split(" ");
    if (
      !match ||
      pair?.length !== 2 ||
      ![mergeSha, ...pair].every((s) => /^[a-f0-9]{40}$/.test(s ?? ""))
    )
      continue;
    const id = Number(match[1]);
    // GitHub merged_at selects among retried merges below; retain the latest merge.
    if (result.has(id) && result.get(id)!.committedAt >= committedAt!) continue;
    result.set(id, {
      id,
      mergeSha: mergeSha!,
      baseSha: pair[0]!,
      headSha: pair[1]!,
      committedAt: committedAt!,
      files: lines.filter(Boolean),
    });
  }
  return result;
}
export async function loadHistoricalMerges(
  buildRoot: string,
): Promise<Map<number, HistoricalMerge>> {
  const index =
    process.env.ARCHER_HISTORY_GIT_INDEX ??
    join(buildRoot, "historical-merge-files.txt");
  try {
    return parseHistoricalMerges(await readFile(index, "utf8"));
  } catch (error) {
    if (process.env.ARCHER_HISTORY_GIT_INDEX) throw error;
    return new Map();
  }
}
export async function readHistoricalMerge(
  item: any,
  merge: HistoricalMerge,
  repository: string,
  token?: string,
): Promise<RustPullRequest> {
  const env = await nativeBuildEnvironment();
  const commit = await checked(
    "git",
    ["-c", "core.commitGraph=false", "cat-file", "commit", merge.mergeSha],
    {
      cwd: repository,
      env: { ...env, GIT_NO_LAZY_FETCH: "1" },
      timeoutMs: 60_000,
    },
  );
  const actual = commit
    .split("\n\n", 1)[0]!
    .split("\n")
    .filter((line) => line.startsWith("parent "))
    .map((line) => line.slice(7))
    .join(" ");
  if (actual !== `${merge.baseSha} ${merge.headSha}`)
    throw new Error("Local merge parents do not match historical index");
  let patch: string,
    patchSource: RustPullRequest["patchSource"] = "git-first-parent-merge-diff";
  try {
    patch = await checked(
      "git",
      [
        "-c",
        "core.commitGraph=false",
        "-c",
        "http.version=HTTP/1.1",
        "diff",
        "--no-renames",
        "--no-ext-diff",
        merge.baseSha,
        merge.mergeSha,
        "--",
      ],
      {
        cwd: repository,
        env: { ...env, GIT_NO_LAZY_FETCH: "1" },
        timeoutMs: 60_000,
      },
    );
  } catch (localError) {
    const headers: Record<string, string> = {
      Accept: "application/vnd.github.diff",
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await githubRequest(
      `https://api.github.com/repos/rust-lang/rust/pulls/${item.number}`,
      headers,
    );
    if (response.ok) {
      patch = await response.text();
      patchSource = "github-pull-diff";
      if (!patch.startsWith("diff --git "))
        throw new Error("GitHub returned an invalid diff response");
    } else {
      await response.body?.cancel();
      console.log(
        `PR #${item.number}: GitHub diff ${response.status}; fetching complete Git objects`,
      );
      patch = await checked(
        "git",
        [
          "-c",
          "core.commitGraph=false",
          "-c",
          "http.version=HTTP/1.1",
          "-c",
          "http.lowSpeedLimit=1000",
          "-c",
          "http.lowSpeedTime=30",
          "diff",
          "--no-renames",
          "--no-ext-diff",
          merge.baseSha,
          merge.mergeSha,
          "--",
        ],
        { cwd: repository, env, timeoutMs: 180_000, processGroup: true },
      );
      patchSource = "git-first-parent-merge-diff";
    }
  }
  const components = [
    ...new Set(
      merge.files
        .filter((f) => f.startsWith("compiler/"))
        .map((f) => f.split("/")[1]!),
    ),
  ].sort();
  return {
    id: item.number,
    url: item.html_url,
    title: item.title,
    body: item.body ?? "",
    author: item.user?.login ?? "unknown",
    state: "closed",
    baseSha: merge.baseSha,
    headSha: merge.headSha,
    mergeSha: merge.mergeSha,
    patch,
    patchSource,
    files: merge.files,
    components,
    createdAt: item.created_at,
    passes: classifyPasses(merge.files, patch),
  };
}
