// Pure presentational leaf: renders one extracted-id category as a chip
// list, striking through anything the citation-grounding check couldn't
// find verbatim in the source document. Doesn't know or care what doc type
// it's rendering for -- each Detail component decides which categories to
// show and in what order/grouping.
export default function IdCategoryGroup({
  label,
  ids,
  ungrounded,
}: {
  label: string;
  ids: string[];
  ungrounded: Set<string>;
}) {
  return (
    <div style={{ marginBottom: 10 }}>
      <b style={{ fontSize: 12, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.03em" }}>
        {label} ({ids.length})
      </b>
      <div style={{ marginTop: 4 }}>
        {ids.length === 0 ? (
          <span style={{ color: "var(--text-muted)", fontSize: 13 }}>none found</span>
        ) : (
          ids.map((id, i) => (
            <span
              key={i}
              style={{
                display: "inline-block", fontFamily: "ui-monospace, Consolas, monospace",
                fontSize: 11, borderRadius: 6, padding: "2px 6px", margin: "2px 3px 2px 0",
                background: ungrounded.has(id) ? "var(--red-soft)" : "var(--accent-soft)",
                color: ungrounded.has(id) ? "var(--red)" : "var(--text)",
                textDecoration: ungrounded.has(id) ? "line-through" : "none",
              }}
            >
              {id}
            </span>
          ))
        )}
      </div>
    </div>
  );
}
