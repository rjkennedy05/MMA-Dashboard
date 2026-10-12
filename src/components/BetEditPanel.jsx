import { Save, Trash2, X } from "lucide-react";
import { useState } from "react";

import { BET_SPORTSBOOKS } from "../config/sportsbooks";
import {
  deleteTrackedBet,
  updateTrackedBet,
} from "../services/resultsService";
import { userFacingDataError } from "../utils/dataError";

const RESULT_OPTIONS = [
  ["pending", "Pending"],
  ["win", "Win"],
  ["loss", "Loss"],
  ["push", "Push"],
  ["void", "Void"],
];

function sideName(fight, side) {
  return side === "fighter_a"
    ? fight?.fighter_a?.full_name ?? "Fighter A"
    : fight?.fighter_b?.full_name ?? "Fighter B";
}

function initialDraft(bet) {
  return {
    bet_side: bet.bet_side ?? "fighter_a",
    bet_sportsbook: bet.bet_sportsbook ?? "",
    bet_price: bet.bet_price ?? "",
    stake_units: bet.stake_units ?? "",
    settlement_status: bet.settlement_status ?? "pending",
    ticket_label: bet.ticket_label ?? "",
    legs: (bet.legs ?? []).map((leg) => ({
      leg_id: leg.leg_id,
      bet_side: leg.bet_side,
      leg_price: leg.leg_price,
    })),
  };
}

export default function BetEditPanel({ bet, onClose, onChanged }) {
  const [draft, setDraft] = useState(() => initialDraft(bet));
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");

  function updateField(field, value) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  function updateLeg(legId, field, value) {
    setDraft((current) => ({
      ...current,
      legs: current.legs.map((leg) => (
        leg.leg_id === legId ? { ...leg, [field]: value } : leg
      )),
    }));
  }

  async function handleSave() {
    try {
      setBusyAction("save");
      setError("");
      await updateTrackedBet(bet, draft);
      onChanged?.();
      onClose?.();
    } catch (saveError) {
      setError(userFacingDataError(saveError, "Could not update this ticket."));
    } finally {
      setBusyAction("");
    }
  }

  async function handleDelete() {
    const confirmed = window.confirm(
      "Permanently remove this ticket from Bet History? Research and fight data will remain."
    );
    if (!confirmed) return;

    try {
      setBusyAction("delete");
      setError("");
      await deleteTrackedBet(bet);
      onChanged?.();
      onClose?.();
    } catch (deleteError) {
      setError(userFacingDataError(deleteError, "Could not delete this ticket."));
    } finally {
      setBusyAction("");
    }
  }

  return (
    <section className="bet-edit-panel">
      <header>
        <div>
          <p className="eyebrow">Edit saved ticket</p>
          <h4>{bet.selection_name ?? "Saved bet"}</h4>
        </div>
        <button type="button" className="bet-edit-close" onClick={onClose}>
          <X size={16} /> Close
        </button>
      </header>

      {bet.ticket_type === "parlay" ? (
        <>
          <label className="bet-edit-field bet-edit-label-field">
            <span>Ticket label</span>
            <input
              type="text"
              value={draft.ticket_label}
              onChange={(event) => updateField("ticket_label", event.target.value)}
            />
          </label>
          <div className="bet-edit-legs">
            {(bet.legs ?? []).map((leg) => {
              const legDraft = draft.legs.find((item) => item.leg_id === leg.leg_id);
              return (
                <article key={leg.leg_id}>
                  <small>{leg.event_name}</small>
                  <div className="bet-edit-side-buttons">
                    {["fighter_a", "fighter_b"].map((side) => (
                      <button
                        type="button"
                        key={side}
                        className={legDraft?.bet_side === side ? "active" : ""}
                        onClick={() => updateLeg(leg.leg_id, "bet_side", side)}
                      >
                        {sideName(leg, side)}
                      </button>
                    ))}
                  </div>
                  <label>
                    <span>Leg odds</span>
                    <input
                      type="number"
                      value={legDraft?.leg_price ?? ""}
                      onChange={(event) => updateLeg(leg.leg_id, "leg_price", event.target.value)}
                    />
                  </label>
                </article>
              );
            })}
          </div>
        </>
      ) : (
        <fieldset className="bet-edit-side-control">
          <legend>Selection</legend>
          <div className="bet-edit-side-buttons">
            {["fighter_a", "fighter_b"].map((side) => (
              <button
                type="button"
                key={side}
                className={draft.bet_side === side ? "active" : ""}
                onClick={() => updateField("bet_side", side)}
              >
                {sideName(bet, side)}
              </button>
            ))}
          </div>
        </fieldset>
      )}

      <fieldset className="sportsbook-choice-control bet-edit-book-control">
        <legend>Sportsbook</legend>
        <div>
          {BET_SPORTSBOOKS.map((sportsbook) => (
            <button
              type="button"
              key={sportsbook}
              className={draft.bet_sportsbook === sportsbook ? "active" : ""}
              onClick={() => updateField("bet_sportsbook", sportsbook)}
            >
              {sportsbook}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="bet-edit-fields">
        <label className="bet-edit-field">
          <span>Sportsbook override</span>
          <input
            type="text"
            placeholder="Other book"
            value={draft.bet_sportsbook}
            onChange={(event) => updateField("bet_sportsbook", event.target.value)}
          />
        </label>
        <label className="bet-edit-field">
          <span>{bet.ticket_type === "parlay" ? "Combined odds" : "Odds taken"}</span>
          <input
            type="number"
            value={draft.bet_price}
            onChange={(event) => updateField("bet_price", event.target.value)}
          />
        </label>
        <label className="bet-edit-field">
          <span>Stake (units)</span>
          <input
            type="number"
            min="0"
            step="0.1"
            value={draft.stake_units}
            onChange={(event) => updateField("stake_units", event.target.value)}
          />
        </label>
        <label className="bet-edit-field">
          <span>Result</span>
          <select
            value={draft.settlement_status}
            onChange={(event) => updateField("settlement_status", event.target.value)}
          >
            {RESULT_OPTIONS.map(([value, label]) => (
              <option value={value} key={value}>{label}</option>
            ))}
          </select>
        </label>
      </div>

      {error ? <p className="results-error">{error}</p> : null}

      <footer>
        <button
          type="button"
          className="delete-bet-button"
          disabled={Boolean(busyAction)}
          onClick={handleDelete}
        >
          <Trash2 size={15} />
          {busyAction === "delete" ? "Deleting…" : "Delete ticket"}
        </button>
        <button
          type="button"
          className="save-bet-edit-button"
          disabled={Boolean(busyAction)}
          onClick={handleSave}
        >
          <Save size={15} />
          {busyAction === "save" ? "Saving…" : "Save changes"}
        </button>
      </footer>
    </section>
  );
}
