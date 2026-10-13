import { CheckCircle2, Clock3, RefreshCw, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  getLatestHistoryMaintenanceRun,
  getLatestSyncRun,
  getLocalSyncState,
  getUpcomingHistoryCoverage,
  startDataSync,
} from "../services/syncService";
import { historyCoverageLabel, historyRunLabel } from "../utils/historyCoverage";
import { SUPPORTED_PROMOTIONS } from "../config/promotions";

const PROVIDERS = {
  ufc: "espn_ufc",
  dwcs: "espn_ufc",
  pfl: "espn_mma",
  one: "one_championship",
  bkfc: "bkfc",
  lfa: "lfa",
};

const COVERAGE = SUPPORTED_PROMOTIONS.map(({ key, label }) => ({
  promotion: label,
  key,
  provider: PROVIDERS[key],
}));

const PROMOTION_ALIASES = Object.fromEntries(
  SUPPORTED_PROMOTIONS.map(({ key, aliases }) => [key, aliases])
);

function issueMatchesPromotion(issue, promotionKey, cards = []) {
  const card = cards.find((row) => row.event_id === issue?.event_id);
  const promotion = String(issue?.promotion ?? card?.promotion ?? "").trim().toLowerCase();
  return (PROMOTION_ALIASES[promotionKey] ?? [promotionKey]).some((alias) =>
    promotion === alias || promotion.includes(alias)
  );
}

function issueTitle(issue) {
  if (issue.code === "ODDS_CARD_EMPTY") return "Odds missing";
  if (issue.code === "ODDS_CARD_PARTIAL") return "Odds incomplete";
  if (issue.code === "CARD_EMPTY") return "Fight card missing";
  if (issue.code === "MISSING_EVENT") return "Official event missing";
  if (issue.code === "CATALOG_UNAVAILABLE") return "Schedule check unavailable";
  if (issue.code === "CATALOG_IMPORT_FAILED") return "Official event needs review";
  if (issue.code === "HISTORY_UNCHECKED") return "History check queued";
  if (issue.code === "HISTORY_PARTIAL") return "Partial fighter history";
  if (issue.code === "HISTORY_UNAVAILABLE") return "Public history unavailable";
  if (issue.code === "HISTORY_REVIEW") return "Fighter identity review";
  return String(issue.code ?? "Data notice").replaceAll("_", " ");
}

function MissingMatchups({ issue }) {
  const matchups = Array.isArray(issue?.missing_matchups)
    ? issue.missing_matchups.filter((entry) => entry?.matchup)
    : [];
  if (!matchups.length) return null;

  return (
    <details className="missing-matchups-list">
      <summary>Show {matchups.length} uncovered matchup{matchups.length === 1 ? "" : "s"}</summary>
      <ul>
        {matchups.map((entry) => <li key={entry.fight_id}>{entry.matchup}</li>)}
      </ul>
    </details>
  );
}

function apiSportsSummary(providerRun) {
  if (!providerRun) return "API-Sports fallback has not reported yet.";
  if (providerRun.status === "skipped_missing_key") {
    return "API-Sports fallback did not run because no supported key name was found.";
  }
  if (providerRun.status === "skipped") return "API-Sports fallback was not run in this refresh.";
  if (providerRun.status === "failed") return "API-Sports fallback failed; review the provider warning above.";
  if (["completed", "completed_limited", "partial"].includes(providerRun.status)) {
    const deferred = (providerRun.dates_deferred_by_plan?.length ?? 0)
      + (providerRun.plan_limited_dates?.length ?? 0);
    return `API-Sports: ${providerRun.matched ?? 0} matched from ${providerRun.raw_rows ?? 0} returned rows · ${providerRun.requests ?? 0} requests${deferred ? ` · ${deferred} later date${deferred === 1 ? "" : "s"} deferred by the free plan` : ""}${providerRun.key_environment ? ` · key: ${providerRun.key_environment}` : ""}.`;
  }
  return "API-Sports fallback has not run yet.";
}

