import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
export const CORPUS_SINCE = "2024-01-01";
export const CORPUS_UNTIL = "2025-12-31";
export const historyRoot = (output: string) =>
  join(output, "knowledge", "history");
export interface CorpusScope {
  since: string;
  until: string;
  groupBy: "pass";
  schemaVersion: 2;
}
export async function ensureCorpusScope(
  output: string,
  since = CORPUS_SINCE,
  until = CORPUS_UNTIL,
): Promise<CorpusScope> {
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(since) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(until) ||
    !Number.isFinite(Date.parse(since)) ||
    !Number.isFinite(Date.parse(until)) ||
    since > until
  )
    throw new Error("Invalid corpus date range");
  const scope: CorpusScope = {
    since,
    until,
    groupBy: "pass",
    schemaVersion: 2,
  };
  const root = historyRoot(output);
  await mkdir(root, { recursive: true });
  let current: CorpusScope | undefined;
  try {
    current = JSON.parse(await readFile(join(root, "scope.json"), "utf8"));
  } catch (error: any) {
    if (error.code !== "ENOENT") throw error;
  }
  if (
    current &&
    (current.since !== since ||
      current.until !== until ||
      current.groupBy !== "pass" ||
      current.schemaVersion !== 2)
  )
    throw new Error(
      "Corpus scope differs: use a separate output directory instead of mixing periods/classifications",
    );
  if (!current)
    await writeFile(
      join(root, "scope.json"),
      JSON.stringify(scope, null, 2) + "\n",
    );
  return scope;
}
export function inCorpusRange(
  mergedAt: string | undefined,
  scope: Pick<CorpusScope, "since" | "until">,
): boolean {
  const date = Date.parse(mergedAt ?? "");
  return (
    Number.isFinite(date) &&
    date >= Date.parse(`${scope.since}T00:00:00Z`) &&
    date <= Date.parse(`${scope.until}T23:59:59.999Z`)
  );
}

export interface CorpusSelection {
  schema: 1;
  since: string;
  until: string;
  prIds: number[];
  selectionHash: string;
  [key: string]: unknown;
}
export async function loadCorpusSelection(
  output: string,
): Promise<CorpusSelection | undefined> {
  try {
    const s: CorpusSelection = JSON.parse(
      await readFile(join(historyRoot(output), "selection.json"), "utf8"),
    );
    if (
      s.schema !== 1 ||
      !Array.isArray(s.prIds) ||
      s.prIds.length > 1000 ||
      s.prIds.some((id) => !Number.isInteger(id) || id < 1) ||
      new Set(s.prIds).size !== s.prIds.length
    )
      throw new Error("Invalid bounded corpus selection");
    return s;
  } catch (error: any) {
    if (error.code === "ENOENT") return undefined;
    throw error;
  }
}
