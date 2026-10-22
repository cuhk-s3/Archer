import { expect, it } from "vitest";
import { checkScreening } from "./screening.js";
it("requires complete independent accounting and per-PR source evidence for batch screening", () => {
  const inputs = [
    {
      name: "1.json",
      raw: {
        pr: {
          id: 1,
          title: "Frontend diagnostic change",
          body: "",
          patch: "",
          files: [],
        } as any,
        issues: [],
      },
    },
  ];
  expect(() =>
    checkScreening(
      [
        {
          prId: 1,
          verdict: "excluded",
          reason: "frontend",
          evidence: ["Frontend diagnostic change"],
        },
      ],
      inputs,
    ),
  ).not.toThrow();
  expect(() => checkScreening([], inputs)).toThrow("every supplied PR");
  expect(() =>
    checkScreening(
      [{ prId: 2, verdict: "pending", reason: "uncertain", evidence: [] }],
      inputs,
    ),
  ).toThrow("unprovided");
  expect(() =>
    checkScreening(
      [
        {
          prId: 1,
          verdict: "excluded",
          reason: "no matching pass",
          evidence: ["invented evidence"],
        },
      ],
      inputs,
    ),
  ).toThrow("exact evidence");
  expect(() =>
    checkScreening(
      [
        {
          prId: 1,
          verdict: "pending",
          reason: "source inspection required",
          evidence: [],
        },
      ],
      inputs,
    ),
  ).not.toThrow();
});
