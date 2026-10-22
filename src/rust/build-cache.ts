import { createHash } from "node:crypto";
import { mkdir, readFile, rm, stat } from "node:fs/promises";
import { writeFileSync } from "node:fs";
import { hostname } from "node:os";
import { join } from "node:path";
import { atomicJson } from "../infra/artifacts.js";

export function buildCacheKey(identity: object): string {
  return createHash("sha256").update(JSON.stringify(identity)).digest("hex");
}

interface LockOwner {
  pid: number;
  host: string;
  token: string;
  processGroup?: number;
}
const alive = (pid: number) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
};
export interface BuildLease {
  onSpawn(pid: number): void;
}

/** Serialize writers across review processes, retaining interrupted output for resumption. */
export async function withBuildLock<T>(
  directory: string,
  timeoutMs: number,
  action: (lease: BuildLease) => Promise<T>,
): Promise<T> {
  await mkdir(directory, { recursive: true });
  const lock = join(directory, ".lock");
  const owner: LockOwner = {
    pid: process.pid,
    host: hostname(),
    token: crypto.randomUUID(),
  };
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      await mkdir(lock);
      writeFileSync(join(lock, "owner.json"), JSON.stringify(owner));
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      const reclaim = lock + ".reclaim";
      let reclaiming = false;
      try {
        await mkdir(reclaim);
        reclaiming = true;
        try {
          const previous = JSON.parse(
            await readFile(join(lock, "owner.json"), "utf8"),
          ) as LockOwner;
          // A crashed Node process may leave a live detached compiler group behind.
          if (
            previous.host === owner.host &&
            !alive(previous.pid) &&
            (!previous.processGroup || !alive(-previous.processGroup))
          ) {
            await rm(lock, { recursive: true, force: true });
          }
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code === "ENOENT") {
            // Allow a creator to finish writing its owner record.
            try {
              if (Date.now() - (await stat(lock)).mtimeMs > 60_000)
                await rm(lock, { recursive: true, force: true });
            } catch {}
          } else throw error;
        }
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      } finally {
        if (reclaiming) await rm(reclaim, { recursive: true, force: true });
      }
      if (Date.now() >= deadline)
        throw new Error(`Timed out waiting for build cache lock: ${directory}`);
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  try {
    return await action({
      onSpawn(pid) {
        owner.processGroup = pid;
        writeFileSync(join(lock, "owner.json"), JSON.stringify(owner));
      },
    });
  } finally {
    const current = JSON.parse(
      await readFile(join(lock, "owner.json"), "utf8"),
    ) as LockOwner;
    if (current.token === owner.token)
      await rm(lock, { recursive: true, force: true });
  }
}

/** Only a complete, validated receipt is reusable. Partial builds keep their incremental output. */
export async function cachedBuild(
  directory: string,
  key: string,
  timeoutMs: number,
  validate: () => Promise<void>,
  build: (lease: BuildLease) => Promise<void>,
): Promise<boolean> {
  return withBuildLock(directory, timeoutMs, async (lease) => {
    const receipt = join(directory, "complete.json");
    try {
      const saved = JSON.parse(await readFile(receipt, "utf8"));
      if (saved.key === key) {
        await validate();
        return true;
      }
    } catch {
      /* Missing, interrupted, or invalid outputs require a rebuild. */
    }
    await rm(receipt, { force: true });
    await build(lease);
    await validate();
    await atomicJson(receipt, {
      schema: 1,
      key,
      completedAt: new Date().toISOString(),
    });
    return false;
  });
}
