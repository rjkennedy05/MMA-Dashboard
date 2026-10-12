import { Check, Clipboard, LoaderCircle, Save, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  getEventResearch,
  saveEventAnalysis,
} from "../services/eventResearchService";
import { getFightsByEvent } from "../services/fightService";
import { getLatestMoneylinesForFights } from "../services/oddsService";
import {
  getFightResearchForFights,
  saveAssistantMatchupFacts,
} from "../services/researchService";
import { inspectAssistantMatchupFacts } from "../utils/assistantMatchupFacts";
import { buildCardAnalysisPrompt } from "../utils/cardAnalysisPrompt";
import { getCappingDiagnostics } from "../services/resultsService";
import { getCardFighterHistories } from "../services/fighterHistoryService";

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const temporaryField = document.createElement("textarea");
  temporaryField.value = text;
  temporaryField.setAttribute("readonly", "");
  temporaryField.style.position = "fixed";
  temporaryField.style.opacity = "0";
  document.body.appendChild(temporaryField);
  temporaryField.select();
  const copied = document.execCommand("copy");
  temporaryField.remove();

  if (!copied) {
    throw new Error("Your browser blocked clipboard access.");
  }
}

export default function CardAssistantAnalysis({ eventId, open, onClose, onAnalysisSaved }) {
  const [analysis, setAnalysis] = useState("");
  const [loading, setLoading] = useState(false);
  const [copying, setCopying] = useState(false);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveSummary, setSaveSummary] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadCardAnalysis() {
      if (!eventId) {
        setAnalysis("");
        setError("");
        return;
      }

      try {
        setLoading(true);
        setError("");
        setCopied(false);
        setSaved(false);
        setSaveSummary(null);
        const eventResearch = await getEventResearch(eventId);

        if (!cancelled) {
          setAnalysis(eventResearch?.assistant_card_analysis ?? "");
        }
      } catch (loadError) {
        console.error("Card analysis loading error:", loadError);

        if (!cancelled) {
          setAnalysis("");
          setError(
            loadError.message ?? "Could not load the saved card analysis."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadCardAnalysis();

    return () => {
      cancelled = true;
    };
  }, [eventId]);

  useEffect(() => {
    if (!open) return undefined;
    function closeOnEscape(event) {
      if (event.key === "Escape") onClose?.();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  async function handleCopyPrompt() {
    try {
      setCopying(true);
      setCopied(false);
      setError("");

      const fights = await getFightsByEvent(eventId);
      const fightIds = fights.map((fight) => fight.fight_id);
      const diagnosticsPromise = getCappingDiagnostics().catch((diagnosticsError) => {
        console.warn("Background capping diagnostics unavailable:", diagnosticsError);
        return null;
      });
      const [oddsByFight, researchByFight, performanceDiagnostics, historiesByFighter] = await Promise.all([
        getLatestMoneylinesForFights(fightIds),
        getFightResearchForFights(fightIds),
        diagnosticsPromise,
        getCardFighterHistories(fights),
      ]);
      const prompt = buildCardAnalysisPrompt({
        fights,
        oddsByFight,
        researchByFight,
        performanceDiagnostics,
        historiesByFighter,
      });

      await copyText(prompt);
      setCopied(true);
    } catch (copyError) {
      console.error("Card prompt copying error:", copyError);
      setError(copyError.message ?? "Could not copy the full-card prompt.");
    } finally {
      setCopying(false);
    }
  }

  async function handleSave() {
    try {
      setSaving(true);
      setSaved(false);
      setSaveSummary(null);
      setError("");
      const fights = await getFightsByEvent(eventId);
      const inspection = inspectAssistantMatchupFacts(analysis, fights);
      const eventResearch = await saveEventAnalysis(eventId, analysis);
      const savedFacts = await saveAssistantMatchupFacts(inspection.updates);
      setAnalysis(eventResearch.assistant_card_analysis ?? "");
      setSaveSummary({
        updated: savedFacts.length,
        total: fights.length,
        unmatchedFights: inspection.unmatchedFights,
        sectionCount: inspection.sectionCount,
        factBlockCount: inspection.factBlockCount,
        matchStrategy: inspection.matchStrategy,
      });
      setSaved(true);
      onAnalysisSaved?.();
    } catch (saveError) {
      console.error("Card analysis saving error:", saveError);
      setError(saveError.message ?? "Could not save the card analysis.");
    } finally {
      setSaving(false);
    }
  }

  if (!eventId || !open) {
    return null;
  }

  return (
    <div className="card-research-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose?.();
    }}>
    <section className="card-research-drawer" role="dialog" aria-modal="true" aria-labelledby="card-research-title">
      <div className="section-heading card-assistant-heading">
        <div>
          <p className="eyebrow">Guided card workflow</p>
          <h2 id="card-research-title"><Sparkles size={18} /> Card research</h2>
        </div>
        <button type="button" className="card-research-close" aria-label="Close card research" onClick={onClose}>
          <X size={18} />
        </button>
      </div>

      <ol className="card-research-steps">
        <li className={copied ? "complete" : "active"}><span>1</span><strong>Copy prompt</strong><small>Builds the full event request</small></li>
        <li className={copied && !saved ? "active" : ""}><span>2</span><strong>Run in ChatGPT</strong><small>Paste the complete response below</small></li>
        <li className={saved ? "complete" : ""}><span>3</span><strong>Import card</strong><small>Applies analysis to every matchup</small></li>
      </ol>

      <button
        type="button"
        className="generate-analysis-button card-research-copy"
        disabled={copying || loading}
        onClick={handleCopyPrompt}
      >
        {copying ? <LoaderCircle className="spin" size={15} /> : copied ? <Check size={15} /> : <Clipboard size={15} />}
        {copying ? "Building prompt…" : copied ? "Prompt copied" : "Copy full-card prompt"}
      </button>

      {error ? <p className="assistant-generation-error">{error}</p> : null}
      {copied ? (
        <p className="assistant-generation-success">
          Full-card prompt copied. Paste it into ChatGPT, then bring the completed analysis back to the field below.
        </p>
      ) : null}

      <label className="notes-field notes-field-wide card-analysis-field">
        <span>Full-card assistant analysis</span>
        <textarea
          rows="16"
          disabled={loading}
          placeholder="Paste the complete ChatGPT card analysis here…"
          value={analysis}
          onChange={(event) => {
            setAnalysis(event.target.value);
            setSaved(false);
            setSaveSummary(null);
          }}
        />
      </label>

      <div className="card-analysis-actions">
        <small>
          {saved && saveSummary
            ? `Analysis saved · ${saveSummary.updated} of ${saveSummary.total} fights updated`
            : "The analysis saves once for the event; structured facts also update matching fights."}
        </small>
        <button
          type="button"
          className="save-card-analysis-button"
          disabled={saving || loading}
          onClick={handleSave}
        >
          {saved ? <Check size={16} /> : <Save size={16} />}
          {saving ? "Saving…" : saved ? "Card analysis saved" : "Save card analysis"}
        </button>
      </div>

      {saved && saveSummary ? (
        <div
          className={
            saveSummary.updated === saveSummary.total
              ? "assistant-generation-success card-analysis-save-result"
              : "assistant-generation-warning card-analysis-save-result"
          }
          role="status"
        >
          <strong>
            Analysis saved. Dashboard facts updated for {saveSummary.updated} of {saveSummary.total} fights.
          </strong>
          {saveSummary.updated === 0 ? (
            <span>
              {saveSummary.factBlockCount > 0
                ? `${saveSummary.factBlockCount} Dashboard facts block${saveSummary.factBlockCount === 1 ? " was" : "s were"} found, but they could not be matched safely to this card.`
                : "No Dashboard facts blocks were found in the pasted response. Copy a fresh prompt from this version and keep its Dashboard facts lines in the response."}
            </span>
          ) : saveSummary.updated < saveSummary.total ? (
            <span>
              Not updated: {saveSummary.unmatchedFights
                .slice(0, 4)
                .map((fight) => `${fight.fighter_a?.full_name} vs ${fight.fighter_b?.full_name}`)
                .join(", ")}
              {saveSummary.unmatchedFights.length > 4
                ? `, plus ${saveSummary.unmatchedFights.length - 4} more`
                : ""}.
            </span>
          ) : (
            <span>Select a matchup to view the refreshed style and finish data above Outside Opinions.</span>
          )}
        </div>
      ) : null}
    </section>
    </div>
  );
}
