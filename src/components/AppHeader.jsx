import { Activity, ChartNoAxesCombined, Swords } from "lucide-react";

const VIEWS = [
  { key: "cards", label: "Cards", icon: Swords },
  { key: "bets", label: "Bet Center", icon: ChartNoAxesCombined },
];

export default function AppHeader({ activeView, onChangeView, onOpenDataHealth }) {
  return (
    <header className="app-header">
      <div className="app-brand">
        <span className="app-brand-mark">FC</span>
        <span>
          <strong>FightCenter</strong>
          <small>MMA intelligence workspace</small>
        </span>
      </div>

      <nav className="app-primary-nav" aria-label="Main dashboard navigation">
        {VIEWS.map(({ key, label, icon: Icon }) => (
          <button
            type="button"
            key={key}
            className={activeView === key ? "active" : ""}
            aria-current={activeView === key ? "page" : undefined}
            onClick={() => onChangeView(key)}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </nav>

      <button
        type="button"
        className="data-health-nav-button"
        onClick={onOpenDataHealth}
      >
        <Activity size={16} />
        Data Health
      </button>
    </header>
  );
}
