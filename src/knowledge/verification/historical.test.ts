import { expect, it } from "vitest";
import { reproduced, type WitnessRun } from "./historical.js";
const oracle = { code: 0, stdout: "42\n", stderr: "" };
const cases = (): WitnessRun[] =>
  ["0", "3"].flatMap((level) =>
    ["base", "fixed"].flatMap((version) =>
      [0, 1].map(() => ({
        label: `${version}-O${level}`,
        compiled: true,
        result: {
          ...oracle,
          stdout: version === "base" && level === "3" ? "0\n" : oracle.stdout,
        },
      })),
    ),
  );
it("requires stable pre-fix wrong output and both fixed levels agreeing with two reference runs", () => {
  expect(reproduced([oracle, oracle], cases())).toBe(true);
  expect(
    reproduced(
      [oracle, oracle],
      cases().map((r) => ({ ...r, result: oracle })),
    ),
  ).toBe(false);
  expect(reproduced([oracle], cases())).toBe(false);
  expect(reproduced([oracle, { ...oracle, stdout: "43\n" }], cases())).toBe(
    false,
  );
  const wrongFixed = cases();
  wrongFixed[7]!.result.stdout = "0\n";
  expect(reproduced([oracle, oracle], wrongFixed)).toBe(false);
});
it("rejects timeouts, killed processes, incomplete compiles and unstable output", () => {
  for (const change of [
    { timedOut: true },
    { signal: "SIGKILL" },
    { code: -1 },
    { stdout: "unstable" },
  ]) {
    const runs = cases();
    Object.assign(runs[0]!.result, change);
    expect(reproduced([oracle, oracle], runs)).toBe(false);
  }
  const runs = cases();
  runs[0]!.compiled = false;
  expect(reproduced([oracle, oracle], runs)).toBe(false);
  expect(reproduced([{ ...oracle, code: 1 }, oracle], cases())).toBe(false);
});

it("records explicit pass-isolation flags and rejects malformed compiler options", async () => {
  const { rustTestFlags } = await import("../../review/tools.js");
  expect(
    rustTestFlags({
      mirOptLevel: 0,
      mirPasses: ["+RenameReturnPlace", "-CopyProp"],
    }),
  ).toEqual([
    "-Zmir-opt-level=0",
    "-Zmir-enable-passes=+RenameReturnPlace,-CopyProp",
  ]);
  expect(rustTestFlags()).toEqual([]);
  expect(() => rustTestFlags({ mirOptLevel: -1 })).toThrow(
    "Invalid MIR optimization level",
  );
  expect(() => rustTestFlags({ mirPasses: ["GVN;extra"] })).toThrow(
    "Invalid concrete MIR pass selector",
  );
});
