"use client";

import { useCallback, useEffect, useState } from "react";

import { listJobs } from "@/lib/api";
import type { JobListItemResponse } from "@/lib/types";

interface UseActiveJobsOptions {
  activeOnly?: boolean;
  limit?: number;
  intervalMs?: number;
  maxIntervalMs?: number;
  hiddenIntervalMs?: number;
}

function computeBackoffDelay(baseIntervalMs: number, maxIntervalMs: number, errorCount: number): number {
  return Math.min(maxIntervalMs, baseIntervalMs * 2 ** Math.min(errorCount, 4));
}

export function useActiveJobs(options: UseActiveJobsOptions | number = {}) {
  const {
    activeOnly = false,
    limit = 8,
    intervalMs = 2500,
    maxIntervalMs = 30000,
    hiddenIntervalMs = 15000,
  } = typeof options === "number" ? { intervalMs: options } : options;
  const [jobs, setJobs] = useState<JobListItemResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshJobs = useCallback(async () => {
    try {
      const nextJobs = await listJobs({ activeOnly, limit });
      setJobs(nextJobs);
      setError(null);
    } catch (caughtError) {
      const message =
        caughtError instanceof Error
          ? caughtError.message
          : "Falha ao listar os lotes recentes.";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [activeOnly, limit]);

  useEffect(() => {
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
        void refreshLoop();
      }, delayMs);
    }

    async function refreshLoop() {
      if (document.visibilityState === "hidden") {
        scheduleNext(hiddenIntervalMs);
        return;
      }

      try {
        const nextJobs = await listJobs({ activeOnly, limit });
        if (isCancelled) {
          return;
        }

        errorCount = 0;
        setJobs(nextJobs);
        setError(null);
      } catch (caughtError) {
        if (isCancelled) {
          return;
        }

        errorCount += 1;
        const message =
          caughtError instanceof Error
            ? caughtError.message
            : "Falha ao listar os lotes recentes.";
        setError(message);
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
          scheduleNext(errorCount ? computeBackoffDelay(intervalMs, maxIntervalMs, errorCount) : intervalMs);
        }
      }
    }

    void refreshLoop();

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        clearTimer();
        void refreshLoop();
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      isCancelled = true;
      clearTimer();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [activeOnly, hiddenIntervalMs, intervalMs, limit, maxIntervalMs]);

  return {
    jobs,
    isLoading,
    error,
    refreshJobs,
  };
}
