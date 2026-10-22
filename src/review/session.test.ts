import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it, vi } from "vitest";
import { createReviewSession } from "./session.js";
import type { ReviewToolContext } from "./tools.js";

it("replays thinking across Pi tool rounds and exposes only Rust review tools", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-pi-test-"));
  const requests: any[] = [];
  vi.stubEnv("ARCHER_LM_API_KEY", "test-key");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: unknown, init: RequestInit) => {
      const body = JSON.parse(String(init.body));
      requests.push(body);
      const round = requests.length;
      const call =
        round === 1
          ? {
              name: "stop",
              arguments: JSON.stringify({
                thoughts: "Inspect nested delimiters",
                strategies: [
                  {
                    name: "cursor",
                    target: "parser",
                    rationale: "nested delimiters",
                    expectedIssue: "truncated tokens",
                  },
                ],
              }),
            }
          : round === 2
            ? {
                name: "submit_report",
                arguments: JSON.stringify({ report: "Test report." }),
              }
            : undefined;
      const chunks = [
        {
          choices: [
            {
              index: 0,
              delta: {
                role: "assistant",
                reasoning_content: `thinking round ${round}`,
              },
              finish_reason: null,
            },
          ],
        },
        {
          choices: [
            {
              index: 0,
              delta: call
                ? {
                    tool_calls: [
                      {
                        index: 0,
                        id: `call-${round}`,
                        type: "function",
                        function: call,
                      },
                    ],
                  }
                : { content: "Done." },
              finish_reason: null,
            },
          ],
        },
        {
          choices: [
            {
              index: 0,
              delta: {},
              finish_reason: call ? "tool_calls" : "stop",
            },
          ],
        },
      ];
      return new Response(
        chunks
          .map(
            (chunk) =>
              `data: ${JSON.stringify({ id: `test-${round}`, object: "chat.completion.chunk", created: 0, model: "test", ...chunk })}\n\n`,
          )
          .join("") + "data: [DONE]\n\n",
        { headers: { "content-type": "text/event-stream" } },
      );
    }),
  );
  const context: ReviewToolContext = {
    pr: {
      id: 42,
      url: "https://github.com/rust-lang/rust/pull/42",
      headSha: "head",
    } as any,
    build: {
      baseDir: root,
      patchedDir: root,
      baselineRustc: "unused",
      patchedRustc: "unused",
    },
    evidence: [],
    strategies: [],
    knowledge: [],
    report: "",
  };
  let session:
    Awaited<ReturnType<typeof createReviewSession>>["session"] | undefined;
  try {
    ({ session } = await createReviewSession(context, {
      modelEndpoint: "https://archer-test.invalid/v1",
      modelApiKey: "test-key",
      model: "test",
      buildRoot: root,
      outputDir: root,
      buildTimeoutMs: 1000,
      host: "127.0.0.1",
      port: 0,
      agentTimeoutMs: 10_000,
    }));
    expect(session.getActiveToolNames()).toContain("differential_test");
    expect(session.getActiveToolNames()).not.toContain("bash");
    await session.prompt("Save a strategy, then submit a report.");
    expect(context.strategies).toHaveLength(1);
    expect(context.report).toBe("Test report.");
    expect(requests).toHaveLength(3);
    expect(requests[0].messages[0].role).toBe("system");
    expect(
      requests[1].messages.find((m: any) => m.role === "assistant")
        .reasoning_content,
    ).toBe("thinking round 1");
    const assistants = requests[2].messages.filter(
      (m: any) => m.role === "assistant",
    );
    expect(assistants.map((m: any) => m.reasoning_content)).toEqual([
      "thinking round 1",
      "thinking round 2",
    ]);
  } finally {
    session?.dispose();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    await rm(root, { recursive: true, force: true });
  }
}, 15_000);
