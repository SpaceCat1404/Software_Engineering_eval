import type { Team } from "../../types";
import { flagTone } from "../../types";
import IdCategoryGroup from "./IdCategoryGroup";
import DocumentContents from "../DocumentContents";

// SRS's own detail layout: 4 flat criteria (intro/requirements/uml/security),
// 4 extracted-id categories (FR/NFR/security objectives/security
// requirements). Deliberately not shared with TestPlanDetail -- SRS's shape
// may keep diverging (e.g. surfacing the UML criterion differently) without
// needing a shared conditional to stay generic.
export default function SrsDetail({ team }: { team: Team }) {
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
        <h3 style={{ margin: "0 0 8px", fontSize: 14 }}>Requirements found (AI extraction pass)</h3>
        {["functional_requirements", "non_functional_requirements", "security_objectives", "security_requirements"].map((key) => (
          <IdCategoryGroup
            key={key}
            label={key.replace(/_/g, " ")}
            ids={s.extracted_ids[key] || []}
            ungrounded={ungrounded}
          />
        ))}
        <p style={{ fontSize: 12, color: ungrounded.size ? "var(--red)" : "var(--green)", marginTop: 8 }}>
          {ungrounded.size
            ? "Struck-through items were cited by the model but not found verbatim in the extracted document text -- possible hallucination, verify manually."
            : "All cited items verified present in the extracted document text."}
        </p>
      </div>
    </div>
  );
}
