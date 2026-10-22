import { expect, it } from "vitest";
import {
  bootstrapEnvironment,
  historicalBootstrapConfig,
} from "./toolchain.js";
it("builds historical pinned LLVM locally and never downloads an unrelated compiler", () => {
  const config = historicalBootstrapConfig("aarch64-apple-darwin");
  expect(config).toContain("download-ci-llvm = false");
  expect(config).toContain("download-rustc = false");
  expect(config).toContain('targets = "AArch64"');
  expect(config).not.toMatch(/^jobs\s*=/m); // 2024 bootstrap accepts jobs only as a CLI option.
  expect(config).toContain('CMAKE_POLICY_VERSION_MINIMUM = "3.5"');
  expect(config).not.toContain("llvm-config =");
});
it("uses a previously built pinned LLVM only when explicitly provided", () => {
  const config = historicalBootstrapConfig(
    "x86_64-unknown-linux-gnu",
    "/workspace with spaces/llvm/bin/llvm-config",
  );
  expect(config).toContain('targets = "X86"');
  expect(config).toContain("[target.x86_64-unknown-linux-gnu]");
  expect(config).toContain(
    'llvm-config = "/workspace with spaces/llvm/bin/llvm-config"',
  );
  expect(config).toContain("llvm-has-rust-patches = true");
  expect(() => historicalBootstrapConfig("unsupported-host")).toThrow(
    "No historical LLVM target",
  );
});

it("selects a matching Command Line Tools compiler and SDK only inside the build process", () => {
  const previous = process.env.DEVELOPER_DIR;
  const root = "/Library/Developer/CommandLineTools";
  const env = bootstrapEnvironment("/rust/bin", "/usr/bin", root);
  expect(env.DEVELOPER_DIR).toBe(root);
  expect(env.SDKROOT).toBe(root + "/SDKs/MacOSX.sdk");
  expect(env.PATH).toContain(root + "/usr/bin");
  expect(process.env.DEVELOPER_DIR).toBe(previous);
  expect(
    bootstrapEnvironment("/rust/bin", "/usr/bin").DEVELOPER_DIR,
  ).toBeUndefined();
});
