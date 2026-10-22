import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";
import { loadPublishedKnowledge } from "./publication.js";
it("loads versioned knowledge without runtime caches and keeps pass files separate and editable", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-published-knowledge-"));
  try {
    await mkdir(join(root, "passes"));
    await writeFile(
      join(root, "manifest.json"),
      JSON.stringify({
        schema: 1,
        passes: [
          { id: "GVN", file: "passes/GVN.md" },
          { id: "CopyProp", file: "passes/CopyProp.md" },
        ],
      }),
    );
    await writeFile(
      join(root, "passes/GVN.md"),
      "# GVN\nTyped value numbering invariants.\n",
    );
    await writeFile(
      join(root, "passes/CopyProp.md"),
      "# CopyProp\nCopy propagation invariants.\n",
    );
    expect(await loadPublishedKnowledge(["GVN"], root)).toContain(
      "Typed value numbering",
    );
    expect(await loadPublishedKnowledge(["GVN"], root)).not.toContain(
      "Copy propagation invariants",
    );
    expect(await loadPublishedKnowledge(["Inline"], root)).toBeUndefined();
    await writeFile(
      join(root, "passes/GVN.md"),
      "# GVN\nMaintained test invariant.\n",
    );
    expect(await loadPublishedKnowledge(["GVN"], root)).toContain(
      "Maintained test invariant",
    );
    await writeFile(
      join(root, "passes/GVN.md"),
      "# GVN\n" + "x".repeat(100000),
    );
    const combined = await loadPublishedKnowledge(["GVN", "CopyProp"], root);
    expect(combined).toContain("# GVN");
    expect(combined).toContain("# CopyProp");
    expect(combined).toContain("Prompt excerpt");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
