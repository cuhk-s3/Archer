import {
  mkdtemp,
  mkdir,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ session: vi.fn(), request: vi.fn() }));
vi.mock("../../infra/pi.js", () => ({ createPiSession: mocks.session }));
vi.mock("../../infra/github.js", () => ({ githubRequest: mocks.request }));
import {
  classifyHistoricalPr,
  implementedPasses,
  migrateUnclassified,
} from "./classification.js";
it("requeues rule-only exclusions without changing explicit LLM exclusions, and is resumable", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-migrate-"));
  try {
    await mkdir(join(root, "skipped"));
    await writeFile(
      join(root, "skipped/1.json"),
      JSON.stringify({ prId: 1, reason: "No concrete MIR pass identified" }),
    );
    await writeFile(
      join(root, "skipped/2.json"),
      JSON.stringify({
        prId: 2,
        reason: "Pure cleanup",
        evidence: ["quoted source"],
      }),
    );
    expect(await migrateUnclassified(root)).toBe(1);
    expect(await readdir(join(root, "skipped"))).toEqual(["2.json"]);
    expect(
      JSON.parse(await readFile(join(root, "pending/1.json"), "utf8")).status,
    ).toBe("awaiting-analysis");
    expect(await migrateUnclassified(root)).toBe(0);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
it("recognizes actual MirPass/MirLint implementations, not queries or type mentions", () => {
  expect(
    implementedPasses(
      "impl<'tcx> MirLint<'tcx> for ConstPropLint { }\nimpl<'tcx> crate::MirPass<'tcx> for NewPass {}\nstruct NotAPass; fn provide() {}",
    ),
  ).toEqual(["ConstPropLint", "NewPass"]);
  expect(implementedPasses("fn foo(x: NewPass) {}\nstruct SSA;")).toEqual([]);
});
it("inspects historical implementations before accepting missing passes and caches the decision", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-classify-"));
  const implementation = "impl<'tcx> MirLint<'tcx> for HistoricalLint { }";
  mocks.request.mockResolvedValue(Response.json({}));
  mocks.request.mockImplementation(async () => new Response(implementation));
  mocks.session.mockImplementation(async (_config, _cwd, tools) => ({
    session: {
      prompt: async () => {
        const assign = tools.find(
          (t: any) => t.name === "assign_historical_passes",
        );
        const input = {
          reason: "changed lint logic",
          assignments: [
            {
              passId: "HistoricalLint",
              module: "historical_lint",
              evidence: ["changed lint logic in the PR", implementation],
            },
          ],
        };
        await expect(assign.execute("1", input)).rejects.toThrow(
          "exact quotations",
        );
        await tools
          .find((t: any) => t.name === "inspect_rust_pass_source")
          .execute("2", {
            path: "compiler/rustc_mir_transform/src/historical_lint.rs",
          });
        await assign.execute("3", input);
      },
      abort: vi.fn(),
      dispose: vi.fn(),
    },
  }));
  const raw = {
    pr: {
      id: 1,
      headSha: "a".repeat(40),
      title: "changed lint logic in the PR",
      body: "",
      patch: "",
      files: [],
    } as any,
    issues: [],
  };
  try {
    const result = await classifyHistoricalPr(
      { agentTimeoutMs: 10000 } as any,
      root,
      "1.json",
      raw,
      [],
    );
    expect(result.verdict).toBe("assigned");
    expect(result.passes[0]!.id).toBe("HistoricalLint");
    expect(
      (await classifyHistoricalPr({} as any, root, "1.json", raw, [])).verdict,
    ).toBe("assigned");
    expect(mocks.session).toHaveBeenCalledTimes(1);
  } finally {
    await rm(root, { recursive: true, force: true });
    vi.clearAllMocks();
  }
});

it("continues pending investigations from cached source and permits actual passes outside mir_transform", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-cached-classification-")),
    head = "b".repeat(40);
  const path = "compiler/rustc_const_eval/src/transform/validate.rs";
  const implementation = "impl<'tcx> MirPass<'tcx> for Validator { }";
  const reason =
    "Already found Validator; inspect its changed validation logic.";
  await mkdir(join(root, "classification"), { recursive: true });
  await mkdir(join(root, "pass-sources", head), { recursive: true });
  await writeFile(
    join(root, "classification/2.json"),
    JSON.stringify({
      model: "fixture",
      version: "source-backed-llm-v1",
      headSha: head,
      verdict: "pending",
      reason,
    }),
  );
  await writeFile(
    join(root, "pass-sources", head, path.replaceAll("/", "__")),
    implementation,
  );
  mocks.request.mockClear();
  mocks.session.mockImplementation(async (_config, _cwd, tools) => ({
    session: {
      prompt: async (prompt: string) => {
        expect(prompt).toContain(reason);
        await tools
          .find((t: any) => t.name === "inspect_rust_pass_source")
          .execute("1", { path });
        await tools
          .find((t: any) => t.name === "assign_historical_passes")
          .execute("2", {
            reason: "Concrete validator behavior",
            assignments: [
              {
                passId: "Validator",
                module: "validate",
                sourcePath: path,
                evidence: ["changed validation logic in PR", implementation],
              },
            ],
          });
      },
      abort: vi.fn(),
      dispose: vi.fn(),
    },
  }));
  try {
    const result = await classifyHistoricalPr(
      { model: "fixture", agentTimeoutMs: 10000 } as any,
      root,
      "2.json",
      {
        pr: {
          id: 2,
          headSha: head,
          title: "changed validation logic in PR",
          body: "",
          patch: "",
          files: [],
        } as any,
        issues: [],
      },
      [],
    );
    expect(result.passes[0]?.id).toBe("Validator");
    expect(mocks.request).not.toHaveBeenCalled();
  } finally {
    await rm(root, { recursive: true, force: true });
    vi.clearAllMocks();
  }
});