function fightOddsSummary(providerRun) {
  if (!providerRun) return "FightOdds fallback has not reported yet.";
  if (providerRun.status === "skipped") return "FightOdds fallback was not run in this refresh.";
  if (providerRun.status === "skipped_no_gaps") return "FightOdds fallback was not needed.";
  if (providerRun.status === "failed") return "FightOdds fallback failed; review the provider warning above.";
  if (["completed", "partial"].includes(providerRun.status)) {
    return `FightOdds fallback: ${providerRun.matched ?? 0} matched across ${providerRun.cards_matched ?? 0}/${providerRun.cards_targeted ?? 0} gap cards · ${providerRun.requests ?? 0} public pages.`;
  }
  return "FightOdds fallback has not run yet.";
}

function dynamicCoverage(summary, provider, promotionKey) {
  const requestedScope = summary?.requested_scope ?? "all";
  const sameUfcFamily = [requestedScope, promotionKey].every((key) =>
    ["ufc", "dwcs"].includes(key)
  );
  if (requestedScope !== "all" && requestedScope !== promotionKey && !sameUfcFamily) {
    return "Unchanged";
  }
  const status = provider === "espn_mma"
    ? summary?.provider_runs?.espn_mma?.status
    : summary?.provider_runs?.[provider]?.status;

  const matchingIssues = [...(summary?.quality_audit?.issues ?? []), ...(summary?.catalog_issues ?? []),
                          ...(summary?.publication_readiness?.disputes ?? [])].filter((issue) =>
    issueMatchesPromotion(issue, promotionKey, summary?.quality_audit?.cards)
  );

  if (matchingIssues.some((issue) => issue.code === "CARD_EMPTY")) return "Card gap";
  if (matchingIssues.some((issue) => ["CARD_IMPORT_REVIEW", "CARD_SOURCE_OMISSION", "CARD_SOURCE_EMPTY"].includes(issue.code))) return "Card gap";
  if (matchingIssues.some((issue) =>
    ["MISSING_EVENT", "CATALOG_UNAVAILABLE", "CATALOG_IMPORT_FAILED"].includes(issue.code)
  )) return "Catalog gap";
  if (matchingIssues.some((issue) =>
    ["ODDS_CARD_EMPTY", "ODDS_CARD_PARTIAL"].includes(issue.code)
  )) return "Odds gaps";

  if (status === "completed") {
    return "Automatic";
  }

  if (status === "failed" || status === "partial") {
    return "Review needed";
  }

  if (status === "skipped" || status === "not_run") return "Not run this refresh";
  return "Not reported";
}

function formatDateTime(value) {
  if (!value) {
    return "Never";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Chicago",
    timeZoneName: "short",
  }).format(new Date(value));
}

function statusLabel(status, qualityStatus) {
  if (status === "success") {
    return qualityStatus === "gaps_found" ? "Completed with gaps" : "Healthy";
  }

  if (status === "partial") {
    return "Review needed";
  }

  return status ? "Failed" : "Not run";
}

