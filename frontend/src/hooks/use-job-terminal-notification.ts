"use client";

import { useEffect, useRef } from "react";

import { formatJobFailureMessage, isJobTerminal } from "@/lib/presentation";
import type { JobStatusResponse } from "@/lib/types";

type NotificationConstructorLike = typeof Notification;

function getNotificationConstructor(): NotificationConstructorLike | null {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return null;
  }

  return window.Notification;
}

function isTerminalStatus(status: JobStatusResponse["status"]): boolean {
  return status === "completed" || status === "failed" || status === "canceled";
}

function buildNotificationCopy(job: JobStatusResponse): {
  title: string;
  body: string;
} {
  const fileLabel = job.file_name || "O lote";

  if (job.status === "completed") {
    return {
      title: "Lote concluido",
      body: `${fileLabel} terminou o processamento e ja pode ser revisado.`,
    };
  }

  if (job.status === "failed") {
    return {
      title: "Lote com falha",
      body: formatJobFailureMessage(job),
    };
  }

  return {
    title: "Lote cancelado",
    body: `${fileLabel} foi interrompido antes da conclusao.`,
  };
}

export function requestJobNotificationPermission(): void {
  const NotificationApi = getNotificationConstructor();
  if (!NotificationApi || NotificationApi.permission !== "default") {
    return;
  }

  void NotificationApi.requestPermission().catch(() => undefined);
}

export function useJobTerminalNotification(job: JobStatusResponse | null): void {
  const previousSnapshotRef = useRef<{
    jobId: string;
    status: JobStatusResponse["status"];
  } | null>(null);

  useEffect(() => {
    const previousSnapshot = previousSnapshotRef.current;

    if (
      job &&
      previousSnapshot &&
      previousSnapshot.jobId === job.job_id &&
      !isTerminalStatus(previousSnapshot.status) &&
      isJobTerminal(job) &&
      document.visibilityState === "hidden"
    ) {
      const NotificationApi = getNotificationConstructor();
      if (NotificationApi && NotificationApi.permission === "granted") {
        const { title, body } = buildNotificationCopy(job);
        new NotificationApi(title, {
          body,
          tag: `${job.job_id}:${job.status}`,
        });
      }
    }

    previousSnapshotRef.current = job
      ? {
          jobId: job.job_id,
          status: job.status,
        }
      : null;
  }, [job]);
}
