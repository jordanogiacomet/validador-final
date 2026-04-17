import { describeJobProgress, formatDateTime, formatStatusChip, getValidationScopeLabel } from "@/lib/presentation";
import type { JobListItemResponse } from "@/lib/types";

interface ActiveJobsPanelProps {
  jobs: JobListItemResponse[];
  isLoading: boolean;
  error: string | null;
  onOpenJob: (jobId: string) => void;
  onCancelJob: (jobId: string) => void;
}

export function ActiveJobsPanel({
  jobs,
  isLoading,
  error,
  onOpenJob,
  onCancelJob,
}: ActiveJobsPanelProps) {
  return (
    <section className="panel control-card jobs-card">
      <div className="panel-kicker">Fila</div>
      <h2 className="panel-title">Lotes em andamento</h2>

      <div className="job-list">
        {isLoading && !jobs.length ? (
          <p className="job-empty">Carregando lotes...</p>
        ) : null}

        {!isLoading && !jobs.length ? (
          <p className="job-empty">Nenhum lote em processamento.</p>
        ) : null}

        {error ? <p className="inline-error">{error}</p> : null}

        {jobs.map((job) => {
          const chip = formatStatusChip(job);
          const canCancel =
            (job.status === "queued" || job.status === "running") && !job.cancel_requested;

          return (
            <article className="job-item" key={job.job_id}>
              <div className="job-item-head">
                <div>
                  <strong>{job.file_name || "Arquivo não identificado"}</strong>
                  <small>
                    {job.tenant_id} • {getValidationScopeLabel(job.validation_scope)}
                  </small>
                </div>
                <span className={`status-chip ${chip.kind}`}>{chip.label}</span>
              </div>

              <div className="job-item-meta">
                <span>
                  <b>Job:</b> {job.job_id}
                </span>
                <span>
                  <b>Atualizado:</b> {formatDateTime(job.updated_at)}
                </span>
                <span>
                  <b>Etapa:</b> {job.status_title || "Processamento em andamento"}
                </span>
                <span>{describeJobProgress(job)}</span>
              </div>

              <div className="job-item-actions">
                <button className="action-button" type="button" onClick={() => onOpenJob(job.job_id)}>
                  Acompanhar
                </button>
                <button
                  className={`action-button ${canCancel ? "" : "primary"}`.trim()}
                  type="button"
                  disabled={!canCancel}
                  onClick={() => onCancelJob(job.job_id)}
                >
                  {job.cancel_requested ? "Cancelando..." : "Cancelar"}
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
