import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";
import { run } from "./process.js";
it("streams complete build logs while bounding captured output", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-build-log-"));
  try {
    const logFile = join(root, "build.log");
    let outputs = 0;
    const result = await run(
      process.execPath,
      [
        "-e",
        'process.stdout.write("x".repeat(10000));process.stderr.write("done");',
      ],
      {
        logFile,
        maxOutputChars: 64,
        onOutput: () => {
          outputs++;
        },
      },
    );
    expect(result.stdout).toHaveLength(64);
    expect((await readFile(logFile, "utf8")).length).toBe(10004);
    expect(outputs).toBeGreaterThan(0);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
it("marks a killed build as timed out instead of a successful tool result", async () => {
  const result = await run(
    process.execPath,
    ["-e", "setTimeout(()=>{},10000)"],
    {
      timeoutMs: 100,
      check: false,
      processGroup: process.platform !== "win32",
    },
  );
  expect(result.timedOut).toBe(true);
  expect(result.code).not.toBe(0);
});
