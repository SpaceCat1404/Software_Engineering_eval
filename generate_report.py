#!/usr/bin/env python3
"""
generate_report.py — build a single self-contained results.html from the
local blob cache (pipeline_out/blob_local/submissions/{doc_type}/*_score.json),
so results are viewable without the Next.js frontend.

Why: useful as a no-server fallback viewer, and for a quick look at a batch
run without starting the Next.js app.

Generic over doc type: scorer.py's rubric shape (report["criteria"], a list
of {key,label,max,score,justification}, and report["extracted_ids"], a dict
of category -> [items found]) already varies per doc type, so this script
reads the doc type's own criteria/id-category definitions out of
scorer.RUBRICS to build the right table columns and detail sections instead
of hardcoding SRS's 4 criteria.

Usage:
    python generate_report.py --doc-type srs [--pipeline-dir pipeline_out] [--out results.html]
    python generate_report.py --doc-type test_plan [--pipeline-dir pipeline_out] [--out results.html]

Re-run any time after a scoring pass to refresh the file.
"""
import argparse
import json
from pathlib import Path

from scorer import RUBRICS


def load_teams(blob_dir: Path) -> list[dict]:
    ingested_files = sorted(blob_dir.glob("*_ingested.json"))
    teams = []
    for inf in ingested_files:
        team_id = inf.stem[: -len("_ingested")]
        ingested = json.loads(inf.read_text(encoding="utf-8"))

        score_path = blob_dir / f"{team_id}_score.json"
        score = json.loads(score_path.read_text(encoding="utf-8")) if score_path.exists() else None

        teams.append({"team_id": team_id, "source": ingested.get("source", team_id), "score": score})
    return teams


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>SRS Eval Results</title>
<style>
  :root {
    --bg: #0b0d10; --panel: #14171b; --border: #262b31; --text: #e8eaed;
    --text-muted: #9aa1a9; --green: #3ecf8e; --amber: #e0a83c; --red: #e5534b;
    --accent: #5b8def;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f6f7f9; --panel:#fff; --border:#e2e5e9; --text:#1a1d21;
      --text-muted:#5c6570; --green:#1f9d63; --amber:#a86a10; --red:#c93a32; --accent:#3760c9; }
  }
  :root[data-theme="dark"] { --bg:#0b0d10; --panel:#14171b; --border:#262b31; --text:#e8eaed;
    --text-muted:#9aa1a9; --green:#3ecf8e; --amber:#e0a83c; --red:#e5534b; --accent:#5b8def; }
  :root[data-theme="light"] { --bg:#f6f7f9; --panel:#fff; --border:#e2e5e9; --text:#1a1d21;
    --text-muted:#5c6570; --green:#1f9d63; --amber:#a86a10; --red:#c93a32; --accent:#3760c9; }

  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
    font: 14px/1.5 -apple-system, Segoe UI, Roboto, sans-serif; }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 28px 20px 80px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: var(--text-muted); font-size: 13px; margin: 0 0 20px; }

  .stat-row { display:flex; gap:14px; flex-wrap:wrap; margin-bottom: 22px; }
  .stat-tile { background:var(--panel); border:1px solid var(--border); border-radius:10px;
    padding:14px 16px; min-width:130px; flex:1; }
  .stat-tile .v { font-size:24px; font-weight:800; }
  .stat-tile .l { color:var(--text-muted); font-size:12px; margin-top:2px; }

  .controls { display:flex; gap:10px; margin-bottom: 14px; align-items:center; flex-wrap:wrap; }
  input[type=text] { background:var(--panel); border:1px solid var(--border); color:var(--text);
    border-radius:8px; padding:8px 10px; font-size:13px; flex:1; min-width:200px; }
  select { background:var(--panel); border:1px solid var(--border); color:var(--text);
    border-radius:8px; padding:8px 10px; font-size:13px; }

  table { width:100%; border-collapse: collapse; background:var(--panel);
    border:1px solid var(--border); border-radius:10px; overflow:hidden; }
  thead th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.04em;
    color:var(--text-muted); padding:10px 12px; border-bottom:1px solid var(--border);
    cursor:pointer; user-select:none; white-space:nowrap; }
  thead th:hover { color: var(--text); }
  tbody tr { border-bottom:1px solid var(--border); cursor:pointer; }
  tbody tr:hover { background: color-mix(in srgb, var(--accent) 8%, transparent); }
  tbody tr:last-child { border-bottom:none; }
  td { padding:10px 12px; vertical-align:top; }
  .team-name { font-weight:600; max-width: 320px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .num { font-variant-numeric: tabular-nums; }
  .badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700; }
  .badge.green { background: color-mix(in srgb, var(--green) 18%, transparent); color:var(--green); }
  .badge.amber { background: color-mix(in srgb, var(--amber) 18%, transparent); color:var(--amber); }
  .badge.red { background: color-mix(in srgb, var(--red) 18%, transparent); color:var(--red); }
  .badge.grey { background: color-mix(in srgb, var(--text-muted) 18%, transparent); color:var(--text-muted); }

  .detail { display:none; background: var(--bg); border-top:1px solid var(--border); }
  .detail.open { display:table-row; }
  .detail-inner { padding: 16px 20px; display:grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 800px) { .detail-inner { grid-template-columns: 1fr; } }
  .crit { margin-bottom: 12px; }
  .crit b { display:block; margin-bottom:2px; }
  .crit .j { color: var(--text-muted); font-size:13px; }
  .flags-box { border:1px solid var(--amber); background: color-mix(in srgb, var(--amber) 10%, transparent);
    border-radius:8px; padding:10px 12px; font-size:13px; margin-bottom: 12px; }
  .id-chip { display:inline-block; background: color-mix(in srgb, var(--accent) 12%, transparent);
    color: var(--text); border-radius:6px; padding:2px 6px; font-size:11px; margin:2px 3px 2px 0;
    font-family: ui-monospace, Consolas, monospace; }
  .id-chip.ungrounded { background: color-mix(in srgb, var(--red) 18%, transparent); color: var(--red);
    text-decoration: line-through; }
  .req-group { margin-bottom: 10px; }
  .req-group b { font-size:12px; color: var(--text-muted); text-transform:uppercase; letter-spacing:.03em; }
  .empty { color: var(--text-muted); font-size:13px; padding: 20px; text-align:center; }
