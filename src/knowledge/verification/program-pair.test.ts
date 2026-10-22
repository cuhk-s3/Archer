import { digest } from "../../infra/artifacts.js";
import { expect, it } from "vitest";
import {
  pairSources,
  pairCounterexample,
  sourceQuotations,
  validPair,
  type PairObservation,
  type VerifiedPair,
} from "./program-pair.js";

import { checkSynthesis } from "../synthesis.js";
const pair = {
  commonSource: "",
  originalFunction: "fn case(x: u8) -> u8 { x }",
  transformedFunction: "fn case(x: u8) -> u8 { x.wrapping_add(1) }",
  harness: 'fn main() { println!("{}", case(1)); }',
  inputs: "1",
  explanation: "fixture",
};
const result = (stdout: string) => ({ code: 0, stdout, stderr: "" });
const oracles = (): PairObservation[] =>
  ["original", "transformed"].flatMap((label) =>
    [0, 1].map(() => ({
      label,
      result: result(label === "original" ? "1" : "2"),
    })),
  );
const runs = (): PairObservation[] =>
  ["original", "transformed"].flatMap((label) =>
    ["0", "3"].flatMap((level) =>
      [0, 1].map(() => ({
        label: `${label}-O${level}`,
        result: result(label === "original" ? "1" : "2"),
      })),
    ),
  );
it("requires a shared function signature and a single identical harness", () => {
  expect(pairSources(pair)[0]).toContain(pair.harness);
  expect(pairSources(pair)[1]).toContain(pair.harness);
  expect(() =>
    pairSources({
      ...pair,
      transformedFunction: "fn case(_x: u8) -> u8 { 2 }",
    }),
  ).not.toThrow();
  expect(() =>
    pairSources({
      ...pair,
      originalFunction: pair.originalFunction.replace("case", "check"),
      transformedFunction: pair.transformedFunction.replace("case", "check"),
      harness: pair.harness.replace("case", "check"),
    }),
  ).not.toThrow();
  expect(() =>
    pairSources({ ...pair, transformedFunction: "fn case(x: u16) -> u16 {x}" }),
  ).toThrow("same fn case signature");
  expect(() =>
    pairSources({ ...pair, commonSource: "fn case(x:u8)->u8{x}" }),
  ).toThrow("shared main harness");
});
it("accepts stable concrete differences only when every native execution matches its own Miri reference", () => {
  expect(pairCounterexample(oracles(), runs())).toBe(true);
  const same = runs().map((r) => ({ ...r, result: result("1") }));
  expect(pairCounterexample(oracles(), same)).toBe(false);
  const bad = runs();
  bad[0]!.result.stdout = "2";
  expect(pairCounterexample(oracles(), bad)).toBe(false);
  expect(pairCounterexample(oracles().slice(1), runs())).toBe(false);
  const unstable = oracles();
  unstable[0]!.result.stdout = "random";
  expect(pairCounterexample(unstable, runs())).toBe(false);
  const failed = runs();
  failed[0]!.result.code = -1;
  expect(pairCounterexample(oracles(), failed)).toBe(false);
});
const verified = (): VerifiedPair => {
  const analysis = {
    model: "deepseek-flash",
    prId: 1,
    headSha: "a".repeat(40),
    passIds: ["GVN"],
    evidence: ["historical source quotation"],
  } as any;
  return {
    analysis,
    certificate: {
      schema: 2,
      scope: "historical-transformation-program-pair",
      status: "validated-counterexample",
      model: "deepseek-flash",
      analysisHash: digest(analysis),
      pairHash: digest(pair),
      pair,
      runtime: {
        toolchain: "nightly",
        rustc: "fixture",
        rustcVersion: "fixture",
        miriVersion: "fixture",
      },
      passIds: ["GVN"],
      evidence: analysis.evidence,
      oracles: oracles(),
      runs: runs(),
      validatedAt: "fixture",
    },
  };
};
it("binds certificates to frozen analysis, programs, model and pass", () => {
  const v = verified();
  expect(validPair(v)).toBe(true);
  v.analysis.trigger = "edited";
  expect(validPair(v)).toBe(false);
  const other = verified();
  other.certificate.passIds = ["CopyProp"];
  expect(validPair(other)).toBe(false);
});
it("requires C to summarize every retained case with source evidence", () => {
  const v = verified(),
    id = `1-${v.analysis.headSha}`;
  const p = {
    title: "fixture",
    description: "fixture",
    preconditions: [],
    pitfalls: [],
    testStrategy: "fixture",
    caseIds: [id],
    evidence: ["historical source quotation"],
  };
  expect(() => checkSynthesis({ patterns: [p] }, [v], "GVN")).not.toThrow();
  expect(() => checkSynthesis({ patterns: [] }, [v], "GVN")).toThrow(
    "included",
  );
  expect(() =>
    checkSynthesis(
      { patterns: [{ ...p, evidence: ["invented historical quotation"] }] },
      [v],
      "GVN",
    ),
  ).toThrow("Summary evidence");
});

it("retains only verifiable source quotations while accepting normal citation wrappers", () => {
  const actual = "This is a historical source quotation.";
  expect(
    sourceQuotations(
      ["file.rs:12: `" + actual + "`", "invented quote"],
      [actual],
    ),
  ).toEqual([actual]);
  expect(() => sourceQuotations(["invented quote"], [actual])).toThrow(
    "No exact historical quotation",
  );
});
