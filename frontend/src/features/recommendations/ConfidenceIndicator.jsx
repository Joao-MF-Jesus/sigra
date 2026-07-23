import React from "react";
import { getConfidence } from "./recommendationModel.js";

export default function ConfidenceIndicator({ item, compact = false }) {
  const confidence = getConfidence(item);
  return (
    <div className={`confidence-indicator confidence-${confidence.level} ${compact ? "compact" : ""}`}>
      <span>Confiança dos dados</span>
      <strong>{confidence.level}{confidence.score === null ? "" : ` — ${confidence.score}/100`}</strong>
    </div>
  );
}
