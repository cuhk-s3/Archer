import { mkdir, access, writeFile, readFile, readdir } from "node:fs/promises";
import { availableParallelism } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { checked, run } from "../infra/process.js";
import {
  buildCacheKey,
  cachedBuild,
  withBuildLock,
  type BuildLease,
} from "./build-cache.js";
import type { RustPullRequest } from "../types.js";

export interface BuiltRustPr {
  baseDir: string;
  patchedDir: string;
  baselineRustc: string;
  patchedRustc: string;
}

export interface RustBuildProgress {
  status: "building" | "complete" | "failed";
  revision: string;
  phase: string;
  sourceDir: string;
  logFile: string;
  updatedAt: string;
  lastOutputAt: string;
}

export function historicalBootstrapConfig(
  host: string,
  llvmConfig?: string,
): string {
  const target = host.startsWith("aarch64-")
    ? "AArch64"
    : host.startsWith("x86_64-")
      ? "X86"
      : undefined;
  if (!target)
    throw new Error(`No historical LLVM target configured for ${host}`);
  return `[llvm]
download-ci-llvm = false
targets = "${target}"
experimental-targets = ""
assertions = false
ninja = true
build-config = { CMAKE_POLICY_VERSION_MINIMUM = "3.5" }

[build]
docs = false

[rust]
download-rustc = false
optimize = 1
debuginfo-level = 0
debug-assertions = false
incremental = true
${llvmConfig ? `\n[target.${host}]\nllvm-config = ${JSON.stringify(llvmConfig)}\nllvm-has-rust-patches = true\n` : ""}`;
}

/** Select installed CLT per process; never change xcode-select or accept licenses. */
export function bootstrapEnvironment(
  bin: string,
  inheritedPath: string,
  commandLineTools?: string,
): NodeJS.ProcessEnv {
  return {
    PATH: [
      bin,
      ...(commandLineTools ? [join(commandLineTools, "usr/bin")] : []),
      inheritedPath,
    ]
      .filter(Boolean)
      .join(delimiter),
    ...(commandLineTools
      ? {
          DEVELOPER_DIR: commandLineTools,
          SDKROOT: join(commandLineTools, "SDKs/MacOSX.sdk"),
        }
      : {}),
  };
}

export async function nativeBuildEnvironment(
  bin = "",
): Promise<NodeJS.ProcessEnv> {
  let tools: string | undefined;
  if (process.platform === "darwin") {
    const root = "/Library/Developer/CommandLineTools";
    try {
      await access(join(root, "usr/bin/clang++"));
      await access(join(root, "SDKs/MacOSX.sdk"));
      tools = root;
    } catch {
      /* Preserve configured tools when CLT is absent. */
    }
  }
  return bootstrapEnvironment(bin, process.env.PATH ?? "", tools);
}

export class RustToolchain {
  constructor(
    private readonly root: string,
    private readonly timeoutMs: number,
    private readonly onProgress?: (
      progress: RustBuildProgress,
    ) => Promise<void>,
  ) {}

  private repoDir(pr: RustPullRequest, revision: string): string {
    return join(this.root, "source", String(pr.id), revision.slice(0, 12));
  }

  private async checkout(
    path: string,
    commit: string,
    patch?: string,
    lease?: BuildLease,
  ): Promise<void> {
    const env = await nativeBuildEnvironment();
    const execution = {
      env,
      processGroup: true,
      ...(lease ? { onSpawn: lease.onSpawn } : {}),
    };
    await mkdir(dirname(path), { recursive: true });
    try {
      await access(join(path, ".git"));
    } catch {
      await checked(
        "git",
        [
          "clone",
          "--filter=blob:none",
          "https://github.com/rust-lang/rust.git",
          path,
        ],
        { ...execution, timeoutMs: this.timeoutMs },
      );
    }
    await checked("git", ["reset", "--hard"], { cwd: path, ...execution });
    await checked("git", ["clean", "-fdx", "-e", "/build/"], {
      cwd: path,
      ...execution,
    });
    await checked("git", ["fetch", "origin", commit], {
      cwd: path,
      ...execution,
      timeoutMs: this.timeoutMs,
    });
    await checked("git", ["checkout", "--detach", "FETCH_HEAD"], {
      cwd: path,
      ...execution,
    });
    if (patch)
      await checked("git", ["apply", "--3way", "-"], {
        cwd: path,
        ...execution,
        input: patch,
      });
  }

