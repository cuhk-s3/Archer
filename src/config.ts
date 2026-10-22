import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const projectRoot = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "..",
);

export function loadEnvironment(
  path = resolve(projectRoot, "environments"),
): void {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    const match = line.match(
      /^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/,
    );
    if (!match) continue;
    const [, key, raw] = match;
    if (process.env[key!]) continue;
    let value = raw!;
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (
      !/^(ARCHER_LM_API_ENDPOINT|ARCHER_LM_API_KEY|LAB_GITHUB_TOKEN|ARCHER_MODEL|ARCHER_KNOWLEDGE_MODEL|ARCHER_HISTORY_GIT_REPO|ARCHER_HISTORY_GIT_INDEX|LAB_RUST_BUILD_DIR|LAB_RUST_BUILD_TIMEOUT|LAB_MIRI_TOOLCHAIN|ARCHER_OUTPUT_DIR|ARCHER_HOST|ARCHER_PORT|ARCHER_AGENT_TIMEOUT|RUSTUP)$/.test(
        key!,
      )
    )
      continue;
    process.env[key!] = value;
  }
}

export interface ArcherConfig {
  githubToken?: string;
  modelEndpoint: string;
  modelApiKey: string;
  model: string;
  buildRoot: string;
  outputDir: string;
  buildTimeoutMs: number;
  host: string;
  port: number;
  agentTimeoutMs: number;
}

export function getConfig(): ArcherConfig {
  loadEnvironment();
  const endpoint = process.env.ARCHER_LM_API_ENDPOINT;
  const apiKey = process.env.ARCHER_LM_API_KEY;
  if (!endpoint || !apiKey)
    throw new Error(
      "Set ARCHER_LM_API_ENDPOINT and ARCHER_LM_API_KEY in environments.",
    );
  return {
    ...(process.env.LAB_GITHUB_TOKEN
      ? { githubToken: process.env.LAB_GITHUB_TOKEN }
      : {}),
    modelEndpoint: endpoint,
    modelApiKey: apiKey,
    model: process.env.ARCHER_MODEL ?? "deepseek-flash",
    buildRoot: resolve(
      process.env.LAB_RUST_BUILD_DIR ?? resolve(projectRoot, "build/rust"),
    ),
    outputDir: resolve(
      process.env.ARCHER_OUTPUT_DIR ??
        resolve(projectRoot, "service_data/reviews"),
    ),
    buildTimeoutMs: Number(process.env.LAB_RUST_BUILD_TIMEOUT ?? 14_400) * 1000,
    host: process.env.ARCHER_HOST ?? "127.0.0.1",
    port: Number(process.env.ARCHER_PORT ?? 8080),
    agentTimeoutMs: Number(process.env.ARCHER_AGENT_TIMEOUT ?? 1200) * 1000,
  };
}

export function getKnowledgeConfig(): ArcherConfig {
  const config = getConfig();
  return {
    ...config,
    model: process.env.ARCHER_KNOWLEDGE_MODEL ?? "deepseek-flash",
  };
}
