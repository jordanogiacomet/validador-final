"use client";

import { useEffect, useState } from "react";

import { listActiveJobs } from "@/lib/api";
import type { JobListItemResponse } from "@/lib/types";

export function useActiveJobs(intervalMs = 1000) {
  const [jobs, setJobs] = useState<JobListItemResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refreshJobs() {
    try {
      const nextJobs = await listActiveJobs();
      setJobs(nextJobs);
      setError(null);
    } catch (caughtError) {
      const message =
        caughtError instanceof Error
          ? caughtError.message
          : "Falha ao listar os jobs ativos.";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    let isCancelled = false;

    async function refreshLoop() {
      try {
        const nextJobs = await listActiveJobs();
        if (isCancelled) {
          return;
        }

        setJobs(nextJobs);
        setError(null);
      } catch (caughtError) {
        if (isCancelled) {
          return;
        }

        const message =
          caughtError instanceof Error
            ? caughtError.message
            : "Falha ao listar os jobs ativos.";
        setError(message);
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    }

    void refreshLoop();
    const timer = window.setInterval(() => {
      void refreshLoop();
    }, intervalMs);

    return () => {
      isCancelled = true;
      window.clearInterval(timer);
    };
  }, [intervalMs]);

  return {
    jobs,
    isLoading,
    error,
    refreshJobs,
  };
}
