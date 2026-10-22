import { createWriteStream } from "node:fs";
import { spawn } from "node:child_process";

export interface ProcessResult {
  code: number;
  stdout: string;
  stderr: string;
  timedOut?: boolean;
  signal?: string | null;
}

export function run(
  command: string,
  args: string[],
  options: {
    cwd?: string;
    timeoutMs?: number;
    env?: NodeJS.ProcessEnv;
    input?: string;
    check?: boolean;
    logFile?: string;
    maxOutputChars?: number;
    onOutput?: () => void;
    onSpawn?: (pid: number) => void;
    processGroup?: boolean;
  } = {},
): Promise<ProcessResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      detached: options.processGroup ?? false,
      env: { ...process.env, ...options.env },
      stdio: [options.input === undefined ? "ignore" : "pipe", "pipe", "pipe"],
    });
    child.on("spawn", () => {
      try {
        if (child.pid) options.onSpawn?.(child.pid);
      } catch (error) {
        if (timer) clearTimeout(timer);
        child.kill("SIGKILL");
        log?.end();
        reject(error);
      }
    });
    const log = options.logFile
      ? createWriteStream(options.logFile, { flags: "a", mode: 0o600 })
      : undefined;
    const tail = (s: string) =>
      options.maxOutputChars ? s.slice(-options.maxOutputChars) : s;
    log?.on("error", (error) => {
      child.kill("SIGKILL");
      reject(error);
    });
    let stdout = "";
    let stderr = "";
    child.stdout!.setEncoding("utf8").on("data", (s: string) => {
      stdout = tail(stdout + s);
      log?.write(s);
      options.onOutput?.();
    });
    child.stderr!.setEncoding("utf8").on("data", (s: string) => {
      stderr = tail(stderr + s);
      log?.write(s);
      options.onOutput?.();
    });
    if (options.input !== undefined) child.stdin!.end(options.input);
    let timedOut = false;
    const timer = options.timeoutMs
      ? setTimeout(() => {
          timedOut = true;
          if (options.processGroup && child.pid) {
            try {
              process.kill(-child.pid, "SIGKILL");
            } catch {
              child.kill("SIGKILL");
            }
          } else child.kill("SIGKILL");
        }, options.timeoutMs)
      : undefined;
    child.on("error", (error) => {
      if (timer) clearTimeout(timer);
      log?.end();
      reject(error);
    });
    child.on("close", async (code, signal) => {
      if (timer) clearTimeout(timer);
      if (log && !log.writableEnded)
        await new Promise<void>((done) => {
          log.end(done);
        });
      if ((code === 0 && !timedOut) || options.check === false)
        resolve({ code: code ?? -1, stdout, stderr, timedOut, signal });
      else
        reject(
          new Error(
            `${command} ${args.join(" ")} failed (${signal ?? code})\n${stdout}${stderr}`,
          ),
        );
    });
  });
}

export async function checked(
  command: string,
  args: string[],
  options: Parameters<typeof run>[2] = {},
): Promise<string> {
  const result = await run(command, args, options);
  return result.stdout;
}
