"use client";

import { useEffect, useRef } from "react";

import { getJob } from "@/lib/api";
import { isJobTerminal } from "@/lib/presentation";
import type { JobStatusResponse } from "@/lib/types";

interface UseJobPollingOptions {
  jobId: string | null;
  enabled?: boolean;
  intervalMs?: number;
  maxIntervalMs?: number;
  hiddenIntervalMs?: number;
  onJobUpdate: (job: JobStatusResponse) => void;
  onError?: (message: string) => void;
}

function computeBackoffDelay(baseIntervalMs: number, maxIntervalMs: number, errorCount: number): number {
  return Math.min(maxIntervalMs, baseIntervalMs * 2 ** Math.min(errorCount, 4));
}

export function useJobPolling({
  jobId,
  enabled = true,
  intervalMs = 1000,
  maxIntervalMs = 15000,
  hiddenIntervalMs = 10000,
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
    let errorCount = 0;

    function clearTimer() {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    }

    function scheduleNext(delayMs: number) {
      clearTimer();
      timer = window.setTimeout(() => {
        void pollJob();
      }, delayMs);
    }

    async function pollJob() {
      if (isCancelled) {
        return;
      }
      const nextDelayMs =
        document.visibilityState === "hidden" ? hiddenIntervalMs : intervalMs;

      try {
        const nextJob = await getJob(targetJobId);
        if (isCancelled) {
          return;
        }

        errorCount = 0;
        onJobUpdateRef.current(nextJob);
        if (isJobTerminal(nextJob)) {
          clearTimer();
          return;
        }
        scheduleNext(nextDelayMs);
      } catch (caughtError) {
        if (isCancelled) {
          return;
        }

        errorCount += 1;
        const message =
          caughtError instanceof Error
            ? caughtError.message
            : "Falha ao consultar o lote.";
        onErrorRef.current?.(message);
        scheduleNext(computeBackoffDelay(nextDelayMs, maxIntervalMs, errorCount));
      }
    }

    void pollJob();

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        clearTimer();
        void pollJob();
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      isCancelled = true;
      clearTimer();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [enabled, hiddenIntervalMs, intervalMs, jobId, maxIntervalMs]);
}
