import { useState } from "react";
import { useBadge } from "../hooks.js";

const ICONS = { green: "✓", red: "!", amber: "?", grey: "–", blue: "" };

/** Verification badge under an assistant message (INTEGRATION_GUIDE section 7). */
export default function Badge({ messageId }) {
  const badge = useBadge(messageId);
  const [open, setOpen] = useState(false);

  // Every answer always shows a status. If verification could not run, it says "Not verified"
  // (with the reason) rather than showing nothing, and the chat keeps working.
  if (!badge.text) return null;

  const checking = badge.state === "checking";
  const hasDetails = badge.claims && badge.claims.length > 0;

  return (
    <div className="badge-wrap">
      <button
        type="button"
        className={`badge badge-${badge.color}`}
        onClick={() => hasDetails && setOpen((o) => !o)}
        disabled={!hasDetails}
        aria-expanded={open}
      >
        {checking ? <span className="spinner" aria-hidden /> : <span className="icon">{ICONS[badge.color]}</span>}
        <span>{badge.text}</span>
        {badge.confidence != null && !checking && (
          <span className="conf">{Math.round(badge.confidence * 100)}%</span>
        )}
        {hasDetails && <span className="chev">{open ? "▴" : "▾"}</span>}
      </button>

      {badge.state === "unavailable" && badge.error && (
        <div className="muted">Verification did not run: {badge.error}</div>
      )}

      {badge.state === "stale" && badge.suggested_correction && (
        <div className="correction">
          <strong>Suggested correction:</strong> {badge.suggested_correction}
          {badge.source_url && (
            <>
              {" "}
              <a href={badge.source_url} target="_blank" rel="noreferrer">
                Source ↗
              </a>
            </>
          )}
        </div>
      )}

      {open && hasDetails && (
        <ul className="claims">
          {badge.claims.map((c, i) => (
            <li key={i}>
              <div className="claim-head">
                <span className={`pill pill-${c.label}`}>{c.label?.replace("_", " ")}</span> {c.text}
              </div>
              {c.reasoning && <div className="muted">{c.reasoning}</div>}
              {c.evidence?.map((e, j) => (
                <div key={j} className="evidence">
                  <span className="stance">{e.stance}</span>{" "}
                  <a href={e.url} target="_blank" rel="noreferrer">
                    {e.url}
                  </a>
                  {e.quoted_span && <blockquote>“{e.quoted_span}”</blockquote>}
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
