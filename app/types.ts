// Shapes returned by GET /api/teams/{doc_type} (api/index.py) and produced
// by scorer.py's RUBRICS-driven score(). Generic across doc types: which
// criteria/id-categories exist differs per doc type, but the shape itself
// doesn't (see scorer.py's docstring for what's shared vs. bespoke).

export type DocType = "srs" | "test_plan" | "sads";

export type Criterion = {
  key: string;
  label: string;
  max: number;
  group: string | null;
};

export type ScoredCriterion = Criterion & {
  score: number;
  justification: string;
};

export type SanityCheck = {
  cited_count: number;
  grounded_count: number;
  grounded_fraction: number;
  ungrounded_ids: string[];
};

export type Score = {
  source: string;
  doc_type: DocType;
  extracted_ids: Record<string, string[]>;
  criteria: ScoredCriterion[];
  total_score: number;
  max_total: number;
  percentage: number;
  overall_feedback: string;
  flags: string;
  sanity_check: SanityCheck;
};

export type TableData = {
  headers: string[];
  rows: Record<string, string>[];
  req_id_col: string | null;
  n_data_rows: number;
};

export type Team = {
  team_id: string;
  source: string;
  raw_text: string;
  tables: TableData[];
  score: Score | null;
};

export type IdCategory = { key: string; label: string };

export type TeamsResponse = {
  doc_type: DocType;
  id_categories: IdCategory[];
  criteria: Criterion[];
  max_total: number;
  teams: Team[];
};

export function flagTone(flags: string | undefined | null): "amber" | "red" | null {
  if (!flags || flags === "None") return null;
  if (flags.startsWith("SCORING ERROR")) return "red";
  return "amber";
}
