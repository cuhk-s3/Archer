import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it, vi } from "vitest";
import { createReviewSession } from "./session.js";
import { runTwoPhases } from "./phases.js";
import type { ReviewToolContext } from "./tools.js";

vi.mock("../infra/process.js", () => ({
  run: async (command: string, args: string[]) => ({
    code: 0,
    stderr: "",
    stdout:
      command === "which"
        ? "/mock/rustup\n"
        : command === "/mock/rustup"
          ? "/mock/cargo\n"
          : command.endsWith("rustc")
            ? ""
            : "42\n",
  }),
}));

it("runs real Pi through stop → Phase 2 → differential_test → report with thinking replay", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-two-phase-pi-"));
  const requests: any[] = [];
  const strategy = {
    name: "boundary",
    target: "GVN",
    rationale: "check a range",
    expectedIssue: "overflow",
    passId: "GVN",
  };
  vi.stubEnv("ARCHER_LM_API_KEY", "test-key");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: unknown, init: RequestInit) => {
      requests.push(JSON.parse(String(init.body)));
      const round = requests.length;
      const call =
        round === 1
          ? {
              name: "stop",
              arguments: JSON.stringify({
                thoughts: "Inspect bounds",
                strategies: [strategy],
              }),
            }
          : round === 2
            ? {
                name: "differential_test",
                arguments: JSON.stringify({
                  source: 'fn main(){println!("42");}',
                  strategy: "boundary",
                }),
              }
            : {
                name: "submit_report",
                arguments: JSON.stringify({
                  report: "No difference observed in the boundary test.",
                }),
              };
      const chunks = [
        {
          delta: { role: "assistant", reasoning_content: `thinking ${round}` },
          finish_reason: null,
        },
        {
          delta: {
            tool_calls: [
              {
                index: 0,
                id: `call-${round}`,
                type: "function",
                function: call,
              },
            ],
          },
          finish_reason: null,
        },
        { delta: {}, finish_reason: "tool_calls" },
      ];
      return new Response(
        chunks
          .map(
            (choice) =>
              `data: ${JSON.stringify({ id: `test-${round}`, object: "chat.completion.chunk", created: 0, model: "test", choices: [{ index: 0, ...choice }] })}\n\n`,
          )
          .join("") + "data: [DONE]\n\n",
        { headers: { "content-type": "text/event-stream" } },
      );
    }),
  );
  const ctx: ReviewToolContext = {
    pr: {
      passes: [
        {
          id: "GVN",
          name: "GVN",
          kind: "pass",
          confidence: "high",
          evidence: ["gvn.rs"],
        },
      ],
    } as any,
    build: {
      baseDir: root,
      patchedDir: root,
      baselineRustc: "/base/rustc",
      patchedRustc: "/patched/rustc",
    },
    strategies: [],
    evidence: [],
    knowledge: [],
    report: "",
  };
  let session:
    Awaited<ReturnType<typeof createReviewSession>>["session"] | undefined;
  try {
    ({ session } = await createReviewSession(ctx, {
      modelEndpoint: "https://test.invalid/v1",
      modelApiKey: "test-key",
      model: "test",
      buildRoot: root,
      outputDir: root,
      buildTimeoutMs: 1000,
      host: "127.0.0.1",
      port: 0,
      agentTimeoutMs: 10_000,
    }));
    const phases = await runTwoPhases(session, ctx, "Analyze this PR.", 10_000);
    expect(phases.map((p) => p.phase)).toEqual([1, 2]);
    expect(ctx.report).toContain("No difference");
    expect(ctx.evidence[0]).toMatchObject({
      tool: "differential_test",
      status: "ok",
      found: false,
      strategy: "boundary",
      passId: "GVN",
    });
    expect(requests).toHaveLength(3);
    expect(requests[0].tools.map((t: any) => t.function.name)).not.toContain(
      "differential_test",
    );
    expect(requests[1].tools.map((t: any) => t.function.name)).toContain(
      "differential_test",
    );
    expect(requests[1].tools.map((t: any) => t.function.name)).not.toContain(
      "stop",
    );
    expect(
      requests[2].messages
        .filter((m: any) => m.role === "assistant")
        .map((m: any) => m.reasoning_content),
    ).toEqual(["thinking 1", "thinking 2"]);
  } finally {
    session?.dispose();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    await rm(root, { recursive: true, force: true });
  }
}, 15_000);
