import type { PassAssignment } from "./rust/passes.js";
export interface RustPullRequest {
  id: number;
  url: string;
  title: string;
  body: string;
  author: string;
  state: string;
  baseSha: string;
  headSha: string;
  mergeSha?: string;
  patch: string;
  patchSource?: "git-first-parent-merge-diff" | "github-pull-diff";
  files: string[];
  components: string[];
  createdAt: string;
  passes?: PassAssignment[];
}

export interface TestStrategy {
  name: string;
  target: string;
  rationale: string;
  expectedIssue: string;
  passId?: string;
}

export interface ToolEvidence {
  tool: string;
  status: string;
  clean?: boolean;
  found?: boolean;
  source?: string;
  stdout?: string;
  stderr?: string;
  [key: string]: unknown;
}

export interface ReviewRecord {
  id: string;
  pr: RustPullRequest;
  model: string;
  startedAt: string;
  finishedAt: string;
  report: string;
  strategies: TestStrategy[];
  evidence: ToolEvidence[];
  knowledge: KnowledgeRecord[];
  analysis?: { thoughts: string; strategies: TestStrategy[] };
  phases?: Array<{
    phase: 1 | 2;
    startedAt: string;
    finishedAt: string;
    toolCalls: number;
  }>;
}

export interface KnowledgeRecord {
  prId: number;
  headSha: string;
  component: string;
  passId?: string;
  summary: string;
  optimization: string;
  evidence: string[];
  sourceUrl: string;
  extractedAt: string;
}
