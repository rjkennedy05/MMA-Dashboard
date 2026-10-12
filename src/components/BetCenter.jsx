import { ChartNoAxesCombined } from "lucide-react";

import BetEventPicker from "./BetEventPicker";
import ParlayEntry from "./ParlayEntry";
import ResultsRoi from "./ResultsRoi";

export default function BetCenter({ eventId, onSelectEvent, refreshKey = 0, onBetSaved }) {
  return (
    <div className="bet-center-view">
      <header className="section-hero bet-center-hero">
        <div className="section-hero-icon"><ChartNoAxesCombined size={22} /></div>
        <div>
          <p className="eyebrow">Current tracking period</p>
          <h1>Bet Center</h1>
          <p>
            Build tickets, review open exposure, grade outcomes and inspect the
            active record without crowding the fight-research workspace.
          </p>
        </div>
      </header>

      <BetEventPicker
        selectedEventId={eventId}
        onSelectEvent={onSelectEvent}
        refreshKey={refreshKey}
      />

      <ParlayEntry eventId={eventId} onSaved={onBetSaved} />
      <ResultsRoi eventId={eventId} refreshKey={refreshKey} />
    </div>
  );
}
