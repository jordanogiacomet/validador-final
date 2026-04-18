"use client";

import { useState } from "react";

import { LoginScreen } from "@/components/login-screen";
import { OperationalWorkspace } from "@/components/operational-workspace";
import { getApiSession, setApiSession } from "@/lib/api";
import type { LoginResponse } from "@/lib/types";

export default function HomePage() {
  const [session, setSession] = useState<LoginResponse | null>(() => getApiSession());

  function handleAuthenticated(nextSession: LoginResponse) {
    setApiSession(nextSession);
    setSession(nextSession);
  }

  return (
    <div className="shell">
      {session ? <OperationalWorkspace /> : <LoginScreen onAuthenticated={handleAuthenticated} />}
    </div>
  );
}
