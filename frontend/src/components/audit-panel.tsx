import React, { useEffect, useState } from "react";

import { listAuditEvents } from "@/lib/api";
import {
  buildAuditEventTypeOptions,
  filterAuditEvents,
  formatDateTime,
  getAuditEventTone,
  getAuditEventTypeLabel,
  getAuditRecentWindowLabel,
  hasActiveAuditFilters,
  resetAuditFilterState,
  summarizeAuditEvent,
} from "@/lib/presentation";
import type { AuditFilterState, AuditRecentWindow } from "@/lib/presentation";
import type { AuditEventResponse } from "@/lib/types";

const AUDIT_EVENT_FETCH_LIMIT = 200;
const AUDIT_RECENT_WINDOWS: AuditRecentWindow[] = ["all", "24h", "7d", "30d"];

interface AuditPanelProps {
  tenantId: string | null;
  currentJobId: string | null;
}

function buildEmptyAuditCopy(
  totalEvents: number,
  tenantId: string | null,
  currentJobId: string | null,
): { title: string; detail: string } {
  if (totalEvents === 0) {
    return {
      title: "Ainda não há eventos registrados",
      detail: currentJobId
        ? `A empresa ${tenantId || "-"} ainda não registrou eventos para o lote aberto.`
        : `A empresa ${tenantId || "-"} ainda não registrou eventos operacionais visíveis.`,
    };
  }

  return {
    title: "Nenhum evento corresponde aos filtros",
    detail: "Ajuste o tipo, o período ou o lote informado para ampliar a consulta.",
  };
}

