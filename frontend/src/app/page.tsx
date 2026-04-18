"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";

import { LoginScreen } from "@/components/login-screen";
import { OperationalWorkspace } from "@/components/operational-workspace";
import {
  clearApiSession,
  getApiSession,
  renewApiSession,
  setApiSession,
  setApiSessionInvalidHandler,
} from "@/lib/api";
import type { LoginResponse } from "@/lib/types";

const SESSION_RENEWAL_THRESHOLD_MS = 5 * 60 * 1000;
const SESSION_CLOCK_INTERVAL_MS = 30 * 1000;

function parseSessionExpiresAtMs(session: LoginResponse | null): number | null {
  if (!session?.expires_at) {
    return null;
  }
  const parsed = Date.parse(session.expires_at);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatMinutesUntil(msUntilExpiry: number): string {
  const clampedMs = Math.max(msUntilExpiry, 0);
  const minutes = Math.max(1, Math.ceil(clampedMs / 60000));
  return minutes === 1 ? "menos de 1 minuto" : `cerca de ${minutes} minutos`;
}

export default function HomePage() {
  const [session, setSession] = useState<LoginResponse | null>(null);
  const [isSessionReady, setIsSessionReady] = useState(false);
  const [now, setNow] = useState<number>(() => Date.now());
  const [isRenewing, setIsRenewing] = useState(false);
  const [renewError, setRenewError] = useState<string | null>(null);

  useEffect(() => {
    setSession(getApiSession());
    setIsSessionReady(true);
  }, []);

  useEffect(() => {
    setApiSessionInvalidHandler(() => {
      setSession(null);
    });

    return () => {
      setApiSessionInvalidHandler(null);
    };
  }, []);

  useEffect(() => {
    if (!session) {
      return;
    }
    setNow(Date.now());
    const intervalId = setInterval(() => {
      setNow(Date.now());
    }, SESSION_CLOCK_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [session]);

  const expiresAtMs = useMemo(() => parseSessionExpiresAtMs(session), [session]);
  const msUntilExpiry = expiresAtMs !== null ? expiresAtMs - now : null;
  const isRenewalWindow =
    msUntilExpiry !== null &&
    msUntilExpiry > 0 &&
    msUntilExpiry <= SESSION_RENEWAL_THRESHOLD_MS;

  function handleAuthenticated(nextSession: LoginResponse) {
    setApiSession(nextSession);
    setSession(nextSession);
    setRenewError(null);
  }

  function handleLogout() {
    clearApiSession();
    setSession(null);
    setRenewError(null);
  }

  const handleRenew = useCallback(async () => {
    if (isRenewing) {
      return;
    }
    setIsRenewing(true);
    setRenewError(null);
    try {
      const nextSession = await renewApiSession();
      setSession(nextSession);
    } catch (error) {
      setRenewError(
        error instanceof Error && error.message
          ? error.message
          : "Não foi possível renovar a sessão operacional.",
      );
    } finally {
      setIsRenewing(false);
    }
  }, [isRenewing]);

  return (
    <div className="shell">
      {isSessionReady ? (
        session ? (
          <>
            <section className="panel session-card">
              <div className="session-meta">
                <div className="panel-kicker panel-kicker-inline">Sessão ativa</div>
                <strong>{session.tenant_id}</strong>
                <p>{session.operator_id}</p>
              </div>
              <button className="action-button" type="button" onClick={handleLogout}>
                Sair
              </button>
            </section>
            {isRenewalWindow && msUntilExpiry !== null ? (
              <section
                className="panel session-renewal-card"
                role="status"
                aria-live="polite"
              >
                <div className="session-renewal-meta">
                  <div className="panel-kicker panel-kicker-inline">Sessão</div>
                  <strong>Sua sessão expira em {formatMinutesUntil(msUntilExpiry)}.</strong>
                  <p>Renove agora para continuar sem precisar fazer login novamente.</p>
                  {renewError ? (
                    <p className="inline-error" role="alert">
                      {renewError}
                    </p>
                  ) : null}
                </div>
                <button
                  className="cta"
                  type="button"
                  onClick={handleRenew}
                  disabled={isRenewing}
                >
                  {isRenewing ? "Renovando..." : "Renovar sessão"}
                </button>
              </section>
            ) : null}
            <OperationalWorkspace />
          </>
        ) : (
          <LoginScreen onAuthenticated={handleAuthenticated} />
        )
      ) : null}
    </div>
  );
}
