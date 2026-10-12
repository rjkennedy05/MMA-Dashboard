import { Activity, X } from "lucide-react";
import { useEffect } from "react";

import DataSyncStatus from "./DataSyncStatus";

export default function DataHealthDrawer({ open, onClose, onSyncCompleted }) {
  useEffect(() => {
    if (!open) return undefined;
    function closeOnEscape(event) {
      if (event.key === "Escape") onClose?.();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div
      className="data-health-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.();
      }}
    >
      <aside
        className="data-health-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="data-health-title"
      >
        <header className="data-health-drawer-header">
          <div>
            <p className="eyebrow">Coverage, freshness and exceptions</p>
            <h2 id="data-health-title"><Activity size={19} /> Data Health</h2>
            <p>
              Refreshes, missing odds, incomplete cards and history exceptions
              live here instead of interrupting matchup research.
            </p>
          </div>
          <button type="button" aria-label="Close data health" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <DataSyncStatus onSyncCompleted={onSyncCompleted} />
      </aside>
    </div>
  );
}
