// Single-page app now (see app/page.tsx) -- doc-type tabs live there, so
// this header is just a static title, no nav links.
export default function Header() {
  return (
    <header style={{ borderBottom: "1px solid var(--border)", background: "var(--card-bg)" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "16px 24px" }}>
        <div style={{ fontWeight: 800, fontSize: 16 }}>SE Project Grader</div>
        <div style={{ fontSize: 12, color: "var(--text-muted)", letterSpacing: "0.03em" }}>
          SOFTWARE ENGINEERING · AI RUBRIC EVALUATION
        </div>
      </div>
    </header>
  );
}
