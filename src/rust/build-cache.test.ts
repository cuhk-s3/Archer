import { expect, it } from "vitest";
import { mkdtemp, readFile, rm, writeFile, mkdir } from "node:fs/promises";
import { tmpdir, hostname } from "node:os";
import { join } from "node:path";
import { buildCacheKey, cachedBuild, withBuildLock } from "./build-cache.js";

it("reuses an identical compiler across callers, serializes writers, and repairs missing outputs", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-cache-test-"));
  try {
    let builds = 0;
    const validate = async () => {
      expect(await readFile(join(root, "rustc"), "utf8")).toBe("ready");
    };
    const build = async () => {
      builds++;
      await new Promise((resolve) => setTimeout(resolve, 20));
      await writeFile(join(root, "rustc"), "ready");
    };
    const results = await Promise.all([
      cachedBuild(root, "same-revision", 5000, validate, build),
      cachedBuild(root, "same-revision", 5000, validate, build),
    ]);
    expect(results.sort()).toEqual([false, true]);
    expect(builds).toBe(1);
    await rm(join(root, "rustc"));
    expect(
      await cachedBuild(root, "same-revision", 5000, validate, build),
    ).toBe(false);
    expect(builds).toBe(2);
    expect(
      await cachedBuild(root, "changed-config", 5000, validate, build),
    ).toBe(false);
    expect(builds).toBe(3);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

it("never publishes failed builds and resumes their incremental output", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-cache-test-"));
  try {
    await expect(
      cachedBuild(
        root,
        "revision",
        5000,
        async () => {},
        async () => {
          await writeFile(join(root, "partial"), "incremental");
          throw new Error("interrupted");
        },
      ),
    ).rejects.toThrow("interrupted");
    await expect(readFile(join(root, "complete.json"))).rejects.toThrow();
    expect(
      await cachedBuild(
        root,
        "revision",
        5000,
        async () => {},
        async () => {
          expect(await readFile(join(root, "partial"), "utf8")).toBe(
            "incremental",
          );
        },
      ),
    ).toBe(false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

it("recovers a dead owner lock but does not steal a live compiler process group", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-cache-test-"));
  try {
    await mkdir(join(root, ".lock"));
    const dead = { pid: 2147483647, host: hostname(), token: "old" };
    await writeFile(join(root, ".lock/owner.json"), JSON.stringify(dead));
    expect(await withBuildLock(root, 5000, async () => "recovered")).toBe(
      "recovered",
    );
    await mkdir(join(root, ".lock"));
    // processGroup is negative here so alive(-processGroup) probes the real live PID.
    await writeFile(
      join(root, ".lock/owner.json"),
      JSON.stringify({ ...dead, processGroup: -process.pid }),
    );
    await expect(withBuildLock(root, 10, async () => "stolen")).rejects.toThrow(
      "Timed out",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

it("invalidates cache keys on compiler source, tool or configuration changes", () => {
  const identity = {
    revision: "a",
    patch: "",
    host: "aarch64",
    config: "release",
    tools: ["clang1"],
  };
  const key = buildCacheKey(identity);
  expect(buildCacheKey({ ...identity })).toBe(key);
  for (const change of [
    { revision: "b" },
    { patch: "fix" },
    { host: "x86_64" },
    { config: "debug" },
    { tools: ["clang2"] },
  ]) {
    expect(buildCacheKey({ ...identity, ...change })).not.toBe(key);
  }
});