</style>
</head>
<body>
<div class="wrap">
  <h1 id="pageTitle">Eval Results</h1>
  <p class="sub" id="genInfo"></p>

  <div class="stat-row" id="statRow"></div>

  <div class="controls">
    <input type="text" id="search" placeholder="Filter by team name...">
    <select id="flagFilter">
      <option value="all">All teams</option>
      <option value="unscored">Not yet scored</option>
      <option value="flagged">Has a flag (incl. low grounding)</option>
      <option value="lowscore">Score &lt; 50%</option>
    </select>
  </div>

  <table>
    <thead>
      <tr id="headerRow">
        <th data-sort="team_id">Team</th>
        <th data-sort="grounded" class="num">Grounding</th>
        <th data-sort="score" class="num">AI Score</th>
        <th>Flags</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
  <div id="emptyMsg" class="empty" style="display:none;">No teams match this filter.</div>
</div>

<script>
const TEAMS = __TEAMS_JSON__;
const GENERATED_AT = __GENERATED_AT__;
const DOC_TYPE = __DOC_TYPE_JSON__;
const CRITERIA = __CRITERIA_JSON__;       // [{key,label,max,group}, ...] -- bespoke per doc type
const ID_CATEGORIES = __ID_CATEGORIES_JSON__; // [{key,label}, ...] -- bespoke per doc type
const MAX_TOTAL = __MAX_TOTAL_JSON__;

document.getElementById("pageTitle").textContent = `${DOC_TYPE} Eval Results`;
document.getElementById("genInfo").textContent =
  `${TEAMS.length} team(s) — generated ${GENERATED_AT}. Extracted-item counts and scores come ` +
  `entirely from the AI rubric's own extract-then-score pass -- each cited item is grounded ` +
  `against the extracted document text (see Grounding column / sanity check below).`;

// Insert one <th> per id-category, before the Grounding column.
(function buildHeader() {
  const headerRow = document.getElementById("headerRow");
  const groundingTh = headerRow.children[1];
  ID_CATEGORIES.forEach(cat => {
    const th = document.createElement("th");
    th.className = "num";
    th.dataset.sort = `idcount:${cat.key}`;
    th.textContent = cat.label;
    headerRow.insertBefore(th, groundingTh);
  });
})();

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));
}

function idCount(t, catKey) {
  const ids = t.score?.extracted_ids?.[catKey];
  return ids ? ids.length : null;
}

