import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";
import {
  ensureCorpusScope,
  inCorpusRange,
  loadCorpusSelection,
} from "./corpus.js";

it("uses inclusive 2024–2025 merge timestamps and refuses to mix corpus periods", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-corpus-test-"));
  try {
    const scope = await ensureCorpusScope(root);
    expect(scope).toMatchObject({
      since: "2024-01-01",
      until: "2025-12-31",
      groupBy: "pass",
    });
    expect(inCorpusRange("2024-01-01T00:00:00Z", scope)).toBe(true);
    expect(inCorpusRange("2025-12-31T23:59:59.999Z", scope)).toBe(true);
    expect(inCorpusRange("2023-12-31T23:59:59Z", scope)).toBe(false);
    expect(inCorpusRange("2026-01-01T00:00:00Z", scope)).toBe(false);
    expect(inCorpusRange(undefined, scope)).toBe(false);
    await expect(
      ensureCorpusScope(root, "2023-01-01", "2025-12-31"),
    ).rejects.toThrow("Corpus scope differs");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

it("enforces the user's explicit 1000-PR bound without deleting the wider cache", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-bounded-selection-"));
  try {
    await ensureCorpusScope(root);
    const file = join(root, "knowledge/history/selection.json");
    await writeFile(
      file,
      JSON.stringify({
        schema: 1,
        since: "2024-01-01",
        until: "2025-12-31",
        prIds: [115105],
        selectionHash: "fixture",
      }),
    );
    expect((await loadCorpusSelection(root))?.prIds).toEqual([115105]);
    await writeFile(
      file,
      JSON.stringify({
        schema: 1,
        prIds: Array.from({ length: 1001 }, (_, i) => i + 1),
      }),
    );
    await expect(loadCorpusSelection(root)).rejects.toThrow(
      "bounded corpus selection",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
