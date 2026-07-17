export default function StatTile({
  label,
  value,
  tone,
  sublabel,
}: {
  label: string;
  value: string | number;
  tone?: "green" | "amber" | "red";
  sublabel?: string;
}) {
  const color =
    tone === "green" ? "var(--green)" : tone === "amber" ? "var(--amber)" : tone === "red" ? "var(--red)" : "var(--text)";
  return (
    <div className="stat-tile">
      <p className="label">{label}</p>
      <p className="value" style={{ color }}>{value}</p>
      {sublabel && <p className="sublabel">{sublabel}</p>}
    </div>
  );
}