function flagTone(flags) {
  if (!flags || flags === "None") return null;
  if (flags.startsWith("SCORING ERROR")) return "red";
  return "amber";
}

function groundingBadge(s) {
  if (!s) return `<span class="badge grey">–</span>`;
  const sc = s.sanity_check;
  if (!sc || sc.cited_count === 0) return `<span class="badge grey">n/a</span>`;
  const pct = Math.round(sc.grounded_fraction * 100);
  const tone = pct >= 90 ? "green" : pct >= 70 ? "amber" : "red";
  return `<span class="badge ${tone}">${pct}% (${sc.grounded_count}/${sc.cited_count})</span>`;
}

function row(t) {
  const s = t.score;
  const idCells = ID_CATEGORIES.map(cat => `<td class="num">${idCount(t, cat.key) ?? "–"}</td>`).join("");
  const scoreBadge = s
    ? `<span class="badge ${s.percentage >= 75 ? "green" : s.percentage >= 50 ? "amber" : "red"}">${s.total_score}/${MAX_TOTAL} (${s.percentage}%)</span>`
    : `<span class="badge grey">not scored</span>`;
  const flags = s?.flags;
  const tone = flagTone(flags);
  const flagBadge = tone ? `<span class="badge ${tone}">${esc(flags.length > 60 ? flags.slice(0, 57) + "..." : flags)}</span>` : `<span class="badge green">none</span>`;
  const colspan = 4 + ID_CATEGORIES.length;

  return `
  <tr class="team-row" data-id="${esc(t.team_id)}">
    <td class="team-name" title="${esc(t.team_id)}">${esc(t.team_id)}</td>
    ${idCells}
    <td>${groundingBadge(s)}</td>
    <td>${scoreBadge}</td>
    <td>${flagBadge}</td>
  </tr>
  <tr class="detail" data-id="${esc(t.team_id)}"><td colspan="${colspan}">
    <div class="detail-inner">
      <div>
        <h3 style="margin:0 0 8px;font-size:14px;">AI rubric score</h3>
        ${!s ? `<p style="color:var(--text-muted);">Not yet scored.</p>` : `
          ${tone ? `<div class="flags-box"><b>Flags:</b> ${esc(flags)}</div>` : ""}
          ${criteriaBlocks(s)}
          ${s.overall_feedback ? `<p style="font-size:13px;margin-top:10px;">${esc(s.overall_feedback)}</p>` : ""}
        `}
      </div>
      <div>
        <h3 style="margin:0 0 8px;font-size:14px;">Items found (AI extraction pass)</h3>
        ${!s ? `<p style="color:var(--text-muted);">Not yet scored.</p>` : idGroups(s)}
      </div>
    </div>
  </td></tr>`;
}

function criteriaBlocks(s) {
  const byKey = Object.fromEntries((s.criteria || []).map(c => [c.key, c]));
  return CRITERIA.map(c => {
    const found = byKey[c.key];
    const score = found ? found.score : 0;
    const justification = found ? found.justification : "";
    return `
    <div class="crit"><b>${esc(c.label)} — ${score}/${c.max}</b>
      <div class="j">${esc(justification)}</div></div>`;
  }).join("");
}

function idGroups(s) {
  const found = s.extracted_ids || {};
  const ungrounded = new Set((s.sanity_check?.ungrounded_ids) || []);
  const body = ID_CATEGORIES.map(cat => {
    const ids = found[cat.key] || [];
    return `
    <div class="req-group">
      <b>${esc(cat.label)} (${ids.length})</b><br>
      ${ids.length === 0 ? `<span style="color:var(--text-muted);font-size:13px;">none found</span>` :
        ids.map(id => `<span class="id-chip${ungrounded.has(id) ? " ungrounded" : ""}">${esc(id)}</span>`).join("")}
    </div>`;
  }).join("");
  const sc = s.sanity_check;
  const note = sc && sc.ungrounded_ids && sc.ungrounded_ids.length
    ? `<p style="font-size:12px;color:var(--red);margin-top:8px;">Struck-through items were cited by the model but not found verbatim in the extracted document text -- possible hallucination, verify manually.</p>`
    : `<p style="font-size:12px;color:var(--green);margin-top:8px;">All cited items verified present in the extracted document text.</p>`;
  return body + note;
}

