import { expect, it, vi } from "vitest";
import { runTwoPhases, PHASE1_TOOLS, PHASE2_TOOLS } from "./phases.js";
import { createReviewTools, type ReviewToolContext } from "./tools.js";
import type { AgentSession } from "@earendil-works/pi-coding-agent";

const strategy = {
  name: "nested delimiters",
  target: "parser",
  rationale: "check replay",
  expectedIssue: "truncated tokens",
};
function context(): ReviewToolContext {
  return {
    pr: {} as any,
    build: { patchedDir: process.cwd() } as any,
    strategies: [],
    evidence: [],
    knowledge: [],
    report: "",
  };
}

it("requires structured stop before switching tools, retains one session and records both phases", async () => {
  const ctx = context();
  const tools = createReviewTools(ctx);
  let listener: (event: any) => void = () => {};
  const active: string[][] = [];
  const session = {
    state: { messages: [] },
    abort: vi.fn(async () => {}),
    subscribe(fn: typeof listener) {
      listener = fn;
      return () => {};
    },
    setActiveToolsByName(names: string[]) {
      active.push(names);
    },
    prompt: vi.fn(async () => {
      if (ctx.phase === 1) {
        await tools
          .find((t) => t.name === "stop")!
          .execute(
            "stop-1",
            { thoughts: "analysis", strategies: [strategy] },
            undefined,
            undefined,
            {} as any,
          );
      } else ctx.report = "Evidence-backed report";
      listener({ type: "turn_end" });
      throw new DOMException("This operation was aborted", "AbortError");
    }),
  } as unknown as AgentSession;
  const phases = await runTwoPhases(session, ctx, "PR source", 1000);
  expect(active).toEqual([PHASE1_TOOLS, PHASE2_TOOLS]);
  expect(phases.map((p) => p.phase)).toEqual([1, 2]);
  expect(session.abort).toHaveBeenCalledTimes(2);
  expect(ctx.analysis?.strategies).toEqual([strategy]);
});

it("ordinary assistant text cannot skip Phase 1", async () => {
  const ctx = context();
  const setTools = vi.fn();
  const session = {
    state: { messages: [] },
    subscribe: () => () => {},
    setActiveToolsByName: setTools,
    prompt: vi.fn(async () => {}),
    abort: vi.fn(),
  } as unknown as AgentSession;
  await expect(runTwoPhases(session, ctx, "PR", 1000)).rejects.toThrow(
    "Phase 1 did not call stop",
  );
  expect(setTools).toHaveBeenCalledTimes(1);
});

it("blocks execution in Phase 1 and rejects unknown strategies or untested reports in Phase 2", async () => {
  const ctx = context();
  const tools = createReviewTools(ctx);
  const execute = (name: string, params: any) =>
    tools
      .find((t) => t.name === name)!
      .execute("test", params, undefined, undefined, {} as any);
  ctx.phase = 1;
  await expect(
    execute("differential_test", { source: "fn main(){}" }),
  ).rejects.toThrow("unavailable in Phase 1");
  await execute("stop", { thoughts: "analysis", strategies: [strategy] });
  ctx.phase = 2;
  expect(tools.map((tool) => tool.name)).not.toContain("save_strategy");
  await expect(
    execute("stop", { thoughts: "replace", strategies: [] }),
  ).rejects.toThrow("frozen");
  await expect(
    execute("differential_test", {
      source: "fn main(){}",
      strategy: "invented",
    }),
  ).rejects.toThrow("exact Phase 1");
  await expect(execute("submit_report", { report: "clean" })).rejects.toThrow(
    "Untested strategies",
  );
});

it("binds Phase 1 strategies to exact pass IDs and requires coverage for each concrete pass", async () => {
  const ctx = context();
  ctx.phase = 1;
  ctx.pr.passes = ["GVN", "CopyProp"].map((id) => ({
    id,
    name: id,
    kind: "pass",
    confidence: "high",
    evidence: [id],
  }));
  const stop = createReviewTools(ctx).find((tool) => tool.name === "stop")!;
  const execute = (strategies: any[]) =>
    stop.execute(
      "stop",
      { thoughts: "analysis", strategies },
      undefined,
      undefined,
      {} as any,
    );
  await expect(
    execute([{ ...strategy, passId: "rustc_mir_transform" }]),
  ).rejects.toThrow("exact classified passId");
  await expect(execute([{ ...strategy, passId: "GVN" }])).rejects.toThrow(
    "CopyProp",
  );
  await execute([
    { ...strategy, passId: "GVN" },
    { ...strategy, name: "copy", passId: "CopyProp" },
  ]);
  expect(ctx.analysis?.strategies.map((s) => s.passId)).toEqual([
    "GVN",
    "CopyProp",
  ]);
});

it("preserves committed phase results if a subsequent model request fails", async () => {
  const ctx = context();
  let listener: (event: any) => void = () => {};
  const session = {
    state: { messages: [] as any[] },
    subscribe(fn: any) {
      listener = fn;
      return () => {};
    },
    setActiveToolsByName: vi.fn(),
    abort: vi.fn(),
    prompt: vi.fn(async () => {
      if (ctx.phase === 1)
        ctx.analysis = { thoughts: "source inspected", strategies: [strategy] };
      else ctx.report = "tested report";
      listener({ type: "turn_end" });
      throw new Error("Connection error after committed tool result");
    }),
  } as unknown as AgentSession;
  expect(
    (await runTwoPhases(session, ctx, "source", 1000)).map((p) => p.phase),
  ).toEqual([1, 2]);
});
