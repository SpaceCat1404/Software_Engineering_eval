"use client";
import { Fragment, useEffect, useMemo, useState } from "react";
import StatTile from "./components/StatTile";
import SrsDetail from "./components/detail/SrsDetail";
import TestPlanDetail from "./components/detail/TestPlanDetail";
import SadsDetail from "./components/detail/SadsDetail";
import type { DocType, TeamsResponse, Team } from "./types";
import { flagTone } from "./types";

const DOC_TYPES: { key: DocType; label: string }[] = [
  { key: "srs", label: "SRS" },
  { key: "test_plan", label: "Test Plan" },
  { key: "sads", label: "SAD Spec" },
];

type FlagFilter = "all" | "unscored" | "flagged" | "lowscore";

export default function Page() {
  const [docType, setDocType] = useState<DocType>("srs");
  const [data, setData] = useState<TeamsResponse | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [flagFilter, setFlagFilter] = useState<FlagFilter>("all");
  const [sortKey, setSortKey] = useState<string>("team_id");
  const [sortAsc, setSortAsc] = useState(true);

  async function refreshTeams(dt: DocType = docType) {
    const res = await fetch(`/api/teams/${dt}`);
    const d: TeamsResponse = await res.json();
    setData(d);
  }

  useEffect(() => {
    setExpanded(null);
    refreshTeams(docType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docType]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    setUploading(true);
    setError(null);
    setNotice(null);
    const failed: string[] = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      setUploadProgress(`Uploading ${i + 1} / ${files.length}: ${file.name}`);
      const form = new FormData();
      form.append("file", file);
      try {
        const res = await fetch(`/api/upload/${docType}`, { method: "POST", body: form });
        if (!res.ok) throw new Error((await res.json()).detail || "upload failed");
      } catch (err: any) {
        failed.push(`${file.name}: ${err.message}`);
      }
    }
    await refreshTeams();
    setUploading(false);
    setUploadProgress(null);
    e.target.value = "";
    if (failed.length > 0) setError(`${failed.length} file(s) failed:\n${failed.join("\n")}`);
    else setNotice(`Uploaded ${files.length} file(s) successfully.`);
  }

  async function handleEvaluateLocal() {
    setEvaluating(true);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch(`/api/evaluate-local/${docType}`, { method: "POST" });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "evaluation failed");
      await refreshTeams();
      setNotice(`Evaluated ${d.teams.length} file(s) from ${d.folder}.`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setEvaluating(false);
    }
  }

  async function handleScoreAll() {
    setScoring(true);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch(`/api/score-all/${docType}`, { method: "POST" });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "scoring failed");
      await refreshTeams();
      setNotice(`AI-scored ${d.scored} team(s).`);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setScoring(false);
    }
  }

  const teams = data?.teams ?? [];
  const idCategories = data?.id_categories ?? [];
  const maxTotal = data?.max_total ?? 0;

  const stats = useMemo(() => {
    const n = teams.length;
    const scored = teams.filter((t) => t.score);
    const avgPct = scored.length ? (scored.reduce((a, t) => a + (t.score?.percentage ?? 0), 0) / scored.length).toFixed(1) : "–";
    const flagged = scored.filter((t) => flagTone(t.score?.flags)).length;
    const lowGrounding = scored.filter((t) => {
      const sc = t.score?.sanity_check;
      return sc && sc.cited_count > 0 && sc.grounded_fraction < 0.8;
    }).length;
    return { n, scoredCount: scored.length, avgPct, flagged, lowGrounding };
  }, [teams]);

  function idCount(t: Team, catKey: string): number | null {
    const ids = t.score?.extracted_ids?.[catKey];
    return ids ? ids.length : null;
  }

  function getSortVal(t: Team, key: string): number | string {
    if (key.startsWith("idcount:")) return idCount(t, key.slice("idcount:".length)) ?? -1;
    switch (key) {
      case "team_id":
        return t.team_id.toLowerCase();
      case "grounded":
        return t.score?.sanity_check?.grounded_fraction ?? -1;
      case "score":
        return t.score?.total_score ?? -1;
      default:
        return 0;
    }
  }

  const visibleTeams = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = teams.filter((t) => {
      if (q && !t.team_id.toLowerCase().includes(q)) return false;
      if (flagFilter === "unscored" && t.score) return false;
      if (flagFilter === "flagged" && !(t.score && flagTone(t.score.flags))) return false;
      if (flagFilter === "lowscore" && !(t.score && t.score.percentage < 50)) return false;
      return true;
    });
    list = [...list].sort((a, b) => {
      const av = getSortVal(a, sortKey);
      const bv = getSortVal(b, sortKey);
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
    return list;
  }, [teams, search, flagFilter, sortKey, sortAsc]);

  function toggleSort(key: string) {
    if (sortKey === key) setSortAsc((v) => !v);
    else {
      setSortKey(key);
      setSortAsc(true);
    }
  }

  function groundingBadge(t: Team) {
    const s = t.score;
    if (!s) return <span className="badge neutral">–</span>;
    const sc = s.sanity_check;
    if (!sc || sc.cited_count === 0) return <span className="badge neutral">n/a</span>;
    const pct = Math.round(sc.grounded_fraction * 100);
    const tone = pct >= 90 ? "green" : pct >= 70 ? "amber" : "red";
    return (
      <span className={`badge ${tone}`}>
        {pct}% ({sc.grounded_count}/{sc.cited_count})
      </span>
    );
  }

  return (
    <div className="page">
      <div className="tabs">
        {DOC_TYPES.map((dt) => (
          <button key={dt.key} className={`tab ${docType === dt.key ? "active" : ""}`} onClick={() => setDocType(dt.key)}>
            {dt.label}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 16 }}>
        <div>
          <h1 className="section-title">{DOC_TYPES.find((d) => d.key === docType)?.label} Submissions</h1>
          <p className="section-subtitle">AI rubric evaluation, self-verified against extracted document text</p>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <label className="btn" style={{ cursor: uploading ? "default" : "pointer" }}>
            {uploading ? uploadProgress ?? "Uploading…" : "Upload (.docx / .pdf, multiple ok)"}
            <input type="file" accept=".docx,.pdf" multiple onChange={handleUpload} disabled={uploading} style={{ display: "none" }} />
          </label>
          <button className="btn secondary" onClick={handleEvaluateLocal} disabled={evaluating}>
            {evaluating ? "Evaluating…" : "Evaluate local folder"}
          </button>
          <button className="btn secondary" onClick={handleScoreAll} disabled={scoring || teams.length === 0}>
            {scoring ? "Scoring…" : "Score all (AI rubric)"}
          </button>
        </div>
      </div>

      {error && (
        <div className="card" style={{ borderColor: "var(--red)", background: "var(--red-soft)", color: "var(--red)", marginTop: 16, whiteSpace: "pre-line" }}>
          {error}
        </div>
      )}
      {notice && (
        <div className="card" style={{ borderColor: "var(--green)", background: "var(--green-soft)", color: "var(--green)", marginTop: 16 }}>
          {notice}
        </div>
      )}

      <div className="stat-grid">
        <StatTile label="Teams submitted" value={stats.n} />
        <StatTile label="AI-scored" value={`${stats.scoredCount} / ${stats.n}`} />
        <StatTile label="Avg AI score" value={`${stats.avgPct}%`} />
        <StatTile label="Flagged" value={stats.flagged} tone={stats.flagged ? "amber" : "green"} />
        <StatTile label="Low grounding (<80%)" value={stats.lowGrounding} tone={stats.lowGrounding ? "amber" : "green"} />
      </div>

      <div className="controls">
        <input type="text" placeholder="Filter by team name..." value={search} onChange={(e) => setSearch(e.target.value)} />
        <select value={flagFilter} onChange={(e) => setFlagFilter(e.target.value as FlagFilter)}>
          <option value="all">All teams</option>
          <option value="unscored">Not yet scored</option>
          <option value="flagged">Has a flag (incl. low grounding)</option>
          <option value="lowscore">Score &lt; 50%</option>
        </select>
      </div>

      {teams.length === 0 ? (
        <div className="card" style={{ textAlign: "center", color: "var(--text-muted)" }}>
          No submissions yet — upload a file or evaluate the local folder to get started.
        </div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th onClick={() => toggleSort("team_id")}>Team</th>
              {idCategories.map((cat) => (
                <th key={cat.key} className="num" onClick={() => toggleSort(`idcount:${cat.key}`)}>
                  {cat.label}
                </th>
              ))}
              <th className="num" onClick={() => toggleSort("grounded")}>
                Grounding
              </th>
              <th className="num" onClick={() => toggleSort("score")}>
                AI Score
              </th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {visibleTeams.length === 0 && (
              <tr>
                <td colSpan={4 + idCategories.length} className="empty" style={{ textAlign: "center", color: "var(--text-muted)", padding: 20 }}>
                  No teams match this filter.
                </td>
              </tr>
            )}
            {visibleTeams.map((t) => {
              const s = t.score;
              const tone = flagTone(s?.flags);
              const isOpen = expanded === t.team_id;
              return (
                <Fragment key={t.team_id}>
                  <tr className="team-row" onClick={() => setExpanded(isOpen ? null : t.team_id)}>
                    <td className="team-name-cell" title={t.team_id}>
                      {t.team_id}
                    </td>
                    {idCategories.map((cat) => (
                      <td key={cat.key} className="num">
                        {idCount(t, cat.key) ?? "–"}
                      </td>
                    ))}
                    <td>{groundingBadge(t)}</td>
                    <td>
                      {s ? (
                        <span className={`badge ${s.percentage >= 75 ? "green" : s.percentage >= 50 ? "amber" : "red"}`}>
                          {s.total_score}/{maxTotal} ({s.percentage}%)
                        </span>
                      ) : (
                        <span className="badge neutral">not scored</span>
                      )}
                    </td>
                    <td>
                      {tone ? (
                        <span className={`badge ${tone}`}>{(s?.flags?.length ?? 0) > 60 ? s?.flags.slice(0, 57) + "..." : s?.flags}</span>
                      ) : (
                        <span className="badge green">none</span>
                      )}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="detail-row">
                      <td colSpan={4 + idCategories.length}>
                        {docType === "srs" ? (
                          <SrsDetail team={t} />
                        ) : docType === "test_plan" ? (
                          <TestPlanDetail team={t} />
                        ) : (
                          <SadsDetail team={t} />
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
