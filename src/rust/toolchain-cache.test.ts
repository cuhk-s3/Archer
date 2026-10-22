import { expect, it, vi } from "vitest";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const mock = vi.hoisted(() => ({
  revisions: new Map<string, string>(),
  fetched: new Map<string, string>(),
  builds: [] as string[],
}));
vi.mock("../infra/process.js", () => ({
  run: vi.fn(async (_command: string, args: string[]) => ({
    code: args.includes("--is-ancestor") ? 1 : 0,
    stdout: "/fake/rustup",
    stderr: "",
  })),
  checked: vi.fn(
    async (command: string, args: string[], options: { cwd?: string } = {}) => {
      const cwd = options.cwd ?? "";
      if (command === "/fake/rustup") return "/fake/bin/rustc";
      if (command === "git") {
        if (args[0] === "clone") {
          await mkdir(join(args.at(-1)!, ".git"), { recursive: true });
          await writeFile(join(args.at(-1)!, "x.py"), "bootstrap");
          return "";
        }
        if (args[0] === "fetch") mock.fetched.set(cwd, args.at(-1)!);
        if (args[0] === "checkout")
          mock.revisions.set(cwd, mock.fetched.get(cwd)!);
        if (args[0] === "show") return "a".repeat(40) + " " + "c".repeat(40);
        if (args[0] === "write-tree") return "tree";
        if (args[0] === "rev-parse")
          return args[1] === "HEAD"
            ? mock.revisions.get(cwd)!
            : args[1] === ":src/llvm-project"
              ? "llvm-revision"
              : "bootstrap-tree";
        return "";
      }
      if (command === "./x.py") {
        const config = await readFile(args[1]!, "utf8");
        const output = JSON.parse(config.match(/^build-dir = (.+)$/m)![1]!);
        const target = args.at(-1)!;
        mock.builds.push(target);
        if (target === "src/llvm-project") {
          const executable = join(
            output,
            "aarch64-apple-darwin/llvm/bin/llvm-config",
          );
          await mkdir(dirname(executable), { recursive: true });
          await writeFile(executable, "llvm");
          await mkdir(join(dirname(dirname(executable)), "lib"), {
            recursive: true,
          });
          await writeFile(
            join(dirname(dirname(executable)), "lib/libLLVM.a"),
            "llvm library",
          );
        }
        if (target === "library") {
          const stage = join(output, "aarch64-apple-darwin/stage1");
          await mkdir(join(stage, "bin"), { recursive: true });
          await writeFile(join(stage, "bin/rustc"), "rustc");
          await mkdir(join(stage, "lib"), { recursive: true });
          await writeFile(join(stage, "lib/libstd-test.rlib"), "std");
        }
        return "";
      }
      if (command.endsWith("/llvm-config")) {
        await access(command);
        return args.includes("--libdir")
          ? join(dirname(dirname(command)), "lib")
          : args.includes("--libnames")
            ? "libLLVM.a"
            : "LLVM test";
      }
      if (command.endsWith("/stage1/bin/rustc")) {
        await access(command);
        return args.includes("--print")
          ? join(dirname(dirname(command)), "lib")
          : "host: aarch64-apple-darwin";
      }
      if (command === "rustc") return "host: aarch64-apple-darwin";
      return command + " test-version";
    },
  ),
}));
import { RustToolchain } from "./toolchain.js";
import type { RustPullRequest } from "../types.js";

it("keeps source checkouts per PR while reusing compiler and LLVM outputs across PRs", async () => {
  const root = await mkdtemp(join(tmpdir(), "archer-toolchain-cache-"));
  try {
    mock.builds.length = 0;
    const pr = { id: 1, headSha: "c".repeat(40) } as RustPullRequest;
    const first = await new RustToolchain(root, 5000).prepareHistorical(
      pr,
      "b".repeat(40),
    );
    expect(mock.builds).toEqual([
      "src/llvm-project",
      "compiler/rustc",
      "library",
      "compiler/rustc",
      "library",
    ]);
    const second = await new RustToolchain(root, 5000).prepareHistorical(
      { ...pr, id: 2 },
      "b".repeat(40),
    );
    expect(second.baseDir).not.toBe(first.baseDir);
    expect(second.patchedDir).not.toBe(first.patchedDir);
    expect(second.baselineRustc).toBe(first.baselineRustc);
    expect(second.patchedRustc).toBe(first.patchedRustc);
    expect(mock.builds).toHaveLength(5);
    await rm(first.patchedRustc);
    await new RustToolchain(root, 5000).prepareHistorical(
      { ...pr, id: 3 },
      "b".repeat(40),
    );
    expect(mock.builds.slice(5)).toEqual(["compiler/rustc", "library"]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