  private async nightlyPath(): Promise<string> {
    const rustup =
      process.env.RUSTUP ?? (await run("which", ["rustup"])).stdout.trim();
    const result = await checked(rustup, [
      "which",
      "rustc",
      "--toolchain",
      process.env.LAB_MIRI_TOOLCHAIN ?? "nightly",
    ]);
    return dirname(result.trim());
  }

  private async build(path: string, sourceLease: BuildLease): Promise<string> {
    const bin = await this.nightlyPath();
    const env = await nativeBuildEnvironment(bin);
    const host = (await checked("rustc", ["-vV"], { cwd: path, env })).match(
      /^host: (.+)$/m,
    )?.[1];
    if (!host) throw new Error("Could not determine Rust host triple");
    const revision = (
      await checked("git", ["rev-parse", "HEAD"], { cwd: path, env })
    ).trim();
    const patch = await checked("git", ["diff", "HEAD", "--binary"], {
      cwd: path,
      env,
    });
    const llvmRevision = (
      await checked("git", ["rev-parse", ":src/llvm-project"], {
        cwd: path,
        env,
      })
    ).trim();
    const tree = (
      await checked("git", ["write-tree"], { cwd: path, env })
    ).trim();
    const bootstrapTree = (
      await checked("git", ["rev-parse", `${tree}:src/bootstrap`], {
        cwd: path,
        env,
      })
    ).trim();
    const tools = await Promise.all([
      checked("clang++", ["--version"], { env }),
      checked("cmake", ["--version"], { env }),
      checked("ninja", ["--version"], { env }),
      checked("rustc", ["-vV"], { env }),
      ...(process.platform === "darwin"
        ? [checked("xcrun", ["--show-sdk-version"], { env })]
        : []),
    ]);
    const buildEnvironment = Object.fromEntries(
      [
        "CC",
        "CXX",
        "AR",
        "CFLAGS",
        "CXXFLAGS",
        "LDFLAGS",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "CMAKE_PREFIX_PATH",
        "SDKROOT",
        "DEVELOPER_DIR",
        "MACOSX_DEPLOYMENT_TARGET",
        "LIBRARY_PATH",
        "CPATH",
      ].map((name) => [name, env[name] ?? process.env[name] ?? ""]),
    );
    const cacheRoot = join(this.root, "cache");
    const baseConfig = historicalBootstrapConfig(host);
    // Bootstrap's LLVM recipe matters too: the same LLVM revision can be built differently.
    const llvmKey = buildCacheKey({
      schema: 1,
      llvmRevision,
      bootstrapTree,
      host,
      config: baseConfig,
      tools,
      buildEnvironment,
    });
    const llvmDir = join(cacheRoot, "llvm", llvmKey);
    const llvmOut = join(llvmDir, "build");
    const llvmConfig = join(llvmOut, host, "llvm", "bin", "llvm-config");
    const compilerConfig = historicalBootstrapConfig(host, llvmConfig);
    const rustKey = buildCacheKey({
      schema: 1,
      revision,
      patch,
      host,
      config: compilerConfig,
      tools,
      buildEnvironment,
    });
    const rustDir = join(cacheRoot, "rustc", rustKey);
    const rustOut = join(rustDir, "build");
    const rustc = join(rustOut, host, "stage1", "bin", "rustc");
    const statusDir = join(this.root, "build-status");
    await mkdir(statusDir, { recursive: true });
    const logFile = join(statusDir, `${revision}-${rustKey.slice(0, 12)}.log`);
    let phase = "cache";
    let lastOutputAt = new Date().toISOString();
    const progress = async (status: RustBuildProgress["status"]) => {
      const item = {
        status,
        revision,
        phase,
        sourceDir: path,
        logFile,
        updatedAt: new Date().toISOString(),
        lastOutputAt,
      };
      await writeFile(
        join(statusDir, `${revision}.json`),
        JSON.stringify(item, null, 2) + "\n",
      );
      await this.onProgress?.(item);
    };
    const validateRust = async () => {
      await checked(rustc, ["-vV"], { env });
      const libdir = (
        await checked(rustc, ["--print", "target-libdir"], { env })
      ).trim();
      if (
        !(await readdir(libdir)).some((name) => /^libstd-.*\.rlib$/.test(name))
      )
        throw new Error("Cached compiler is missing its standard library");
    };
    const bootstrap = async (
      source: string,
      output: string,
      config: string,
      targets: string[],
      lease: BuildLease,
    ) => {
      await mkdir(output, { recursive: true });
      const configFile = join(output, "archer-bootstrap.toml");
      // Keep build-dir in the existing [build] section for old and new bootstraps.
      await writeFile(
        configFile,
        config.replace(
          "[build]\n",
          `[build]\nbuild-dir = ${JSON.stringify(output)}\n`,
        ),
      );
      for (const target of targets) {
        phase = target;
        await progress("building");
        await checked(
          "./x.py",
          [
            "--config",
            configFile,
            "build",
            "--stage",
            "1",
            "-j",
            String(Math.max(1, Math.min(6, availableParallelism()))),
            target,
          ],
          {
            cwd: source,
            env,
            timeoutMs: this.timeoutMs,
            logFile,
            maxOutputChars: 24_000,
            onOutput: () => {
              lastOutputAt = new Date().toISOString();
            },
            onSpawn: (pid) => {
              sourceLease.onSpawn(pid);
              lease.onSpawn(pid);
            },
            processGroup: true,
          },
        );
      }
    };
    await progress("building");
    console.log(`Rust cache ${rustKey.slice(0, 12)}; live log: ${logFile}`);
    const timer = setInterval(() => {
      void progress("building").catch(() => {});
    }, 15_000);
    try {
      const reused = await cachedBuild(
        rustDir,
        rustKey,
        this.timeoutMs,
        validateRust,
        async (rustLease) => {
          const llvmReused = await cachedBuild(
            llvmDir,
            llvmKey,
            this.timeoutMs,
            async () => {
              await checked(llvmConfig, ["--version"], { env });
              const libdir = (
                await checked(llvmConfig, ["--libdir"], { env })
              ).trim();
              const libraries = (
                await checked(llvmConfig, ["--libnames"], { env })
              )
                .trim()
                .split(/\s+/);
              if (!libraries[0])
                throw new Error("Cached LLVM is missing its libraries");
              await Promise.all(
                libraries.map((name) => access(join(libdir, name))),
              );
            },
            async (llvmLease) => {
              // CMake embeds source paths. An interrupted LLVM build resumes against its original source tree.
              const producerFile = join(llvmDir, "producer.json");
              let source = path;
              try {
                source = JSON.parse(
                  await readFile(producerFile, "utf8"),
                ).source;
              } catch {
                await writeFile(
                  producerFile,
                  JSON.stringify({ source, llvmRevision, bootstrapTree }),
                );
              }
              await access(join(source, "x.py"));
              const checkedOutLlvm = (
                await checked(
                  "git",
                  ["-C", join(source, "src/llvm-project"), "rev-parse", "HEAD"],
                  { env },
                )
              ).trim();
              if (checkedOutLlvm !== llvmRevision) {
                await checked(
                  "git",
                  [
                    "-C",
                    join(source, "src/llvm-project"),
                    "fetch",
                    "origin",
                    llvmRevision,
                  ],
                  { env, timeoutMs: this.timeoutMs },
                );
                await checked(
                  "git",
                  [
                    "-C",
                    join(source, "src/llvm-project"),
                    "checkout",
                    "--detach",
                    llvmRevision,
                  ],
                  { env },
                );
              }
              // Both leases track the compiler group while nested LLVM construction is active.
              await bootstrap(
                source,
                llvmOut,
                baseConfig,
                ["src/llvm-project"],
                {
                  onSpawn(pid) {
                    rustLease.onSpawn(pid);
                    llvmLease.onSpawn(pid);
                  },
                },
              );
            },
          );
          console.log(
            `LLVM cache ${llvmKey.slice(0, 12)}: ${llvmReused ? "hit" : "built"}`,
          );
          await bootstrap(
            path,
            rustOut,
            compilerConfig,
            ["compiler/rustc", "library"],
            rustLease,
          );
        },
      );
      phase = reused ? "cache-hit" : "complete";
      console.log(
        `Rust compiler cache: ${reused ? "hit" : "built"} (${revision.slice(0, 12)})`,
      );
      await progress("complete");
      return rustc;
    } catch (error) {
      await progress("failed");
      throw new Error(`Historical build log: ${logFile}\n${String(error)}`);
    } finally {
      clearInterval(timer);
    }
  }