export default function DataSyncStatus({
  onSyncCompleted,
  compact = false,
  buttonOnly = false,
  promotionKey = "all",
}) {
  const [syncRun, setSyncRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadCount, setReloadCount] = useState(0);
  const [localSync, setLocalSync] = useState(null);
  const [historyRun, setHistoryRun] = useState(null);
  const [historyCoverage, setHistoryCoverage] = useState([]);
  const completedRunRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function loadSyncStatus() {
      try {
        setLoading(true);
        setError("");
        const [latestRun, latestHistoryRun, upcomingHistoryCoverage] = await Promise.all([
          getLatestSyncRun(),
          getLatestHistoryMaintenanceRun(),
          getUpcomingHistoryCoverage(),
        ]);

        if (!cancelled) {
          setSyncRun(latestRun);
          setHistoryRun(latestHistoryRun);
          setHistoryCoverage(upcomingHistoryCoverage);
        }
      } catch (loadError) {
        console.error("Sync status loading error:", loadError);

        if (!cancelled) {
          setError(
            "Run the latest included Supabase migration to enable refresh and history status."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadSyncStatus();
    return () => {
      cancelled = true;
    };
  }, [reloadCount]);

  useEffect(() => {
    let cancelled = false;
    let timer;

    async function checkLocalSync() {
      try {
        const state = await getLocalSyncState();
        if (cancelled) return;
        setLocalSync(state);

        if (state.running) {
          timer = window.setTimeout(checkLocalSync, 3000);
          return;
        }

        if (state.finishedAt) {
          setReloadCount((count) => count + 1);
          if (completedRunRef.current !== state.finishedAt) {
            completedRunRef.current = state.finishedAt;
            onSyncCompleted?.();
          }
        }
      } catch (statusError) {
        if (!cancelled) {
          setError(statusError.message ?? "Could not check the local sync process.");
        }
      }
    }

    checkLocalSync();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [localSync?.startedAt, onSyncCompleted]);

  async function handleRefresh() {
    try {
      setError("");
      const state = await startDataSync(compact && promotionKey !== "all" ? promotionKey : "all");
      setLocalSync(state);
    } catch (refreshError) {
      setError(refreshError.message ?? "Could not start the data refresh.");
    }
  }

  const status = localSync?.running ? "running" : syncRun?.status;
  const providerErrors = Array.isArray(syncRun?.summary?.errors)
    ? syncRun.summary.errors
    : [];
  const providerWarnings = Array.isArray(syncRun?.summary?.warnings)
    ? syncRun.summary.warnings
    : [];
  const qualityAudit = syncRun?.summary?.quality_audit ?? {};
  const qualityIssues = [...new Map([...(Array.isArray(qualityAudit.issues) ? qualityAudit.issues : []),
    ...(syncRun?.summary?.publication_readiness?.disputes ?? [])].map(issue =>
      [`${issue.code}:${issue.event_id ?? issue.event_name ?? ""}:${JSON.stringify(issue.fight_ids ?? [])}`, issue])).values()];
  const hasQualityGaps = qualityAudit.status === "gaps_found";
  const apiSportsRun = syncRun?.summary?.provider_runs?.api_sports_mma;
  const fightOddsRun = syncRun?.summary?.provider_runs?.fightodds;
  const displayStatus = status === "success" && hasQualityGaps ? "partial" : status;
  const StatusIcon = displayStatus === "success"
    ? CheckCircle2
    : displayStatus === "partial" || displayStatus === "failed"
      ? TriangleAlert
      : Clock3;

  if (buttonOnly) {
    return (
      <button
        type="button"
        className="promotion-refresh-button"
        disabled={loading || localSync?.running}
        onClick={handleRefresh}
        title="Refresh this promotion's schedule, current card, results and odds"
      >
        <RefreshCw className={loading || localSync?.running ? "spin" : ""} size={14} />
        {localSync?.running
          ? "Refreshing…"
          : `Refresh ${promotionKey === "all" ? "all data" : promotionKey.toUpperCase()}`}
      </button>
    );
  }

  if (compact) {
    return (
      <div className="fightcenter-sync">
        <div className="fightcenter-sync-main">
          <span className={`fightcenter-sync-state fightcenter-sync-state-${displayStatus ?? "unknown"}`}>
            <StatusIcon className={localSync?.running ? "spin" : ""} size={16} />
            <span>
              <small>Data refresh</small>
              <strong>
                {localSync?.running
                  ? localSync.stageLabel ?? "Refreshing…"
                  : loading
                    ? "Checking…"
                    : statusLabel(status, qualityAudit.status)}
              </strong>
            </span>
          </span>
          <button
            type="button"
            className="sync-refresh-button sync-refresh-button-compact"
            disabled={loading || localSync?.running}
            onClick={handleRefresh}
          >
            <RefreshCw className={loading || localSync?.running ? "spin" : ""} size={14} />
            {localSync?.running
              ? "Running"
              : promotionKey === "all"
                ? "Refresh all"
                : `Refresh ${promotionKey.toUpperCase()} + odds`}
          </button>
        </div>
        <details className="fightcenter-sync-details">
          <summary>
            {formatDateTime(syncRun?.finished_at)} · {syncRun?.events_processed ?? "—"} cards · {syncRun?.fights_processed ?? "—"} fights
          </summary>
          {error ? <p className="sync-status-error">{error}</p> : null}
          {!localSync?.running && localSync?.error ? (
            <p className="sync-status-error">
              {syncRun?.status === "partial"
                ? "Refresh finished with issues. Successful provider data remains saved."
                : `Refresh failed: ${localSync.error}`}
            </p>
          ) : null}
          <div className="sync-coverage-list sync-coverage-list-compact">
            {COVERAGE.map(({ promotion, key, provider }) => {
              const displayedCoverage = dynamicCoverage(syncRun?.summary, provider, key);
              return (
                <span className={displayedCoverage === "Automatic" ? "coverage-live" : ["Odds gaps", "Card gap", "Catalog gap"].includes(displayedCoverage) ? "coverage-gap" : ""} key={promotion}>
                  <strong>{promotion}</strong><small>{displayedCoverage}</small>
                </span>
              );
            })}
          </div>
          {providerErrors.length ? (
            <div className="sync-inline-errors" role="status">
              <strong>What needs review</strong>
              {providerErrors.map((providerError, index) => (
                <article key={`${providerError.stage}-${index}`}>
                  <span>{String(providerError.stage ?? "provider").replaceAll("_", " ")}</span>
                  <p>{providerError.message}</p>
                  {providerError.context ? <small>{providerError.context}</small> : null}
                </article>
              ))}
            </div>
          ) : null}
          {qualityIssues.length || providerWarnings.length ? (
            <div className="sync-inline-errors sync-coverage-gaps" role="status">
              <strong>Automatic data coverage checks</strong>
              {qualityIssues.map((issue, index) => (
                <article key={`${issue.code}-${issue.event_id ?? index}`}>
                  <span>{issueTitle(issue)}{issue.promotion ? ` · ${issue.promotion}` : ""}</span>
                  <p>{issue.message}</p>
                  {issue.event_name ? <small>{issue.event_name}</small> : null}
                  <MissingMatchups issue={issue} />
                </article>
              ))}
              {providerWarnings.map((warning, index) => (
                <article key={`${warning.stage}-${index}`}>
                  <span>{String(warning.stage).replaceAll("_", " ")}</span>
                  <p>{warning.message}</p>
                </article>
              ))}
            </div>
          ) : null}
          <div className="history-maintenance-summary">
            <strong>Fighter history · {historyRunLabel(historyRun)}</strong>
            <small>
              {historyRun
                ? `${historyRun.fighters_checked} upcoming fighters checked · ${formatDateTime(historyRun.finished_at)}`
                : "The weekly automatic history check has not run yet."}
            </small>
          </div>
          {historyCoverage.length ? (
            <div className="sync-inline-errors history-coverage-review" role="status">
              <strong>History notes for upcoming cards</strong>
              {historyCoverage.map((entry) => (
                <article key={entry.fighter_id}>
                  <span>{entry.fighter?.full_name ?? "Unknown fighter"} · {entry.promotion_name ?? "Promotion"}</span>
                  <p>{historyCoverageLabel(entry)}</p>
                  <small>{entry.coverage_note}</small>
                </article>
              ))}
            </div>
          ) : null}
          <p className="fightcenter-sync-note">
            Odds: {qualityAudit.odds
              ? `${qualityAudit.odds.covered_fights}/${qualityAudit.odds.expected_fights} fights covered inside ${qualityAudit.odds.expectation_window_days ?? 4} days`
              : syncRun?.odds_status?.replaceAll("_", " ") ?? "—"}.
            {` ${apiSportsSummary(apiSportsRun)}`}
            {` ${fightOddsSummary(fightOddsRun)}`}
            {" "}Fighter-history recovery and completed-fight enrichment run during Sunday maintenance.
          </p>
        </details>
      </div>
    );
  }

  return (
    <section className="card sync-status-panel">
      <div className="sync-status-main">
        <div className="sync-status-title">
          <StatusIcon size={18} />
          <span>
            <small>Automatic data refresh</small>
            <strong>
              {localSync?.running
                ? localSync.stageLabel ?? "Refreshing…"
                : loading
                  ? "Checking…"
                  : statusLabel(status, qualityAudit.status)}
            </strong>
          </span>
        </div>

        <div className="sync-status-metrics">
          <span>
            <small>Last run</small>
            <strong>
              {localSync?.running
                ? `Started ${formatDateTime(localSync.startedAt)}`
                : formatDateTime(syncRun?.finished_at)}
            </strong>
          </span>
          <span>
            <small>Cards / fights</small>
            <strong>
              {syncRun
                ? `${syncRun.events_processed} / ${syncRun.fights_processed}`
                : "—"}
            </strong>
          </span>
          <span>
            <small>Official results</small>
            <strong>{syncRun?.results_processed ?? "—"}</strong>
          </span>
          <span>
            <small>Odds</small>
            <strong>{syncRun?.odds_status?.replaceAll("_", " ") ?? "—"}</strong>
          </span>
        </div>

        <button
          type="button"
          className="sync-refresh-button"
          disabled={loading || localSync?.running}
          onClick={handleRefresh}
        >
          <RefreshCw className={loading || localSync?.running ? "spin" : ""} size={15} />
          {localSync?.running ? "Refreshing…" : "Run data refresh"}
        </button>
      </div>

      {error && <p className="sync-status-error">{error}</p>}
      {!localSync?.running && localSync?.error ? (
        <p className="sync-status-error">
          {syncRun?.status === "partial"
            ? "Refresh finished with issues. Review the provider marked above."
            : `Refresh failed: ${localSync.error}`}
        </p>
      ) : null}

      <div className="sync-coverage-list" aria-label="Automatic provider coverage">
        {COVERAGE.map(({ promotion, key, coverage, provider }) => {
          const displayedCoverage = provider
            ? dynamicCoverage(syncRun?.summary, provider, key)
            : coverage;

          return (
          <span
            className={displayedCoverage === "Automatic" ? "coverage-live" : ["Odds gaps", "Card gap", "Catalog gap"].includes(displayedCoverage) ? "coverage-gap" : ""}
            key={promotion}
          >
            <strong>{promotion}</strong>
            <small>{displayedCoverage}</small>
          </span>
          );
        })}
      </div>

      <details className="sync-full-details" open={Boolean(providerErrors.length)}>
        <summary>
          Coverage details
          <span>{providerErrors.length + qualityIssues.length + providerWarnings.length} notices</span>
        </summary>

        {providerErrors.length ? (
          <div className="sync-inline-errors" role="status">
            <strong>What needs review</strong>
            {providerErrors.map((providerError, index) => (
              <article key={`${providerError.stage}-${index}`}>
                <span>{String(providerError.stage ?? "provider").replaceAll("_", " ")}</span>
                <p>{providerError.message}</p>
                {providerError.context ? <small>{providerError.context}</small> : null}
              </article>
            ))}
          </div>
        ) : null}

        {qualityIssues.length || providerWarnings.length ? (
          <div className="sync-inline-errors sync-coverage-gaps" role="status">
            <strong>Automatic coverage checks</strong>
            {qualityIssues.map((issue, index) => (
              <article key={`${issue.code}-${issue.event_id ?? index}`}>
                <span>{issueTitle(issue)}{issue.promotion ? ` · ${issue.promotion}` : ""}</span>
                <p>{issue.message}</p>
                {issue.event_name ? <small>{issue.event_name}</small> : null}
                <MissingMatchups issue={issue} />
              </article>
            ))}
            {providerWarnings.map((warning, index) => (
              <article key={`${warning.stage}-${index}`}>
                <span>{String(warning.stage).replaceAll("_", " ")}</span>
                <p>{warning.message}</p>
              </article>
            ))}
          </div>
        ) : (
          <p className="data-health-clear"><CheckCircle2 size={16} /> No automatic coverage exceptions were recorded.</p>
        )}

        <div className="history-maintenance-summary">
          <strong>Fighter history · {historyRunLabel(historyRun)}</strong>
          <small>
            {historyRun
              ? `${historyRun.fighters_checked} upcoming fighters checked · ${formatDateTime(historyRun.finished_at)}`
              : "The weekly automatic history check has not run yet."}
          </small>
        </div>
        {historyCoverage.length ? (
          <div className="sync-inline-errors history-coverage-review" role="status">
            <strong>History notes for upcoming cards</strong>
            {historyCoverage.map((entry) => (
              <article key={entry.fighter_id}>
                <span>{entry.fighter?.full_name ?? "Unknown fighter"} · {entry.promotion_name ?? "Promotion"}</span>
                <p>{historyCoverageLabel(entry)}</p>
                <small>{entry.coverage_note}</small>
              </article>
            ))}
          </div>
        ) : null}

        <p className="fightcenter-sync-note">
          Odds: {qualityAudit.odds
            ? `${qualityAudit.odds.covered_fights}/${qualityAudit.odds.expected_fights} fights covered inside ${qualityAudit.odds.expectation_window_days ?? 4} days`
            : syncRun?.odds_status?.replaceAll("_", " ") ?? "—"}.
          {` ${apiSportsSummary(apiSportsRun)}`}
          {` ${fightOddsSummary(fightOddsRun)}`}
        </p>
      </details>
    </section>
  );
}
