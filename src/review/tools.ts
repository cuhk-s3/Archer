import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";
import { Type } from "@sinclair/typebox";
import {
  defineTool,
  type ToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { nativeBuildEnvironment } from "../rust/toolchain.js";
import type { BuiltRustPr } from "../rust/toolchain.js";
import type {
  KnowledgeRecord,
  RustPullRequest,
  TestStrategy,
  ToolEvidence,
} from "../types.js";
import { run } from "../infra/process.js";

const textResult = (text: string) => ({
  content: [{ type: "text" as const, text }],
  details: {},
});

export interface RustTestOptions {
  mirOptLevel?: number;
  mirPasses?: string[];
}
export function rustTestFlags(options: RustTestOptions = {}): string[] {
  if (
    options.mirOptLevel !== undefined &&
    (!Number.isInteger(options.mirOptLevel) ||
      options.mirOptLevel < 0 ||
      options.mirOptLevel > 4)
  )
    throw new Error("Invalid MIR optimization level");
  if (options.mirPasses?.some((p) => !/^[+-][A-Z][A-Za-z0-9_]*$/.test(p)))
    throw new Error("Invalid concrete MIR pass selector");
  return [
    ...(options.mirOptLevel === undefined
      ? []
      : [`-Zmir-opt-level=${options.mirOptLevel}`]),
    ...(options.mirPasses?.length
      ? [`-Zmir-enable-passes=${options.mirPasses.join(",")}`]
      : []),
  ];
}

export async function runRustc(
  rustc: string,
  source: string,
  optLevel: "0" | "3",
  options: RustTestOptions = {},
) {
  const dir = await mkdtemp(join(tmpdir(), "archer-rust-"));
  const sourcePath = join(dir, "main.rs");
  const binary = join(dir, "case");
  const { writeFile } = await import("node:fs/promises");
  await writeFile(sourcePath, source, "utf8");
  try {
    const result = await run(
      rustc,
      [
        "--edition=2021",
        `-Copt-level=${optLevel}`,
        ...rustTestFlags(options),
        sourcePath,
        "-o",
        binary,
      ],
      { check: false, timeoutMs: 60_000, env: await nativeBuildEnvironment() },
    );
    return { ...result, binary, dir };
  } catch (error) {
    await rm(dir, { recursive: true, force: true });
    throw error;
  }
}

export async function miri(
  source: string,
  timeoutMs = 120_000,
  toolchainOverride?: string,
) {
  const found = await run("which", ["rustup"], { check: false });
  const rustup =
    process.env.RUSTUP ?? (found.stdout.trim() || "/opt/homebrew/bin/rustup");
  const toolchain =
    toolchainOverride ?? process.env.LAB_MIRI_TOOLCHAIN ?? "nightly";
  const located = await run(
    rustup,
    ["which", "cargo", "--toolchain", toolchain],
    { check: false },
  );
  if (located.code !== 0)
    return {
      status: "unavailable",
      stdout: "",
      stderr: located.stderr || "nightly cargo is unavailable",
    };
  const cargo = located.stdout.trim();
  const bin = dirname(cargo);
  const dir = await mkdtemp(join(tmpdir(), "archer-miri-"));
  const { mkdir, writeFile } = await import("node:fs/promises");
  const src = join(dir, "src");
  await mkdir(src);
  await writeFile(
    join(dir, "Cargo.toml"),
    '[package]\nname="archer_repro"\nversion="0.0.0"\nedition="2021"\n',
  );
  await writeFile(join(src, "main.rs"), source);
  try {
    const result = await run(cargo, ["miri", "run", "--offline", "--quiet"], {
      cwd: dir,
      env: {
        ...(await nativeBuildEnvironment(resolve(bin))),
        CARGO_TARGET_DIR: join(dir, "target"),
      },
      timeoutMs,
      check: false,
    });
    const status = /Undefined Behavior|undefined behavior/i.test(result.stderr)
      ? "undefined_behavior"
      : result.code === 0
        ? "ok"
        : "inconclusive";
    return { ...result, status };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

export interface ReviewToolContext {
  pr: RustPullRequest;
  build: BuiltRustPr;
  evidence: ToolEvidence[];
  strategies: TestStrategy[];
  knowledge: KnowledgeRecord[];
  report: string;
  phase?: 1 | 2;
  analysis?: { thoughts: string; strategies: TestStrategy[] };
}

export function createReviewTools(
  context: ReviewToolContext,
): ToolDefinition[] {
  const root = resolve(context.build.patchedDir);
  const ensureInRoot = (relativePath: string): string => {
    const path = resolve(root, relativePath);
    if (path !== root && !path.startsWith(root + sep))
      throw new Error("Path escapes the Rust source checkout");
    return path;
  };
  const tools: ToolDefinition[] = [
    defineTool({
      name: "stop",
      label: "Finish Phase 1",
      description:
        "Finish analysis with reasoning and the complete structured list of test strategies. Required to transition to Phase 2.",
      parameters: Type.Object({
        thoughts: Type.String(),
        strategies: Type.Array(
          Type.Object({
            name: Type.String(),
            target: Type.String(),
            rationale: Type.String(),
            expectedIssue: Type.String(),
            passId: Type.Optional(Type.String()),
          }),
          { minItems: 1 },
        ),
      }),
      execute: async (_id, p) => {
        if (
          new Set(p.strategies.map((s) => s.name)).size !== p.strategies.length
        )
          throw new Error("Strategy names must be unique");
        if (context.pr.passes?.length) {
          if (
            p.strategies.some(
              (s) => !context.pr.passes!.some((pass) => pass.id === s.passId),
            )
          )
            throw new Error(
              "Each strategy must reference an exact classified passId",
            );
          const missing = context.pr.passes.filter(
            (pass) =>
              pass.kind === "pass" &&
              !p.strategies.some((s) => s.passId === pass.id),
          );
          if (missing.length)
            throw new Error(
              `Missing strategies for passes: ${missing.map((pass) => pass.id).join(", ")}`,
            );
        }
        context.strategies = p.strategies;
        context.analysis = structuredClone(p);
        return textResult(JSON.stringify(p));
      },
    }),
    defineTool({
      name: "rust_read",
      label: "Read Rust source",
      description:
        "Read a file in the Rust compiler checkout. Paths are relative to repository root.",
      parameters: Type.Object({
        path: Type.String(),
        startLine: Type.Optional(Type.Integer({ minimum: 1 })),
        endLine: Type.Optional(Type.Integer({ minimum: 1 })),
      }),
      execute: async (_id, p) => {
        try {
          const file = ensureInRoot(p.path);
          const lines = (await readFile(file, "utf8")).split("\n");
          const start = Math.max(1, p.startLine ?? 1);
          const end = Math.min(lines.length, p.endLine ?? start + 200);
          return textResult(
            `${p.path}:${start}-${end}\n${lines
              .slice(start - 1, end)
              .map((l, i) => `${start + i}: ${l}`)
              .join("\n")}`,
          );
        } catch (error) {
          return textResult(`Read failed: ${String(error)}`);
        }
      },
    }),
    defineTool({
      name: "rust_search",
      label: "Search Rust source",
      description:
        "Search source code and tests with ripgrep. Use a focused literal or regex pattern.",
      parameters: Type.Object({
        pattern: Type.String(),
        path: Type.Optional(Type.String()),
      }),
      execute: async (_id, p) => {
        const cwd = p.path ? ensureInRoot(p.path) : root;
        const result = await run(
          "rg",
          [
            "-n",
            "--max-count",
            "20",
            "--glob",
            "!build/**",
            "--glob",
            "!target/**",
            p.pattern,
            ".",
          ],
          { cwd, check: false, timeoutMs: 20_000 },
        );
        return textResult(result.stdout || result.stderr || "No matches.");
      },
    }),
    defineTool({
      name: "rust_list",
      label: "List Rust source files",
      description:
        "List files in the Rust compiler repository, relative to a directory.",
      parameters: Type.Object({ path: Type.Optional(Type.String()) }),
      execute: async (_id, p) => {
        try {
          const dir = ensureInRoot(p.path ?? ".");
          const children = (await readdir(dir, { withFileTypes: true }))
            .filter(
              (x) =>
                !x.name.startsWith(".") &&
                !["build", "target"].includes(x.name),
            )
            .slice(0, 250);
          return textResult(
            children
              .map((x) => `${x.isDirectory() ? "d" : "f"} ${x.name}`)
              .join("\n"),
          );
        } catch (error) {
          return textResult(`List failed: ${String(error)}`);
        }
      },
    }),
    defineTool({
      name: "compile_rust",
      label: "Compile Rust program",
      description:
        "Compile a standalone Rust program using the PR's patched rustc at the requested optimization level.",
      parameters: Type.Object({
        source: Type.String(),
        optLevel: Type.Union([Type.Literal("0"), Type.Literal("3")]),
        strategy: Type.Optional(Type.String()),
      }),
      execute: async (_id, p) => {
        const result = await runRustc(
          context.build.patchedRustc,
          p.source,
          p.optLevel,
        );
        await rm(result.dir, { recursive: true, force: true });
        const evidence: ToolEvidence = {
          tool: "compile_rust",
          status: result.code === 0 ? "ok" : "failed",
          source: p.source,
          stdout: result.stdout,
          stderr: result.stderr,
          strategy: p.strategy,
        };
        context.evidence.push(evidence);
        return textResult(JSON.stringify(evidence));
      },
    }),
    defineTool({
      name: "run_miri",
      label: "Check with Miri",
      description:
        "Run a standalone Rust program under nightly Miri. Miri rejects undefined behavior but is not an equivalence oracle.",
      parameters: Type.Object({
        source: Type.String(),
        strategy: Type.Optional(Type.String()),
      }),
      execute: async (_id, p) => {
        const result = await miri(p.source);
        const evidence: ToolEvidence = {
          tool: "run_miri",
          status: result.status,
          clean: result.status === "ok",
          source: p.source,
          stdout: result.stdout,
          stderr: result.stderr,
          strategy: p.strategy,
        };
        context.evidence.push(evidence);
        return textResult(JSON.stringify(evidence));
      },
    }),
    defineTool({
      name: "differential_test",
      label: "Compare base and PR rustc",
      description:
        "First run Miri; if clean, compile and execute with base and patched rustc at O0 and O3 and compare status/stdout/stderr.",
      parameters: Type.Object({
        source: Type.String(),
        strategy: Type.Optional(Type.String()),
      }),
      execute: async (_id, p) => {
        const oracle = await miri(p.source);
        if (oracle.status !== "ok") {
          const rejected = {
            tool: "differential_test",
            status: oracle.status,
            miriClean: false,
            found: false,
            source: p.source,
            log: oracle.stderr,
            strategy: p.strategy,
          };
          context.evidence.push(rejected);
          return textResult(JSON.stringify(rejected));
        }
        const runs: Array<Record<string, unknown>> = [];
        for (const [level, rustc] of [
          ["0", context.build.baselineRustc],
          ["0", context.build.patchedRustc],
          ["3", context.build.baselineRustc],
          ["3", context.build.patchedRustc],
        ] as const) {
          const label = `${rustc === context.build.baselineRustc ? "base" : "patched"}-O${level}`;
          const compiled = await runRustc(rustc, p.source, level);
          if (compiled.code !== 0) {
            runs.push({
              label,
              compiled: false,
              code: compiled.code,
              stderr: compiled.stderr,
            });
            await rm(compiled.dir, { recursive: true, force: true });
            continue;
          }
          try {
            const executed = await run(compiled.binary, [], {
              check: false,
              timeoutMs: 10_000,
            });
            runs.push({
              label,
              compiled: !executed.timedOut && !executed.signal,
              code: executed.code,
              stdout: executed.stdout,
              stderr: executed.stderr,
            });
          } finally {
            await rm(compiled.dir, { recursive: true, force: true });
          }
        }
        const complete =
          runs.length === 4 && runs.every((r) => r.compiled === true);
        const outcomes = complete
          ? runs.map(({ label: _label, ...r }) => JSON.stringify(r))
          : [];
        const found = complete && new Set(outcomes).size > 1;
        const result = {
          tool: "differential_test",
          status: complete ? "ok" : "inconclusive",
          miriClean: true,
          found,
          source: p.source,
          runs,
          strategy: p.strategy,
        };
        context.evidence.push(result);
        return textResult(JSON.stringify(result));
      },
    }),
    defineTool({
      name: "save_knowledge",
      label: "Extract PR knowledge",
      description:
        "Save concise, evidence-backed learning about this Rust optimization PR for future reviews.",
      parameters: Type.Object({
        passId: Type.String(),
        summary: Type.String(),
        optimization: Type.String(),
        evidence: Type.Array(Type.String()),
      }),
      execute: async (_id, p) => {
        if (
          !context.pr.passes?.some(
            (pass) => pass.id === p.passId && pass.kind === "pass",
          )
        )
          throw new Error("Knowledge must use a concrete classified pass ID");
        const item: KnowledgeRecord = {
          prId: context.pr.id,
          headSha: context.pr.headSha,
          component: p.passId,
          passId: p.passId,
          summary: p.summary,
          optimization: p.optimization,
          evidence: p.evidence,
          sourceUrl: context.pr.url,
          extractedAt: new Date().toISOString(),
        };
        context.knowledge.push(item);
        return textResult(
          "Knowledge extraction recorded for " + item.component,
        );
      },
    }),
    defineTool({
      name: "submit_report",
      label: "Submit review report",
      description:
        "Finish the review with evidence and limitations. Findings must come from reproducible compiler behavior.",
      parameters: Type.Object({ report: Type.String() }),
      execute: async (_id, p) => {
        context.report = p.report;
        return textResult("Review report saved.");
      },
    }),
  ];
  return tools.map((tool) => ({
    ...tool,
    execute: async (...args: Parameters<typeof tool.execute>) => {
      if (
        context.phase === 1 &&
        !["rust_read", "rust_search", "rust_list", "stop"].includes(tool.name)
      )
        throw new Error("Tool unavailable in Phase 1");
      if (context.phase === 2 && tool.name === "stop")
        throw new Error("Phase 1 strategies are frozen");
      if (
        context.phase === 2 &&
        ["compile_rust", "run_miri", "differential_test"].includes(tool.name)
      ) {
        const strategy = (args[1] as { strategy?: string }).strategy;
        if (!context.strategies.some((s) => s.name === strategy))
          throw new Error("Use an exact Phase 1 strategy name");
      }
      if (tool.name === "submit_report" && context.phase === 2) {
        const missing = context.strategies.filter(
          (s) =>
            !context.evidence.some(
              (e) => e.tool === "differential_test" && e.strategy === s.name,
            ),
        );
        if (missing.length)
          throw new Error(
            `Untested strategies: ${missing.map((s) => s.name).join(", ")}`,
          );
      }
      const before = context.evidence.length;
      const result = await tool.execute(...args);
      for (const evidence of context.evidence.slice(before)) {
        const strategy = context.strategies.find(
          (s) => s.name === evidence.strategy,
        );
        if (strategy?.passId) evidence.passId = strategy.passId;
      }
      return result;
    },
  }));
}
