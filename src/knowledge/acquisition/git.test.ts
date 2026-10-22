import { expect, it } from "vitest";
import { parseHistoricalMerges } from "./git.js";
it("maps isolated Rust auto/rollup merges and preserves every path without GitHub's 3000-file cap", () => {
  const a = "a".repeat(40),
    b = "b".repeat(40),
    c = "c".repeat(40);
  const paths = Array.from({ length: 9930 }, (_, i) => `tests/ui/test-${i}.rs`);
  const text = `\x1e${a}\t${b} ${c}\t2024-02-01T00:00:00Z\tRollup merge of #120881 - user:branch\n\n${paths.join("\n")}\n\x1e${b}\t${c} ${a}\t2024-02-02T00:00:00Z\tUnrelated subtree merge (#12345)\n\ncompiler/fake.rs\n`;
  const merges = parseHistoricalMerges(text);
  expect(merges.size).toBe(1);
  expect(merges.get(120881)).toMatchObject({
    baseSha: b,
    headSha: c,
    mergeSha: a,
    files: paths,
  });
  expect(
    parseHistoricalMerges(
      `\x1e${a}\t${b}\t2024-02-01\tAuto merge of #7\nfile.rs\n`,
    ).size,
  ).toBe(0);
});
