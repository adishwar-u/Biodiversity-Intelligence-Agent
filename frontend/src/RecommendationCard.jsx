export default function RecommendationCard({ rec }) {
  return (
    <details className="rec-card" open>
      <summary>
        <span className="rec-title">{rec.action}</span>
        <span className="badge">{rec.horizon} horizon</span>
        <span className="badge">{rec.confidence} confidence</span>
      </summary>

      <p className="rec-mechanism">
        <strong>Why it works:</strong> {rec.mechanism}
      </p>

      {rec.cascade.length > 0 && (
        <div className="rec-section">
          <strong>Causal cascade:</strong>
          {rec.cascade.slice(0, 3).map((line, i) => (
            <pre key={i} className="cascade-line">
              {line.replaceAll(" -> ", "  →  ")}
            </pre>
          ))}
        </div>
      )}

      <div className="rec-section">
        <strong>Metrics improved:</strong>
        <ul>
          {rec.metrics_improved.map((m, i) => (
            <li key={i}>
              <code>{m.metric}</code> — {m.delta} ({m.horizon}, {m.confidence} confidence)
            </li>
          ))}
        </ul>
      </div>

      {rec.tradeoffs.length > 0 && (
        <div className="rec-section">
          <strong>Tradeoffs:</strong>
          <ul>
            {rec.tradeoffs.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rec-section">
        <strong>Sources:</strong>
        <ul>
          {rec.sources.map((s, i) => (
            <li key={i}>
              {s.title} ({s.org}
              {s.year ? `, ${s.year}` : ""})
            </li>
          ))}
        </ul>
      </div>

      {rec.evidence.length > 0 && (
        <p className="rec-evidence">
          Supporting literature: {rec.evidence.map((e) => `${e.title} (${e.org})`).join("; ")}
        </p>
      )}
    </details>
  );
}
