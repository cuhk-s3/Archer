import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  extract: vi.fn(),
  verify: vi.fn(),
  synthesize: vi.fn(),
}));
vi.mock("./history.js", () => ({ extractHistory: mocks.extract }));
vi.mock("./verification/program-pair.js", () => ({
  knowledgeRuntime: async () => ({
    toolchain: "fixture",
    rustc: "fixture",
    rustcVersion: "fixture",
    miriVersion: "fixture",
  }),
  verifyProgramPair: mocks.verify,
}));
vi.mock("./synthesis.js", () => ({
  synthesizePassKnowledge: mocks.synthesize,
}));
vi.mock("./acquisition/screening.js", () => ({
  screenUnrelatedHistory: async () => {},
}));
import { runKnowledgePipeline } from "./pipeline.js";
it("lets an idle worker take a newly collected PR while another verification is still running", async () => {
  const output = await mkdtemp(join(tmpdir(), "archer-live-queue-")),
    root = join(output, "knowledge/history");
  const name = (id: number) => `${id}-${String(id).repeat(40)}.json`;
  const raw = (id: number) => ({
    mergedAt: "2024-05-01T00:00:00Z",
    issues: [],
    pr: {
      id,
      headSha: String(id).repeat(40),
      title: "GVN",
      body: "",
      patch: "",
      files: ["compiler/rustc_mir_transform/src/gvn.rs"],
    },
  });
  await mkdir(join(root, "raw"), { recursive: true });
  await mkdir(join(root, "records"));
  await writeFile(join(root, "raw", name(1)), JSON.stringify(raw(1)));
  await writeFile(
    join(root, "collection.json"),
    JSON.stringify({ status: "collecting" }),
  );
  let releaseFirst: () => void = () => {},
    firstStarted: () => void = () => {};
  const blocked = new Promise<void>((r) => {
      releaseFirst = r;
    }),
    started = new Promise<void>((r) => {
      firstStarted = r;
    });
  mocks.extract.mockImplementation(async (_config, _limit, options) => {
    await writeFile(
      join(root, "records", name(options.prId)),
      JSON.stringify({ model: "fixture", prId: options.prId }),
    );
  });
  mocks.verify.mockImplementation(async (_config, _root, _name, analysis) => {
    if (analysis.prId === 1) {
      await writeFile(join(root, "raw", name(2)), JSON.stringify(raw(2)));
      firstStarted();
      await blocked;
    } else {
      await writeFile(
        join(root, "collection.json"),
        JSON.stringify({ status: "complete" }),
      );
      releaseFirst();
    }
    return { certificate: { pairHash: "fixture" } };
  });
  mocks.synthesize.mockResolvedValue(
    new Set([name(1).slice(0, -5), name(2).slice(0, -5)]),
  );
  vi.useFakeTimers();
  let running: Promise<void> | undefined;
  try {
    running = runKnowledgePipeline(
      { outputDir: output, model: "fixture" } as any,
      { follow: true, concurrency: 2 },
    );
    await started;
    await vi.waitFor(
      () =>
        expect(mocks.verify.mock.calls.some((call) => call[3].prId === 2)).toBe(
          true,
        ),
      { timeout: 25000, interval: 1000 },
    );
    await running;
    expect(
      JSON.parse(await readFile(join(root, "pipeline-status.json"), "utf8"))
        .counts,
    ).toEqual({ complete: 2 });
  } finally {
    releaseFirst();
    await running;
    vi.useRealTimers();
    vi.clearAllMocks();
    await rm(output, { recursive: true, force: true });
  }
}, 30000);
