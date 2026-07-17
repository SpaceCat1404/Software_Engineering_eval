"use client";
import { useState } from "react";
import type { TableData } from "../types";

export default function DocumentContents({ rawText, tables }: { rawText: string; tables: TableData[] }) {
  const [showDoc, setShowDoc] = useState(false);

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
        onClick={() => setShowDoc((v) => !v)}
      >
        <h3 style={{ fontSize: 14, margin: 0 }}>
          Document contents ({tables.length} table{tables.length === 1 ? "" : "s"})
        </h3>
        <span style={{ fontSize: 13, color: "var(--accent)", fontWeight: 600 }}>
          {showDoc ? "Hide ▲" : "Show for cross-check ▼"}
        </span>
      </div>
      {showDoc && (
        <div style={{ marginTop: 12 }}>
          {rawText && (
            <pre
              style={{
                fontSize: 13, color: "var(--text-muted)", whiteSpace: "pre-wrap",
                maxHeight: 400, overflowY: "auto", margin: "0 0 12px",
                border: "1px solid var(--border)", borderRadius: 8, padding: 10,
              }}
            >
              {rawText}
            </pre>
          )}
          {tables.map((t, ti) => (
            <div key={ti} style={{ borderTop: "1px solid var(--border)", padding: "10px 0", overflowX: "auto" }}>
              <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 4, color: "var(--text-muted)" }}>
                Table {ti + 1} {t.req_id_col ? `(id column: ${t.req_id_col}, ${t.n_data_rows} rows)` : `(${t.n_data_rows} rows)`}
              </div>
              <table style={{ borderCollapse: "collapse", fontSize: 12, width: "100%" }}>
                <thead>
                  <tr>
                    {t.headers.map((h, hi) => (
                      <th key={hi} style={{ textAlign: "left", padding: "4px 8px", borderBottom: "1px solid var(--border)", color: "var(--text-muted)" }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {t.rows.map((row, ri) => (
                    <tr key={ri}>
                      {t.headers.map((h, hi) => (
                        <td key={hi} style={{ padding: "4px 8px", borderBottom: "1px solid var(--border)", verticalAlign: "top" }}>
                          {row[h]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
