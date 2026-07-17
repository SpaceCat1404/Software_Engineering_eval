import type { Team } from "../../types";
import { flagTone } from "../../types";
import IdCategoryGroup from "./IdCategoryGroup";
import DocumentContents from "../DocumentContents";

// SAD Spec's own detail layout: the one doc type with a real two-level
// rubric (Architecture=10, Design=10, each with its own sub-criteria) --
// scorer.py's criteria already carry a "group" field for this, SRS/Test
// Plan just leave it null. Grouped into two subtotal sections here instead
// of SrsDetail/TestPlanDetail's flat criteria list. 3 extracted-id
// categories (requirement IDs referenced for traceability, API endpoints,
// components named).
const GROUPS = ["Architecture", "Design"] as const;

export default function SadsDetail({ team }: { team: Team }) {
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
        {GROUPS.map((group) => {
          const criteria = s.criteria.filter((c) => c.group === group);
          if (criteria.length === 0) return null;
          const subtotal = criteria.reduce((a, c) => a + c.score, 0);
          const submax = criteria.reduce((a, c) => a + c.max, 0);
          return (
            <div key={group} style={{ marginBottom: 16 }}>
              <div
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "baseline",
                  borderBottom: "1px solid var(--border)", paddingBottom: 4, marginBottom: 8,
                }}
              >
                <b style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "0.03em", color: "var(--text-muted)" }}>
                  {group}
                </b>
                <span style={{ fontSize: 13, fontWeight: 700 }}>
                  {subtotal}/{submax}
                </span>
              </div>
              {criteria.map((c) => (
                <div key={c.key} style={{ marginBottom: 10 }}>
                  <b>{c.label}</b> — {c.score}/{c.max}
                  <div style={{ color: "var(--text-muted)", fontSize: 13 }}>{c.justification}</div>
                </div>
              ))}
            </div>
          );
        })}
        {s.overall_feedback && <p style={{ fontSize: 13, marginTop: 10 }}>{s.overall_feedback}</p>}
        <DocumentContents rawText={team.raw_text} tables={team.tables} />
      </div>
      <div>
        <h3 style={{ margin: "0 0 8px", fontSize: 14 }}>Items found (AI extraction pass)</h3>
        <IdCategoryGroup
          label="Requirement IDs referenced (traceability)"
          ids={s.extracted_ids["requirement_ids_referenced"] || []}
          ungrounded={ungrounded}
        />
        <IdCategoryGroup label="API endpoints" ids={s.extracted_ids["api_endpoints"] || []} ungrounded={ungrounded} />
        <IdCategoryGroup label="Components named" ids={s.extracted_ids["components"] || []} ungrounded={ungrounded} />
        <p style={{ fontSize: 12, color: ungrounded.size ? "var(--red)" : "var(--green)", marginTop: 8 }}>
          {ungrounded.size
            ? "Struck-through items were cited by the model but not found verbatim in the extracted document text -- possible hallucination, verify manually."
            : "All cited items verified present in the extracted document text."}
        </p>
      </div>
    </div>
  );
}
