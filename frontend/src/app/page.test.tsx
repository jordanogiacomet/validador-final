import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  OperationalWorkspace: () => <div>Workspace operacional</div>,
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    clearApiSession: vi.fn(),
    getApiSession: vi.fn(),
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
  setApiSession,
  setApiSessionInvalidHandler,
} from "@/lib/api";

const clearApiSessionMock = vi.mocked(clearApiSession);
const getApiSessionMock = vi.mocked(getApiSession);
const setApiSessionMock = vi.mocked(setApiSession);
const setApiSessionInvalidHandlerMock = vi.mocked(setApiSessionInvalidHandler);

describe("HomePage auth flow", () => {
  beforeEach(() => {
    authState.invalidationHandler = null;
    clearApiSessionMock.mockReset();
    getApiSessionMock.mockReset();
    setApiSessionMock.mockReset();
    setApiSessionInvalidHandlerMock.mockReset();
    setApiSessionInvalidHandlerMock.mockImplementation((handler: (() => void) | null) => {
      authState.invalidationHandler = handler;
    });
  });

  it("stores the issued session after login", async () => {
    getApiSessionMock.mockReturnValue(null);

    render(<HomePage />);

    fireEvent.click(await screen.findByRole("button", { name: "Entrar mock" }));

    expect(setApiSessionMock).toHaveBeenCalledWith(session);
    expect(await screen.findByText("Workspace operacional")).toBeDefined();
  });

  it("restores a persisted session and allows explicit logout", async () => {
    getApiSessionMock.mockReturnValue(session);

    render(<HomePage />);

    expect(await screen.findByText("Workspace operacional")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Sair" }));

    expect(clearApiSessionMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("button", { name: "Entrar mock" })).toBeDefined();
  });

  it("returns to login when the API invalidates the active key", async () => {
    getApiSessionMock.mockReturnValue(session);

    render(<HomePage />);

    expect(await screen.findByText("Workspace operacional")).toBeDefined();

    authState.invalidationHandler?.();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Entrar mock" })).toBeDefined();
    });
  });
});
