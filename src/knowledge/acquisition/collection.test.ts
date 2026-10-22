import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ request: vi.fn(), fetchPr: vi.fn() }));
vi.mock("../../infra/github.js", () => ({
  githubRequest: mocks.request,
  fetchRustPr: mocks.fetchPr,
}));
import { collectHistory } from "../history.js";

it("splits searches above 1000 results and defaults to uncapped collection with resumable raw records", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-all-history-test-"));
  const searches: string[] = [];
  mocks.request.mockImplementation(async (url: string) => {
    if (url.includes("search/issues")) {
      const q = new URL(url).searchParams.get("q")!;
      searches.push(q);
      const full = q.includes("2024-01-01T00:00:00Z..2025-12-31T23:59:59Z");
      const id = q.includes("merged:2024-01-01") ? 101 : 202;
      return Response.json({
        total_count: full ? 1001 : 1,
        incomplete_results: false,
        items: full ? [] : [{ number: id }],
      });
    }
    if (url.includes("/files?"))
      return Response.json([
        { filename: "compiler/rustc_mir_transform/gvn.rs" },
      ]);
    return Response.json({ merged_at: "2024-06-01T00:00:00Z" });
  });
  mocks.fetchPr.mockImplementation(async (id: number) => ({
    id,
    headSha: `head${id}`,
    title: "MIR optimization",
    body: "",
    files: ["compiler/rustc_mir_transform/gvn.rs"],
    components: ["rustc_mir_transform"],
    patch: "test",
  }));
  const config = { outputDir: root } as any;
  try {
    await collectHistory(config, { query: "label:A-mir-opt" });
    const directory = join(root, "knowledge/history");
    expect((await readdir(join(directory, "raw"))).sort()).toEqual([
      "101-head101.json",
      "202-head202.json",
    ]);
    expect(searches).toHaveLength(3);
    const state = JSON.parse(
      await readFile(join(directory, "collection.json"), "utf8"),
    );
    expect(state.limit).toBe("all");
    expect(state.status).toBe("complete");
    expect(state.scopeComplete).toBe(false);
    expect(state.newRecords).toBe(2);
    await collectHistory(config, { query: "label:A-mir-opt" });
    expect(await readdir(join(directory, "raw"))).toHaveLength(2);
    expect(
      JSON.parse(await readFile(join(directory, "collection.json"), "utf8"))
        .newRecords,
    ).toBe(0);
  } finally {
    await rm(root, { recursive: true, force: true });
    vi.clearAllMocks();
  }
});

it("has no default label gate, keeps test-only PRs and audits unrelated PRs", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-test-only-"));
  const searches: string[] = [];
  mocks.request.mockImplementation(async (url: string) => {
    if (url.includes("search/issues")) {
      searches.push(new URL(url).searchParams.get("q")!);
      return Response.json({
        total_count: 2,
        incomplete_results: false,
        items: [
          { number: 301, title: "Test regression", labels: [] },
          { number: 302, title: "Docs", labels: [{ name: "T-doc" }] },
        ],
      });
    }
    if (url.includes("/files?"))
      return Response.json([
        {
          filename: url.includes("/301/")
            ? "tests/ui/codegen/issue.rs"
            : "src/doc/book.md",
        },
      ]);
    return Response.json({ merged_at: "2024-06-01T00:00:00Z" });
  });
  mocks.fetchPr.mockResolvedValue({
    id: 301,
    headSha: "testhead",
    title: "Test regression",
    body: "",
    files: ["tests/ui/codegen/issue.rs"],
    patch: "",
    components: [],
  });
  try {
    const historical = join(root, "knowledge/history");
    await mkdir(historical, { recursive: true });
    // This test-only PR was negatively assessed by the old narrow file filter.
    await writeFile(
      join(historical, "assessments.jsonl"),
      JSON.stringify({
        id: 301,
        filterVersion: "compiler-and-mir-tests-pass-v1",
      }) + "\n",
    );
    await collectHistory({ outputDir: root } as any, {});
    expect(
      searches.every((q) => !q.includes("label:") && !q.includes("in:title")),
    ).toBe(true);
    const directory = join(root, "knowledge/history");
    expect(await readdir(join(directory, "raw"))).toEqual([
      "301-testhead.json",
    ]);
    expect((await readdir(join(directory, "inventory"))).sort()).toEqual([
      "301.json",
      "302.json",
    ]);
    expect(
      JSON.parse(await readFile(join(directory, "inventory/302.json"), "utf8")),
    ).toMatchObject({
      decision: "outside-compiler-and-test-paths",
      labels: ["T-doc"],
      files: ["src/doc/book.md"],
    });
    expect(
      JSON.parse(await readFile(join(directory, "collection.json"), "utf8")),
    ).toMatchObject({
      scopeComplete: true,
      enumeratedThisRun: 2,
      assessedTotal: 2,
    });
  } finally {
    await rm(root, { recursive: true, force: true });
    vi.clearAllMocks();
  }
});
