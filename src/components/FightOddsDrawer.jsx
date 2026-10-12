import { ExternalLink, RefreshCw, TrendingUp, X } from "lucide-react";
import { useEffect, useState } from "react";

const WIDGET_URL = "https://fightodds.io/widget";

export default function FightOddsDrawer() {
  const [open, setOpen] = useState(false);
  const [frameKey, setFrameKey] = useState(0);

  useEffect(() => {
    if (!open) return undefined;

    function closeOnEscape(event) {
      if (event.key === "Escape") setOpen(false);
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  return (
    <>
      <button
        type="button"
        className="fightodds-open-button"
        onClick={() => setOpen(true)}
      >
        <TrendingUp size={14} /> Live FightOdds
      </button>

      {open ? (
        <div
          className="fightodds-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
        >
          <section
            className="fightodds-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="fightodds-title"
          >
            <header className="fightodds-drawer-header">
              <div>
                <p className="eyebrow">Live reference board</p>
                <h2 id="fightodds-title">FightOdds</h2>
              </div>
              <div className="fightodds-drawer-actions">
                <button
                  type="button"
                  title="Reload widget"
                  aria-label="Reload FightOdds widget"
                  onClick={() => setFrameKey((current) => current + 1)}
                >
                  <RefreshCw size={16} />
                </button>
                <a
                  href={WIDGET_URL}
                  target="_blank"
                  rel="noreferrer"
                  title="Open FightOdds in a new tab"
                  aria-label="Open FightOdds in a new tab"
                >
                  <ExternalLink size={16} />
                </a>
                <button
                  type="button"
                  title="Close"
                  aria-label="Close FightOdds"
                  onClick={() => setOpen(false)}
                >
                  <X size={18} />
                </button>
              </div>
            </header>

            <p className="fightodds-reference-note">
              Visual reference only. Enter the actual line you receive in Odds taken;
              the dashboard cannot read data inside this external widget.
            </p>

            <div className="fightodds-frame-shell">
              <iframe
                key={frameKey}
                src={WIDGET_URL}
                width="100%"
                height="100%"
                style={{ border: "none", minHeight: "800px", width: "100%" }}
                title="FightOdds live odds widget"
                loading="lazy"
                referrerPolicy="strict-origin-when-cross-origin"
              />
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