export function AuditPanel({ tenantId, currentJobId }: AuditPanelProps) {
  const [events, setEvents] = useState<AuditEventResponse[]>([]);
  const [filters, setFilters] = useState<AuditFilterState>(() => resetAuditFilterState());
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    setFilters(resetAuditFilterState());
    setIsExpanded(false);
  }, [tenantId, currentJobId]);

  useEffect(() => {
    if (!tenantId) {
      setEvents([]);
      setError(null);
      setIsLoading(false);
      return;
    }

    let isCancelled = false;

    async function loadAuditEvents() {
      setIsLoading(true);
      setError(null);
      try {
        const payload = await listAuditEvents({
          tenantId,
          limit: AUDIT_EVENT_FETCH_LIMIT,
        });
        if (!isCancelled) {
          setEvents(payload);
        }
      } catch (caughtError) {
        if (isCancelled) {
          return;
        }

        const message =
          caughtError instanceof Error
            ? caughtError.message
            : "Não foi possível carregar a trilha de auditoria.";
        setEvents([]);
        setError(message);
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadAuditEvents();
    return () => {
      isCancelled = true;
    };
  }, [tenantId, currentJobId, refreshToken]);

  const filteredEvents = filterAuditEvents(events, filters);
  const eventTypeOptions = buildAuditEventTypeOptions(events);
  const emptyStateCopy = buildEmptyAuditCopy(events.length, tenantId, currentJobId);

  return (
    <section className="panel audit-card" aria-label="Histórico da operação">
      <div className="audit-head">
        <div>
          <div className="panel-kicker">Apoio</div>
          <h2 className="panel-title">Histórico da operação</h2>
          <p className="panel-copy">
            Abra somente se precisar entender reprocessamentos, acessos ou outras ações do sistema.
            {currentJobId ? ` Lote aberto: ${currentJobId}.` : ""}
          </p>
        </div>

        <div className="audit-head-actions">
          <button
            className="action-button"
            type="button"
            aria-expanded={isExpanded}
            onClick={() => setIsExpanded((currentValue) => !currentValue)}
          >
            {isExpanded ? "Fechar histórico" : "Abrir histórico"}
          </button>
        </div>
      </div>

      {!isExpanded ? (
        <div className="audit-collapsed-note">
          <strong>Este painel é opcional.</strong>
          <p>O fluxo principal continua na conferência, na revisão das linhas e nos downloads do lote.</p>
        </div>
      ) : (
        <>
          <div className="audit-head-actions">
            {currentJobId ? (
              <button
                className="action-button"
                type="button"
                onClick={() =>
                  setFilters((currentFilters) => ({
                    ...currentFilters,
                    jobId: currentJobId,
                  }))
                }
              >
                Usar lote aberto
              </button>
            ) : null}
            <button
              className="action-button"
              type="button"
              onClick={() => setRefreshToken((currentValue) => currentValue + 1)}
              disabled={isLoading}
            >
              {isLoading ? "Atualizando..." : "Atualizar"}
            </button>
          </div>

          <div className="audit-filter-grid">
            <div className="field">
              <label htmlFor="audit-event-type">Tipo de evento</label>
              <select
                id="audit-event-type"
                value={filters.eventType}
                onChange={(event) =>
                  setFilters((currentFilters) => ({
                    ...currentFilters,
                    eventType: event.target.value,
                  }))
                }
              >
                <option value="all">Todos os eventos</option>
                {eventTypeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label} ({option.count})
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="audit-recent-window">Período</label>
              <select
                id="audit-recent-window"
                value={filters.recentWindow}
                onChange={(event) =>
                  setFilters((currentFilters) => ({
                    ...currentFilters,
                    recentWindow: event.target.value as AuditRecentWindow,
                  }))
                }
              >
                {AUDIT_RECENT_WINDOWS.map((recentWindow) => (
                  <option key={recentWindow} value={recentWindow}>
                    {getAuditRecentWindowLabel(recentWindow)}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="audit-job-filter">Lote</label>
              <input
                id="audit-job-filter"
                type="search"
                value={filters.jobId}
                placeholder={currentJobId ? `Ex.: ${currentJobId}` : "Ex.: lote-123"}
                onChange={(event) =>
                  setFilters((currentFilters) => ({
                    ...currentFilters,
                    jobId: event.target.value,
                  }))
                }
              />
            </div>
          </div>

          <div className="audit-filter-meta">
            <p>
              {filteredEvents.length} evento(s) exibido(s) de {events.length}. Empresa em foco:{" "}
              {tenantId || "-"}.
            </p>

            {hasActiveAuditFilters(filters) ? (
              <button
                className="action-button"
                type="button"
                onClick={() => setFilters(resetAuditFilterState())}
              >
                Limpar filtros
              </button>
            ) : null}
          </div>

          {error ? <p className="inline-error">{error}</p> : null}

          {isLoading ? <p className="audit-empty">Carregando trilha de auditoria...</p> : null}

          {!isLoading && !error && filteredEvents.length === 0 ? (
            <div className="audit-empty-card">
              <strong>{emptyStateCopy.title}</strong>
              <p>{emptyStateCopy.detail}</p>
            </div>
          ) : null}

          {!isLoading && !error && filteredEvents.length ? (
            <div className="audit-event-list">
              {filteredEvents.map((event) => (
                <article className="audit-event-card" key={event.event_id}>
                  <div className="audit-event-head">
                    <div className="audit-event-head-copy">
                      <span className={`status-chip ${getAuditEventTone(event.event_type)}`}>
                        {getAuditEventTypeLabel(event.event_type)}
                      </span>
                      <p className="audit-event-summary">{summarizeAuditEvent(event)}</p>
                    </div>

                    <time className="audit-event-time" dateTime={event.created_at}>
                      {formatDateTime(event.created_at)}
                    </time>
                  </div>

                  <dl className="audit-event-meta">
                    <div>
                      <dt>Empresa</dt>
                      <dd>{event.tenant_id}</dd>
                    </div>
                    <div>
                      <dt>Lote</dt>
                      <dd>{event.job_id || "-"}</dd>
                    </div>
                    <div>
                      <dt>Chave</dt>
                      <dd>{event.api_key_id || "-"}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
