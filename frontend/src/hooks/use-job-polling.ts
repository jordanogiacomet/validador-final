"use client";

import { useEffect, useRef } from "react";

import { getJob } from "@/lib/api";
import { isJobTerminal } from "@/lib/presentation";
import type { JobStatusResponse } from "@/lib/types";

interface UseJobPollingOptions {
  jobId: string | null;
  enabled?: boolean;
  intervalMs?: number;
  onJobUpdate: (job: JobStatusResponse) => void;
  onError?: (message: string) => void;
}

export function useJobPolling({
  jobId,
  enabled = true,
  intervalMs = 1000,
  onJobUpdate,
  onError,
}: UseJobPollingOptions) {
  const onJobUpdateRef = useRef(onJobUpdate);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onJobUpdateRef.current = onJobUpdate;
  }, [onJobUpdate]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    if (!jobId || !enabled) {
      return;
    }

    const targetJobId = jobId;
    let isCancelled = false;
    let timer: number | null = null;

    async function pollJob() {
      try {
        const nextJob = await getJob(targetJobId);
        if (isCancelled) {
          return;
        }

        onJobUpdateRef.current(nextJob);
        if (isJobTerminal(nextJob) && timer !== null) {
          window.clearInterval(timer);
          timer = null;
        }
      } catch (caughtError) {
        if (isCancelled) {
          return;
        }

        const message =
          caughtError instanceof Error
            ? caughtError.message
            : "Falha ao consultar o lote.";
        onErrorRef.current?.(message);
      }
    }

    void pollJob();
    timer = window.setInterval(() => {
      void pollJob();
    }, intervalMs);

    return () => {
      isCancelled = true;
      if (timer !== null) {
        window.clearInterval(timer);
      }
    };
  }, [enabled, intervalMs, jobId]);
}
