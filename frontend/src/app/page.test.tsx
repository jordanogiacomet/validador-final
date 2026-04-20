import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { authState, session } = vi.hoisted(() => ({
  authState: {
    invalidationHandler: null as (() => void) | null,
  },
  session: {
    tenant_id: "default",
    operator_id: "op-1",
    api_key_id: "issued-1",
    x_api_key: "vapi_example",
    header_name: "X-API-Key",
    expires_at: null as string | null,
  },
}));

vi.mock("@/components/login-screen", () => ({
  LoginScreen: ({
    onAuthenticated,
  }: {
    onAuthenticated: (nextSession: typeof session) => void;
  }) => (
    <button type="button" onClick={() => onAuthenticated(session)}>
      Entrar mock
    </button>
  ),
}));

vi.mock("@/components/operational-workspace", () => ({
  OperationalWorkspace: ({
    initialTenantId,
  }: {
    initialTenantId: string;
  }) => <div>Workspace operacional {initialTenantId}</div>,
}));

vi.mock("@/components/admin-console", () => ({
  AdminConsole: ({
    role,
    sessionTenantId,
    onClose,
  }: {
    role: string;
    sessionTenantId: string;
    onClose: () => void;
  }) => (
    <div>
      <span>
        Console administrativo {role} {sessionTenantId}
      </span>
      <button type="button" onClick={onClose}>
        Fechar painel mock
      </button>
    </div>
  ),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    clearApiSession: vi.fn(),
    getApiSession: vi.fn(),
    renewApiSession: vi.fn(),
    setApiSession: vi.fn(),
    setApiSessionInvalidHandler: vi.fn((handler: (() => void) | null) => {
      authState.invalidationHandler = handler;
    }),
  };
});

import HomePage from "./page";
import {
  clearApiSession,
  getApiSession,
  renewApiSession,
  setApiSession,
  setApiSessionInvalidHandler,
} from "@/lib/api";

const clearApiSessionMock = vi.mocked(clearApiSession);
const getApiSessionMock = vi.mocked(getApiSession);
const renewApiSessionMock = vi.mocked(renewApiSession);
const setApiSessionMock = vi.mocked(setApiSession);
const setApiSessionInvalidHandlerMock = vi.mocked(setApiSessionInvalidHandler);

describe("HomePage auth flow", () => {
  beforeEach(() => {
    authState.invalidationHandler = null;
    session.expires_at = null;
    clearApiSessionMock.mockReset();
    getApiSessionMock.mockReset();
    renewApiSessionMock.mockReset();
    setApiSessionMock.mockReset();
    setApiSessionInvalidHandlerMock.mockReset();
    setApiSessionInvalidHandlerMock.mockImplementation((handler: (() => void) | null) => {
      authState.invalidationHandler = handler;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stores the issued session after login", async () => {
    getApiSessionMock.mockReturnValue(null);

    render(<HomePage />);

    fireEvent.click(await screen.findByRole("button", { name: "Entrar mock" }));

    expect(setApiSessionMock).toHaveBeenCalledWith(session);
    expect(await screen.findByText("Workspace operacional default")).toBeDefined();
  });

  it("restores a persisted session and allows explicit logout", async () => {
    getApiSessionMock.mockReturnValue(session);

    render(<HomePage />);

    expect(await screen.findByText("Workspace operacional default")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Sair" }));

    expect(clearApiSessionMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("button", { name: "Entrar mock" })).toBeDefined();
  });

  it("shows the renewal banner when the session is about to expire", async () => {
    const fakeNow = new Date("2026-04-18T12:00:00Z").getTime();
    vi.spyOn(Date, "now").mockReturnValue(fakeNow);
    session.expires_at = new Date(fakeNow + 2 * 60 * 1000).toISOString();
    getApiSessionMock.mockReturnValue({ ...session });

    render(<HomePage />);

    expect(await screen.findByText(/Sua sessão expira em/i)).toBeDefined();
    expect(screen.getByRole("button", { name: /Renovar sessão/i })).toBeDefined();
  });

  it("replaces the session when the operator renews explicitly", async () => {
    const fakeNow = new Date("2026-04-18T12:00:00Z").getTime();
    vi.spyOn(Date, "now").mockReturnValue(fakeNow);
    session.expires_at = new Date(fakeNow + 3 * 60 * 1000).toISOString();
    const renewedSession = {
      ...session,
      api_key_id: "issued-2",
      x_api_key: "vapi_renewed",
      expires_at: new Date(fakeNow + 30 * 60 * 1000).toISOString(),
    };
    getApiSessionMock.mockReturnValue({ ...session });
    renewApiSessionMock.mockResolvedValue(renewedSession);

    render(<HomePage />);

    await screen.findByRole("button", { name: /Renovar sessão/i });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Renovar sessão/i }));
    });

    expect(renewApiSessionMock).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(screen.queryByText(/Sua sessão expira em/i)).toBeNull();
    });
  });

  it("returns to login when the API invalidates the active key", async () => {
    getApiSessionMock.mockReturnValue(session);

    render(<HomePage />);

    expect(await screen.findByText("Workspace operacional default")).toBeDefined();

    authState.invalidationHandler?.();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Entrar mock" })).toBeDefined();
    });
  });

  it("passes the authenticated tenant to the workspace", async () => {
    getApiSessionMock.mockReturnValue({
      ...session,
      tenant_id: "redesim",
    });

    render(<HomePage />);

    expect(await screen.findByText("Workspace operacional redesim")).toBeDefined();
  });

  it("shows the admin toggle only for administrative roles", async () => {
    getApiSessionMock.mockReturnValue({
      ...session,
      role: "tenant_admin",
    });

    render(<HomePage />);

    expect(await screen.findByRole("button", { name: "Abrir administração" })).toBeDefined();
  });

  it("keeps the operational shell simple for common operators", async () => {
    getApiSessionMock.mockReturnValue({
      ...session,
      role: "operator",
    });

    render(<HomePage />);

    expect(await screen.findByText("Workspace operacional default")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Abrir administração" })).toBeNull();
  });

  it("opens and closes the admin console without replacing the operational workspace", async () => {
    getApiSessionMock.mockReturnValue({
      ...session,
      role: "platform_admin",
    });

    render(<HomePage />);

    fireEvent.click(await screen.findByRole("button", { name: "Abrir administração" }));

    expect(
      await screen.findByText("Console administrativo platform_admin default"),
    ).toBeDefined();
    expect(screen.getByText("Workspace operacional default")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Fechar painel mock" }));

    await waitFor(() => {
      expect(screen.queryByText("Console administrativo platform_admin default")).toBeNull();
    });
    expect(screen.getByRole("button", { name: "Abrir administração" })).toBeDefined();
  });
});