  // Use the actual merge commit and its first parent, not a PR's moving base.
  async prepareHistorical(
    pr: RustPullRequest,
    mergeSha: string,
  ): Promise<BuiltRustPr> {
    return withBuildLock(
      join(this.root, "source-locks", String(pr.id)),
      this.timeoutMs,
      (lease) => this.prepareHistoricalUnlocked(pr, mergeSha, lease),
    );
  }

  private async prepareHistoricalUnlocked(
    pr: RustPullRequest,
    mergeSha: string,
    lease: BuildLease,
  ): Promise<BuiltRustPr> {
    const env = await nativeBuildEnvironment();
    if (!/^[a-f0-9]{40}$/.test(mergeSha))
      throw new Error("Invalid merge revision");
    const patchedDir = this.repoDir(pr, mergeSha);
    await this.checkout(patchedDir, mergeSha, undefined, lease);
    const parents = (
      await checked("git", ["show", "-s", "--format=%P", mergeSha], {
        cwd: patchedDir,
        env,
      })
    )
      .trim()
      .split(/\s+/);
    if (parents.length !== 2 || parents[1] !== pr.headSha)
      throw new Error(
        "Historical validation requires an isolated two-parent PR merge; batch/squash merges need separate reconstruction",
      );
    await checked(
      "git",
      ["merge-base", "--is-ancestor", pr.headSha, mergeSha],
      { cwd: patchedDir, env },
    );
    const parent = parents[0]!;
    await run("git", ["merge-base", "--is-ancestor", pr.headSha, parent], {
      cwd: patchedDir,
      env,
      check: false,
    }).then((result) => {
      if (result.code !== 1)
        throw new Error(
          "Historical baseline already includes the PR or ancestry is unavailable",
        );
    });
    const baseDir = this.repoDir(pr, parent);
    await this.checkout(baseDir, parent, undefined, lease);
    const baselineRustc = await this.build(baseDir, lease);
    const patchedRustc = await this.build(patchedDir, lease);
    return {
      baseDir: resolve(baseDir),
      patchedDir: resolve(patchedDir),
      baselineRustc,
      patchedRustc,
    };
  }

  async prepare(pr: RustPullRequest): Promise<BuiltRustPr> {
    return withBuildLock(
      join(this.root, "source-locks", String(pr.id)),
      this.timeoutMs,
      (lease) => this.prepareUnlocked(pr, lease),
    );
  }

  private async prepareUnlocked(
    pr: RustPullRequest,
    lease: BuildLease,
  ): Promise<BuiltRustPr> {
    const baseDir = this.repoDir(pr, pr.baseSha);
    const patchedDir = join(
      this.root,
      "source",
      String(pr.id),
      `${pr.baseSha.slice(0, 12)}-${pr.headSha.slice(0, 12)}`,
    );
    await this.checkout(baseDir, pr.baseSha, undefined, lease);
    await this.checkout(patchedDir, pr.baseSha, pr.patch, lease);
    const baselineRustc = await this.build(baseDir, lease);
    const patchedRustc = await this.build(patchedDir, lease);
    return {
      baseDir: resolve(baseDir),
      patchedDir: resolve(patchedDir),
      baselineRustc,
      patchedRustc,
    };
  }
}
