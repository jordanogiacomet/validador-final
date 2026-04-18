"use client";

import React, { useEffect, useState } from "react";

import { LoginScreen } from "@/components/login-screen";
import { OperationalWorkspace } from "@/components/operational-workspace";
import {
  clearApiSession,
  getApiSession,
  setApiSession,
  setApiSessionInvalidHandler,
} from "@/lib/api";
import type { LoginResponse } from "@/lib/types";

export default function HomePage() {
  const [session, setSession] = useState<LoginResponse | null>(null);
  const [isSessionReady, setIsSessionReady] = useState(false);

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

  function handleAuthenticated(nextSession: LoginResponse) {
    setApiSession(nextSession);
    setSession(nextSession);
  }

  function handleLogout() {
    clearApiSession();
    setSession(null);
  }

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
            <OperationalWorkspace />
          </>
        ) : (
          <LoginScreen onAuthenticated={handleAuthenticated} />
        )
      ) : null}
    </div>
  );
}
