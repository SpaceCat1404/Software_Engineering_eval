import type { Team } from "../../types";
import { flagTone } from "../../types";
import IdCategoryGroup from "./IdCategoryGroup";
import DocumentContents from "../DocumentContents";

// Test Plan's own detail layout: 5 flat criteria (intro/core sections/
// security validation/traceability/test case coverage), 3 extracted-id
// categories (test case IDs, SRS requirement IDs referenced for
// traceability, security validation items). Kept as its own component
// (not shared with SrsDetail) so this rubric's shape can diverge freely --
// e.g. calling out the traceability criterion next to the SRS-requirement-
// IDs-referenced category, which SRS's layout has no equivalent of.
export default function TestPlanDetail({ team }: { team: Team }) {
  const s = team.score;
  if (!s) return <p style={{ color: "var(--text-muted)" }}>Not yet scored.</p>;

  const tone = flagTone(s.flags);
  const ungrounded = new Set(s.sanity_check.ungrounded_ids);

  return (
    <div className="detail-inner">
      <div>
        <h3 style={{ margin: "0 0 8px", fontSize: 14 }}>AI rubric score</h3>
        {tone && (
          <div className="card" style={{ borderColor: "var(--amber)", marginBottom: 10, fontSize: 13 }}>
            <b>Flags:</b> {s.flags}
          </div>
        )}
        {s.criteria.map((c) => (
          <div key={c.key} style={{ marginBottom: 10 }}>
            <b>{c.label}</b> — {c.score}/{c.max}
            <div style={{ color: "var(--text-muted)", fontSize: 13 }}>{c.justification}</div>
          </div>
        ))}
        {s.overall_feedback && <p style={{ fontSize: 13, marginTop: 10 }}>{s.overall_feedback}</p>}
        <DocumentContents rawText={team.raw_text} tables={team.tables} />
      </div>
      <div>
        <h3 style={{ margin: "0 0 8px", fontSize: 14 }}>Items found (AI extraction pass)</h3>
        <IdCategoryGroup label="Test Case IDs" ids={s.extracted_ids["test_case_ids"] || []} ungrounded={ungrounded} />
        <IdCategoryGroup
          label="SRS Requirement IDs referenced (traceability)"
          ids={s.extracted_ids["srs_requirement_ids_referenced"] || []}
          ungrounded={ungrounded}
        />
        <IdCategoryGroup
          label="Security Validation items"
          ids={s.extracted_ids["security_validation_items"] || []}
          ungrounded={ungrounded}
        />
        <p style={{ fontSize: 12, color: ungrounded.size ? "var(--red)" : "var(--green)", marginTop: 8 }}>
          {ungrounded.size
            ? "Struck-through items were cited by the model but not found verbatim in the extracted document text -- possible hallucination, verify manually."
            : "All cited items verified present in the extracted document text."}
        </p>
      </div>
    </div>
  );
}
