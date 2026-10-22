import { atomicJson, digest } from "../../infra/artifacts.js";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join, relative } from "node:path";
import type { ArcherConfig } from "../../config.js";
import { historyRoot } from "../corpus.js";
import { readVerifiedPairs } from "../synthesis.js";
import { pairSources } from "./program-pair.js";

import { checked } from "../../infra/process.js";
import { nativeBuildEnvironment } from "../../rust/toolchain.js";

/** Materialize the tested source pairs and their compiler-emitted MIR for inspection/replay. */
export async function exportPairArtifacts(
  config: ArcherConfig,
): Promise<number> {
  const root = historyRoot(config.outputDir),
    pairs = await readVerifiedPairs(root, config.model);
  const env = await nativeBuildEnvironment();
  for (const p of pairs) {
    const c = p.certificate,
      dir = join(
        root,
        "program-pair-artifacts",
        config.model.replace(/[^A-Za-z0-9_.-]/g, "_"),
        `${p.analysis.prId}-${p.analysis.headSha}`,
      );
    await mkdir(dir, { recursive: true });
    const sources = pairSources(c.pair);
    const files: Array<{
      source: string;
      sourceHash: string;
      mir: string;
      mirHash: string;
    }> = [];
    const currentVersion = await checked(c.runtime.rustc, ["-vV"], { env });
    if (currentVersion !== c.runtime.rustcVersion)
      throw new Error("Artifact compiler differs from execution certificate");
    for (const [i, label] of ["original", "transformed"].entries()) {
      const source = join(dir, `${label}.rs`),
        mir = join(dir, `${label}.mir`);
      let cached = false;
      try {
        const old = JSON.parse(
          await readFile(join(dir, "artifacts.json"), "utf8"),
        );
        const f = old.files[i];
        cached =
          old.pairHash === c.pairHash &&
          old.analysisHash === c.analysisHash &&
          digest(await readFile(source, "utf8")) === f.sourceHash &&
          digest(await readFile(mir, "utf8")) === f.mirHash;
      } catch {}
      if (!cached) {
        await writeFile(source, sources[i]!);
        await checked(
          c.runtime.rustc,
          [
            "--edition=2021",
            "--crate-name",
            "archer_case",
            "-Copt-level=0",
            "--emit=mir",
            source,
            "-o",
            mir,
          ],
          { env, timeoutMs: 60_000 },
        );
      }
      files.push({
        source: relative(root, source),
        sourceHash: digest(await readFile(source, "utf8")),
        mir: relative(root, mir),
        mirHash: digest(await readFile(mir, "utf8")),
      });
    }
    await atomicJson(join(dir, "artifacts.json"), {
      schema: 1,
      scope: c.scope,
      pairHash: c.pairHash,
      analysisHash: c.analysisHash,
      runtime: c.runtime,
      flags: ["--edition=2021", "-Copt-level=0", "--emit=mir"],
      files,
      exportedAt: new Date().toISOString(),
    });
  }
  console.log(`Exported tested Rust/MIR pairs: ${pairs.length}`);
  return pairs.length;
}
