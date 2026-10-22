import { expect, it } from "vitest";
import { mirDiffViews } from "./material.js";
it("separates outer Git edits from inner before/after MIR expectations", () => {
  const patch = `diff --git a/tests/a.Old.diff b/tests/a.New.diff
--- a/tests/a.Old.diff
+++ b/tests/a.New.diff
@@ -1,5 +1,5 @@
-- // MIR for wrong before Old
-+ // MIR for wrong after Old
+- // MIR for wrong before New
++ // MIR for wrong after New
  fn wrong() {
 - _0 = _2;
-- _2 = const 'b';
-+ _0 = const 'b';
+- _2 = const 'b';
++ _1 = const 'b';
  }
`;
  const [v] = mirDiffViews(patch);
  expect(v!.oldAfter).toContain("_0 = const 'b'");
  expect(v!.newAfter).toContain("_1 = const 'b'");
  expect(v!.newAfter).not.toContain("_0 = const 'b'");
  expect(v!.oldBefore).toContain("_2 = const 'b'");
});
