import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ReviewStore } from "./store.js";
import type { ReviewRecord } from "../types.js";

function record(): ReviewRecord {
  return {
    id: "review-1",
    pr: {
      id: 42,
      url: "https://github.com/rust-lang/rust/pull/42",
      title: "Optimize token cursor",
      body: "",
      author: "rust",
      state: "open",
      baseSha: "base",
      headSha: "0123456789abcdef",
      patch: "diff",
      files: [],
      components: ["rustc_parse"],
      createdAt: "2026-01-01T00:00:00Z",
    },
    model: "test/model",
    startedAt: "2026-01-01T00:00:00Z",
    finishedAt: "2026-01-01T00:01:00Z",
    report: "No issue reproduced.",
    strategies: [],
    evidence: [{ tool: "differential_test", status: "ok", found: false }],
    knowledge: [
      {
        prId: 42,
        headSha: "0123456789abcdef",
        component: "rustc_parse",
        summary: "Cursor change",
        optimization: "Avoid clone",
        evidence: ["PR patch"],
        sourceUrl: "https://github.com/rust-lang/rust/pull/42",
        extractedAt: "2026-01-01T00:01:00Z",
      },
    ],
  };
}

describe("ReviewStore", () => {
  it("writes review, Markdown and knowledge, then lists by PR", async () => {
    const root = await mkdtemp(join(tmpdir(), "archer-store-test-"));
    try {
      const store = new ReviewStore(root);
      const paths = await store.save(record());
      expect((await store.get("review-1"))?.pr.id).toBe(42);
      expect((await store.list()).map((item) => item.id)).toEqual(["review-1"]);
      expect(await readFile(paths.reviewPath, "utf8")).toContain(
        "Optimize token cursor",
      );
      expect(
        await readFile(
          join(root, "reviews/42/0123456789ab-review-1.md"),
          "utf8",
        ),
      ).toContain("No issue reproduced.");
      expect(
        (await readFile(paths.knowledgePath, "utf8")).trim().split("\n"),
      ).toHaveLength(1);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
