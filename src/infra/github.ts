import type { RustPullRequest } from "../types.js";
import { classifyPasses } from "../rust/passes.js";

const API = "https://api.github.com/repos/rust-lang/rust";

/** Honor GitHub's reset window instead of losing a long historical collection. */
export async function githubRequest(
  url: string,
  headers: Record<string, string>,
): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    let response: Response;
    try {
      response = await fetch(url, {
        headers,
        signal: AbortSignal.timeout(60_000),
      });
    } catch (error) {
      if (attempt >= 3) throw error;
      await new Promise((resolve) => setTimeout(resolve, 1000 * 2 ** attempt));
      continue;
    }
    const limited =
      response.status === 429 ||
      (response.status === 403 &&
        (response.headers.get("x-ratelimit-remaining") === "0" ||
          response.headers.has("retry-after")));
    if (limited) {
      const reset =
        Number(response.headers.get("x-ratelimit-reset") ?? 0) * 1000;
      const retry = Number(response.headers.get("retry-after") ?? 0) * 1000;
      const delay = Math.max(retry, reset - Date.now() + 1000, 60_000);
      console.log(
        `GitHub rate limited; resuming in ${Math.ceil(delay / 1000)}s`,
      );
      await response.body?.cancel();
      await new Promise((resolve) => setTimeout(resolve, delay));
      continue;
    }
    if (response.status >= 500 && attempt < 3) {
      await response.body?.cancel();
      await new Promise((resolve) => setTimeout(resolve, 1000 * 2 ** attempt));
      continue;
    }
    return response;
  }
}

export async function fetchRustPr(
  id: number,
  token = process.env.LAB_GITHUB_TOKEN,
): Promise<RustPullRequest> {
  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await githubRequest(`${API}/pulls/${id}`, headers);
  if (!response.ok)
    throw new Error(
      `GitHub PR lookup failed (${response.status}): ${await response.text()}`,
    );
  const pr = (await response.json()) as any;
  const files: string[] = [];
  for (let page = 1; ; page++) {
    const fileResponse = await githubRequest(
      `${API}/pulls/${id}/files?per_page=100&page=${page}`,
      headers,
    );
    if (!fileResponse.ok)
      throw new Error(
        `GitHub PR files lookup failed (${fileResponse.status}): ${await fileResponse.text()}`,
      );
    const batch = (await fileResponse.json()) as Array<{ filename: string }>;
    files.push(...batch.map((file) => file.filename));
    if (batch.length < 100) break;
  }
  if (typeof pr.changed_files === "number" && files.length !== pr.changed_files)
    throw new Error(
      `Incomplete PR file list: received ${files.length}/${pr.changed_files}; do not classify a partial patch`,
    );
  const patchResponse = await githubRequest(pr.patch_url as string, headers);
  if (!patchResponse.ok)
    throw new Error(`GitHub PR patch lookup failed (${patchResponse.status})`);
  const components = new Set<string>();
  for (const file of files) {
    const parts = file.split("/");
    if (["compiler", "library"].includes(parts[0] ?? "") && parts.length > 2)
      components.add(parts[1]!);
    else if (parts[0] === "src" && parts[1] === "tools" && parts.length > 3)
      components.add(parts[2]!);
    else if (file.startsWith("src/librustc_mir/transform/"))
      components.add("rustc_mir_transform");
    else if (/^src\/librustc_(codegen|trans)/.test(file))
      components.add("rustc_codegen_ssa");
    else if (
      /^src\/librustc_(mir|middle)/.test(file) ||
      file.startsWith("src/librustc/mir/")
    )
      components.add("rustc_middle");
    else if (file.startsWith("src/libsyntax/")) components.add("rustc_ast");
    else if (file.startsWith("src/librustc/") || file.startsWith("src/comp/"))
      components.add("rustc_middle");
    else if (parts[0] === "src" && parts[1]?.startsWith("librustc_"))
      components.add(parts[1].replace(/^lib/, ""));
  }
  const patch = await patchResponse.text();
  return {
    id,
    url: pr.html_url,
    title: pr.title,
    body: pr.body ?? "",
    author: pr.user.login,
    state: pr.state,
    baseSha: pr.base.sha,
    headSha: pr.head.sha,
    ...(pr.merged_at && pr.merge_commit_sha
      ? { mergeSha: pr.merge_commit_sha }
      : {}),
    patch,
    files,
    components: [...components].sort(),
    createdAt: pr.created_at,
    passes: classifyPasses(files, patch),
  };
}
