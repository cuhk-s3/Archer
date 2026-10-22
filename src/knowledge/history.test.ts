vi.mock("./publication.js", () => ({
  loadPublishedKnowledge: async () => undefined,
}));
import { digest } from "../infra/artifacts.js";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type ValidationCertificate } from "./verification/historical.js";
import { expect, it, vi } from "vitest";
import {
  summarizeHistory,
  loadPassKnowledge,
  type HistoricalKnowledge,
} from "./history.js";

it("groups evidence by exact pass, restricts dates and never shares GVN knowledge with CopyProp", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-history-test-"));
  try {
    const dir = join(root, "knowledge/history/records");
    await mkdir(dir, { recursive: true });
    const pass = {
      id: "GVN",
      name: "GVN",
      kind: "pass",
      confidence: "high",
      evidence: ["gvn.rs"],
    } as const;
    const item: HistoricalKnowledge = {
      prId: 42,
      headSha: "abc",
      sourceUrl: "https://github.com/rust-lang/rust/pull/42",
      components: ["rustc_mir_transform"],
      mergedAt: "2024-06-01T00:00:00Z",
      passIds: ["GVN"],
      passes: [{ ...pass, evidence: ["gvn.rs"] }],
      summary: "Range propagation",
      kind: "bug-fix",
      trigger: "wrapping arithmetic",
      preconditions: ["signed integer"],
      pitfalls: ["overflow"],
      testStrategy: "Check signed boundaries",
      evidence: ["- wrong transformation\n+ checked transformation"],
      extractedAt: "2026-10-21T00:00:00Z",
      validation: "source-backed-not-reproduced",
    };
    await writeFile(join(dir, "42-abc.json"), JSON.stringify(item));
    await writeFile(
      join(dir, "43-old.json"),
      JSON.stringify({ ...item, prId: 43, mergedAt: "2023-12-31T23:59:59Z" }),
    );
    await summarizeHistory(root);
    expect(await loadPassKnowledge(root, item.passes)).toContain(
      "No historical knowledge",
    );
    const verifiedDir = join(root, "knowledge/history/verified");
    await mkdir(verifiedDir, { recursive: true });
    const result = { code: 0, stdout: "1\n", stderr: "" };
    const certificate: ValidationCertificate = {
      schema: 1,
      status: "reproduced",
      scope: "historical-merge-runtime-counterexample",
      candidateHash: digest(item),
      source: "fn main() {}",
      sourceHash: digest("fn main() {}"),
      passIds: ["GVN"],
      sourceEvidence: item.evidence,
      rationale: "Test fixture",
      before: "a".repeat(40),
      after: "b".repeat(40),
      baselineVersion: "fixture",
      fixedVersion: "fixture",
      miriVersion: "fixture",
      validatedAt: "2026-10-21",
      oracles: [result, result],
      runs: ["0", "3"].flatMap((level) =>
        ["base", "fixed"].flatMap((version) =>
          [0, 1].map(() => ({
            label: `${version}-O${level}`,
            compiled: true,
            result: { ...result, stdout: version === "base" ? "2\n" : "1\n" },
          })),
        ),
      ),
    };
    await writeFile(
      join(verifiedDir, "42-abc.json"),
      JSON.stringify({ candidate: item, certificate }),
    );
    const notes = await loadPassKnowledge(root, item.passes);
    expect(notes).toContain(item.sourceUrl);
    expect(notes).toContain(item.trigger);
    expect(notes).toContain("not a universal equivalence proof");
    expect(
      await loadPassKnowledge(root, [
        { ...pass, id: "CopyProp", evidence: [] },
      ]),
    ).toContain("No historical knowledge");
    expect(
      await loadPassKnowledge(root, [
        { ...pass, id: "../../environments", evidence: [] },
      ]),
    ).toContain("No historical knowledge");
    expect(
      JSON.parse(
        await readFile(join(root, "knowledge/history/manifest.json"), "utf8"),
      ).records,
    ).toBe(1);
    await writeFile(
      join(dir, "42-abc.json"),
      JSON.stringify({ ...item, trigger: "changed candidate" }),
    );
    expect(await loadPassKnowledge(root, item.passes)).toContain(
      "No historical knowledge",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
