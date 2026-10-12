import { useCallback, useState } from "react";

import AppHeader from "./components/AppHeader";
import AuthGate from "./components/AuthGate";
import BetCenter from "./components/BetCenter";
import CardAssistantAnalysis from "./components/CardAssistantAnalysis";
import DataHealthDrawer from "./components/DataHealthDrawer";
import EventSelector from "./components/EventSelector";
import FightCenterConsole from "./components/FightCenterConsole";
import PromotionList from "./components/PromotionList";
import { ALL_PROMOTIONS_KEY } from "./config/promotions";

function Dashboard() {
  const [activeView, setActiveView] = useState("cards");
  const [selectedPromotionKey, setSelectedPromotionKey] = useState(
    ALL_PROMOTIONS_KEY
  );
  const [selectedEventId, setSelectedEventId] = useState(null);
  const [selectedFight, setSelectedFight] = useState(null);
  const [resultsRefreshKey, setResultsRefreshKey] = useState(0);
  const [workspaceRefreshKey, setWorkspaceRefreshKey] = useState(0);
  const [dataRefreshKey, setDataRefreshKey] = useState(0);
  const [cardResearchOpen, setCardResearchOpen] = useState(false);
  const [dataHealthOpen, setDataHealthOpen] = useState(false);

  const handleSelectEvent = useCallback((eventId) => {
    setSelectedEventId(eventId);
    setSelectedFight(null);
    setCardResearchOpen(false);
  }, []);

  const handleSelectPromotion = useCallback((promotionKey) => {
    setSelectedPromotionKey(promotionKey);
    setSelectedEventId(null);
    setSelectedFight(null);
  }, []);

  const handleDataSyncCompleted = useCallback(() => {
    setDataRefreshKey((current) => current + 1);
    setSelectedFight(null);
  }, []);

  return (
    <main className="dashboard-shell app-shell-v11">
      <AppHeader
        activeView={activeView}
        onChangeView={setActiveView}
        onOpenDataHealth={() => setDataHealthOpen(true)}
      />

      {activeView === "cards" ? (
        <div className="cards-view">
          <section className="cards-browser-shell">
            <PromotionList
              selectedPromotionKey={selectedPromotionKey}
              onSelectPromotion={handleSelectPromotion}
            />
            <EventSelector
              selectedPromotionKey={selectedPromotionKey}
              selectedEventId={selectedEventId}
              onSelectEvent={handleSelectEvent}
              refreshKey={dataRefreshKey}
            />
          </section>

          <FightCenterConsole
            eventId={selectedEventId}
            selectedFight={selectedFight}
            onSelectFight={setSelectedFight}
            dataRefreshKey={dataRefreshKey}
            resultsRefreshKey={resultsRefreshKey}
            workspaceRefreshKey={workspaceRefreshKey}
            onDataSyncCompleted={handleDataSyncCompleted}
            onResearchSaved={() =>
              setResultsRefreshKey((current) => current + 1)
            }
            onOpenCardResearch={() => setCardResearchOpen(true)}
          />
        </div>
      ) : (
        <BetCenter
          eventId={selectedEventId}
          onSelectEvent={handleSelectEvent}
          refreshKey={resultsRefreshKey + dataRefreshKey}
          onBetSaved={() => setResultsRefreshKey((current) => current + 1)}
        />
      )}

      <CardAssistantAnalysis
        eventId={selectedEventId}
        open={cardResearchOpen}
        onClose={() => setCardResearchOpen(false)}
        onAnalysisSaved={() =>
          setWorkspaceRefreshKey((current) => current + 1)
        }
      />

      <DataHealthDrawer
        open={dataHealthOpen}
        onClose={() => setDataHealthOpen(false)}
        onSyncCompleted={handleDataSyncCompleted}
      />
    </main>
  );
}

export default function App() {
  return (
    <AuthGate>
      <Dashboard />
    </AuthGate>
  );
}
