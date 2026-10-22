import {
  appendFile,
  mkdir,
  readdir,
  readFile,
  writeFile,
} from "node:fs/promises";
import { join } from "node:path";
import type { KnowledgeRecord, ReviewRecord } from "../types.js";

export class ReviewStore {
  constructor(private readonly root: string) {}

  async save(
    record: ReviewRecord,
  ): Promise<{ reviewPath: string; knowledgePath: string }> {
    const reviewDir = join(this.root, "reviews", String(record.pr.id));
    await mkdir(reviewDir, { recursive: true });
    const base = `${record.pr.headSha.slice(0, 12)}-${record.id}`;
    const reviewPath = join(reviewDir, `${base}.json`);
    await writeFile(reviewPath, JSON.stringify(record, null, 2) + "\n", {
      mode: 0o600,
    });
    const knowledgePath = join(this.root, "knowledge", "rust.jsonl");
    if (record.knowledge.length) {
      await mkdir(join(this.root, "knowledge"), { recursive: true });
      const rows =
        record.knowledge
          .map((item: KnowledgeRecord) => JSON.stringify(item))
          .join("\n") + "\n";
      await appendFile(knowledgePath, rows, { mode: 0o600 });
    }
    await writeFile(join(reviewDir, `${base}.md`), renderMarkdown(record), {
      mode: 0o600,
    });
    return { reviewPath, knowledgePath };
  }

  async list(): Promise<ReviewRecord[]> {
    const root = join(this.root, "reviews");
    let prDirs: string[];
    try {
      prDirs = await readdir(root);
    } catch {
      return [];
    }
    const records: ReviewRecord[] = [];
    for (const prDir of prDirs) {
      let files: string[];
      try {
        files = await readdir(join(root, prDir));
      } catch {
        continue;
      }
      for (const file of files.filter((name) => name.endsWith(".json"))) {
        try {
          records.push(
            JSON.parse(
              await readFile(join(root, prDir, file), "utf8"),
            ) as ReviewRecord,
          );
        } catch {
          /* Ignore an incomplete or invalid artifact. */
        }
      }
    }
    return records.sort((a, b) => b.finishedAt.localeCompare(a.finishedAt));
  }

  async get(reviewId: string): Promise<ReviewRecord | undefined> {
    return (await this.list()).find((record) => record.id === reviewId);
  }
}

function renderMarkdown(record: ReviewRecord): string {
  const findings = record.evidence.filter((item) => item.found === true);
  return [
    `# Rust PR #${record.pr.id}: ${record.pr.title}`,
    "",
    `PR: ${record.pr.url}  `,
    `Head: \`${record.pr.headSha}\`  `,
    `Model: \`${record.model}\`  `,
    `Status: ${findings.length ? "candidate finding" : "no reproducible behavior difference observed"}`,
    "",
    "## Review",
    "",
    record.report || "No final report was submitted.",
    "",
    "## Test strategies",
    "",
    ...(record.strategies.length
      ? record.strategies.map(
          (s) =>
            `- **${s.name}**${s.passId ? ` [${s.passId}]` : ""} — ${s.target}: ${s.rationale}`,
        )
      : ["No strategy records were saved."]),
    "",
    "## Phase execution",
    "",
    ...(record.phases?.map(
      (phase) =>
        `- Phase ${phase.phase}: ${phase.toolCalls} tool calls; ${phase.startedAt} → ${phase.finishedAt}`,
    ) ?? ["Legacy single-session run (no enforced phase boundaries)."]),
    ...(record.analysis
      ? ["", "### Phase 1 reasoning", "", record.analysis.thoughts]
      : []),
    "",
    "## Evidence",
    "",
    ...(record.evidence.length
      ? record.evidence.map(
          (e, i) =>
            `- ${i + 1}. \`${e.tool}\`: ${e.status}${e.found ? " (difference found)" : ""}`,
        )
      : ["No test tools were run."]),
    "",
    "Miri only filters inputs with undefined behavior; it is not an equivalence proof. A clean review is not proof of compiler correctness.",
    "",
  ].join("\n");
}
