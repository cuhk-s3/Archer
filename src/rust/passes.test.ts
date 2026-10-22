import { expect, it } from "vitest";
import {
  classifyPasses,
  getPassCatalog,
  catalogFromSnapshots,
} from "./passes.js";

it("separates GVN and CopyProp using concrete implementation files", () => {
  expect(
    classifyPasses(["compiler/rustc_mir_transform/src/gvn.rs"], "").map(
      (p) => p.id,
    ),
  ).toEqual(["GVN"]);
  expect(
    classifyPasses(["compiler/rustc_mir_transform/src/copy_prop.rs"], "").map(
      (p) => p.id,
    ),
  ).toEqual(["CopyProp"]);
  const cross = classifyPasses(
    [
      "compiler/rustc_mir_transform/src/gvn.rs",
      "compiler/rustc_mir_transform/src/copy_prop.rs",
    ],
    "",
  );
  expect(cross.map((p) => p.id)).toEqual(["CopyProp", "GVN"]);
});

it("uses MIR dump/EMIT_MIR names for test-only changes, not vague test directory names", () => {
  expect(
    classifyPasses(["tests/mir-opt/foo.GVN.diff"], "").map((p) => p.id),
  ).toEqual(["GVN"]);
  expect(
    classifyPasses(
      ["tests/mir-opt/foo.rs"],
      "+// EMIT_MIR foo.JumpThreading.diff",
    ).map((p) => p.id),
  ).toEqual(["JumpThreading"]);
  expect(
    classifyPasses(
      ["tests/mir-opt/foo.rs"],
      "+//@ test-mir-pass: CopyProp",
    ).map((p) => p.id),
  ).toEqual(["CopyProp"]);
  expect(classifyPasses(["tests/mir-opt/foo.rs"], "")[0]?.kind).toBe(
    "unclassified",
  );
});

it("keeps shared SSA and backend changes out of concrete pass categories", () => {
  const shared = classifyPasses(
    ["compiler/rustc_mir_transform/src/ssa.rs"],
    "",
  );
  expect(shared).toMatchObject([{ id: "shared-ssa", kind: "shared" }]);
  expect(
    classifyPasses(["compiler/rustc_codegen_llvm/src/builder.rs"], "")[0]?.kind,
  ).toBe("unclassified");
});

it("narrows a multi-pass file by changed hunk and flags ambiguity when no name is given", () => {
  const file = "compiler/rustc_mir_transform/src/simplify.rs";
  const precise = classifyPasses(
    [file],
    `diff --git a/${file} b/${file}\n@@ impl MirPass for SimplifyCfg {\n-old\n+new`,
  );
  expect(precise.map((p) => p.id)).toEqual(["SimplifyCfg"]);
  const ambiguous = classifyPasses([file], "");
  expect(ambiguous.map((p) => p.id)).toEqual(["SimplifyCfg", "SimplifyLocals"]);
  expect(ambiguous.every((p) => p.confidence === "medium")).toBe(true);
});

it("catalog contains actual registrations and consolidates enum variants", () => {
  const names = getPassCatalog().map((p) => p.name);
  expect(names).toContain("GVN");
  expect(names).toContain("AddCallGuards");
  expect(names).not.toContain("CriticalCallEdges");
  const catalog = catalogFromSnapshots([
    {
      source: "mod simplify: SimplifyCfg { Initial, Final }, SimplifyLocals;",
      url: "pinned source",
    },
  ]);
  expect(catalog.map((p) => p.name)).toEqual(["SimplifyCfg", "SimplifyLocals"]);
});

it("recognizes historical lint wrappers and the ConstPropLint regression", () => {
  const catalog = catalogFromSnapshots([
    {
      source:
        "mod const_prop_lint;\nfn passes() { let p = &Lint(const_prop_lint::ConstPropLint); }",
      url: "pinned",
    },
  ]);
  expect(catalog.map((p) => p.id)).toEqual(["ConstPropLint"]);
  expect(
    classifyPasses(
      ["compiler/rustc_mir_transform/src/const_prop_lint.rs"],
      "",
    ).map((p) => p.id),
  ).toContain("ConstPropLint");
});
