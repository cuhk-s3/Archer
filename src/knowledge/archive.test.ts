import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { expect, it } from "vitest";
import { publishCaseArchive } from "./archive.js";
import { digest } from "../infra/artifacts.js";
import { pairSources, type VerifiedPair } from "./verification/program-pair.js";

it("archives validated and inconclusive cases, removes excluded metadata and preserves portable results", async () => {
  const base = await mkdtemp(join(tmpdir(), "archer-case-archive-"));
  const root = join(base, "runtime"),
    destination = join(base, "published");
  const head = "a".repeat(40),
    model = "fixture";
  const json = async (file: string, value: unknown) =>
    writeFile(join(root, file), JSON.stringify(value));
  try {
    for (const path of [
      "raw",
      "records",
      "skipped",
      "selected-metadata",
      "pipeline/fixture",
      "program-pairs/fixture",
    ])
      await mkdir(join(root, path), { recursive: true });
    for (const [id, status] of [
      [1, "complete"],
      [2, "excluded"],
      [3, "inconclusive"],
      [4, "complete"],
    ] as const) {
      const name = `${id}-${head}.json`;
      await json(`pipeline/fixture/${name}`, { prId: id, status, model });
      await json(`raw/${name}`, {
        pr: {
          id,
          headSha: head,
          title: `PR ${id}`,
          url: `https://github.com/rust-lang/rust/pull/${id}`,
          body: "source description",
          patch: "diff fixture",
          files: ["compiler/pass.rs"],
        },
        mergedAt: "2024-01-01",
      });
      await json(`selected-metadata/${id}.json`, {
        labels: [{ name: "A-mir-opt" }],
      });
      if (id !== 1 && id !== 4)
        await json(`skipped/${name}`, {
          headSha: head,
          model,
          reason:
            status === "excluded" ? "mechanical change" : "no faithful pair",
          evidence: ["source quotation"],
        });
    }
    const pair = {
      analysis: { prId: 1, headSha: head, model, summary: "wrong transform" },
      certificate: {
        pair: {
          commonSource: "",
          originalFunction: "fn case() -> i32 { 1 }",
          transformedFunction: "fn case() -> i32 { 2 }",
          harness: 'fn main() { println!("{}", case()); }',
        },
        runtime: {
          rustc: "/Users/local/bin/rustc",
          rustcVersion: "fixture rustc",
          toolchain: "nightly",
          miriVersion: "fixture miri",
        },
        oracles: [
          {
            label: "original",
            result: {
              code: 0,
              stdout: "/home/literal\n",
              stderr: "/Users/local/temp/case.rs:1",
            },
          },
        ],
        runs: [],
        pairHash: "pair",
        analysisHash: "analysis",
      },
    } as unknown as VerifiedPair;
    await json(`records/1-${head}.json`, pair.analysis);
    const artifact = `program-pair-artifacts/fixture/1-${head}`;
    await mkdir(join(root, artifact), { recursive: true });
    const sources = pairSources(pair.certificate.pair);
    const mir = ["original", "transformed"].map(
      (label) => `// ${join(root, artifact, label + ".rs")}\nMIR fixture\n`,
    );
    for (const [i, label] of ["original", "transformed"].entries())
      await writeFile(join(root, artifact, label + ".mir"), mir[i]!);
    await json(artifact + "/artifacts.json", {
      pairHash: "pair",
      analysisHash: "analysis",
      files: sources.map((source, i) => ({
        sourceHash: digest(source),
        mirHash: digest(mir[i]),
      })),
      flags: ["--emit=mir"],
    });
    const options = {
      runtimeRoot: root,
      destination,
      buildRoot: base,
      model,
      selection: {
        schema: 1 as const,
        since: "2024-01-01",
        until: "2025-12-31",
        prIds: [1, 2, 3],
        selectionHash: "selection",
      },
      pairs: [pair],
    };
    await mkdir(join(destination, "metadata"), { recursive: true });
    await writeFile(join(destination, "metadata/2.json"), "{}");
    await writeFile(join(destination, "metadata/3.json"), "{}");
    expect(await publishCaseArchive(options)).toEqual({
      metadata: 2,
      cases: 1,
    });
    const history = JSON.parse(
      await readFile(join(destination, "history.json"), "utf8"),
    );
    expect(history.prs.map((p: any) => p.prId)).toEqual([1, 3]);
    await expect(
      readFile(join(destination, "metadata/2.json")),
    ).rejects.toThrow();
    const uncertain = JSON.parse(
      await readFile(join(destination, "metadata/3.json"), "utf8"),
    );
    expect(uncertain.processing).toMatchObject({
      status: "inconclusive",
      reason: "no faithful pair",
    });
    const publishedSelection = JSON.parse(
      await readFile(join(destination, "selection.json"), "utf8"),
    );
    expect(publishedSelection.prIds).toEqual([1, 3]);
    const saved = JSON.parse(
      await readFile(join(destination, "cases/1/case.json"), "utf8"),
    );
    expect(saved.validation.runtime.rustc).toBeUndefined();
    expect(saved.validation.oracles[0].result.stdout).toBe("/home/literal\n");
    expect(saved.validation.oracles[0].result.stderr).not.toContain(
      "/Users/local",
    );
    expect(
      await readFile(join(destination, "cases/1/original.rs"), "utf8"),
    ).toBe(sources[0]);
    expect(
      await readFile(join(destination, "cases/1/original.mir"), "utf8"),
    ).toBe("// original.rs\nMIR fixture\n");
    await writeFile(join(root, artifact, "original.mir"), "corrupted artifact");
    await expect(publishCaseArchive(options)).rejects.toThrow(
      "MIR artifact hash mismatch",
    );
    await rm(join(root, "pipeline/fixture/3-" + head + ".json"));
    await expect(publishCaseArchive(options)).rejects.toThrow(
      "every selected PR",
    );
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});