function computeStats() {
  const n = TEAMS.length;
  const scored = TEAMS.filter(t => t.score);
  const avgPct = scored.length
    ? (scored.reduce((a, t) => a + t.score.percentage, 0) / scored.length).toFixed(1)
    : "–";
  const flagged = scored.filter(t => flagTone(t.score.flags)).length;
  const lowGrounding = scored.filter(t => {
    const sc = t.score.sanity_check;
    return sc && sc.cited_count > 0 && sc.grounded_fraction < 0.8;
  }).length;
  return [
    { v: n, l: "Teams" },
    { v: `${scored.length}/${n}`, l: "Scored" },
    { v: `${avgPct}%`, l: "Avg AI score" },
    { v: flagged, l: "Flagged" },
    { v: lowGrounding, l: "Low grounding (<80%)" },
  ];
}

function renderStats() {
  document.getElementById("statRow").innerHTML = computeStats().map(s =>
    `<div class="stat-tile"><div class="v">${s.v}</div><div class="l">${s.l}</div></div>`
  ).join("");
}

let sortKey = "team_id", sortAsc = true;

function getSortVal(t, key) {
  if (key.startsWith("idcount:")) return idCount(t, key.slice("idcount:".length)) ?? -1;
  switch (key) {
    case "team_id": return t.team_id.toLowerCase();
    case "grounded": return t.score?.sanity_check?.grounded_fraction ?? -1;
    case "score": return t.score ? t.score.total_score : -1;
    default: return 0;
  }
}

function render() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const filter = document.getElementById("flagFilter").value;

  let list = TEAMS.filter(t => {
    if (q && !t.team_id.toLowerCase().includes(q)) return false;
    if (filter === "unscored" && t.score) return false;
    if (filter === "flagged" && !(t.score && flagTone(t.score.flags))) return false;
    if (filter === "lowscore" && !(t.score && t.score.percentage < 50)) return false;
    return true;
  });

  list.sort((a, b) => {
    const av = getSortVal(a, sortKey), bv = getSortVal(b, sortKey);
    if (av < bv) return sortAsc ? -1 : 1;
    if (av > bv) return sortAsc ? 1 : -1;
    return 0;
  });

  document.getElementById("rows").innerHTML = list.map(row).join("");
  document.getElementById("emptyMsg").style.display = list.length === 0 ? "block" : "none";

  document.querySelectorAll(".team-row").forEach(tr => {
    tr.addEventListener("click", () => {
      const id = tr.getAttribute("data-id");
      const detail = document.querySelector(`.detail[data-id="${CSS.escape(id)}"]`);
      detail.classList.toggle("open");
    });
  });
}

document.querySelectorAll("thead th[data-sort]").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.getAttribute("data-sort");
    if (sortKey === key) sortAsc = !sortAsc; else { sortKey = key; sortAsc = true; }
    render();
  });
});
document.getElementById("search").addEventListener("input", render);
document.getElementById("flagFilter").addEventListener("change", render);

renderStats();
render();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-type", choices=list(RUBRICS.keys()), default="srs")
    ap.add_argument("--pipeline-dir", default="pipeline_out")
    ap.add_argument("--out", default="results.html")
    args = ap.parse_args()

    blob_dir = Path(args.pipeline_dir) / "blob_local" / "submissions" / args.doc_type
    if not blob_dir.is_dir():
        raise SystemExit(f"no local blob store found at {blob_dir}")

    teams = load_teams(blob_dir)
    if not teams:
        raise SystemExit(f"no *_ingested.json found under {blob_dir}")

    import datetime
    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg = RUBRICS[args.doc_type]

    html = HTML_TEMPLATE.replace("__TEAMS_JSON__", json.dumps(teams))
    html = html.replace("__GENERATED_AT__", json.dumps(generated_at))
    html = html.replace("__DOC_TYPE_JSON__", json.dumps(args.doc_type))
    html = html.replace("__CRITERIA_JSON__", json.dumps(cfg["criteria"]))
    html = html.replace("__ID_CATEGORIES_JSON__", json.dumps(cfg["id_categories"]))
    html = html.replace("__MAX_TOTAL_JSON__", json.dumps(cfg["max_total"]))

    out_path = Path(args.out)
    out_path.write_text(html, encoding="utf-8")

    scored = sum(1 for t in teams if t["score"])
    print(f"Wrote {out_path} — {len(teams)} team(s), {scored} scored.")


if __name__ == "__main__":
    main()
