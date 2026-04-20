import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  completePasswordSetup,
  createInitialAdmin,
  getInitialSetupState,
  loginOperator,
} from "@/lib/api";

import { LoginScreen } from "./login-screen";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    completePasswordSetup: vi.fn(),
    createInitialAdmin: vi.fn(),
    getInitialSetupState: vi.fn(),
    loginOperator: vi.fn(),
  };
});

const completePasswordSetupMock = vi.mocked(completePasswordSetup);
const createInitialAdminMock = vi.mocked(createInitialAdmin);
const getInitialSetupStateMock = vi.mocked(getInitialSetupState);
const loginOperatorMock = vi.mocked(loginOperator);

describe("LoginScreen", () => {
  beforeEach(() => {
    completePasswordSetupMock.mockReset();
    createInitialAdminMock.mockReset();
    getInitialSetupStateMock.mockReset();
    loginOperatorMock.mockReset();
    getInitialSetupStateMock.mockResolvedValue({
      available: false,
      storage_configured: true,
      requires_setup_token: false,
      tenant_id: null,
    });
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("renders the typed tenant login fields", () => {
    render(<LoginScreen onAuthenticated={vi.fn()} />);

    expect(screen.getByLabelText("Código da empresa")).toBeDefined();
    expect(screen.getByLabelText("Usuário")).toBeDefined();
    expect(screen.getByLabelText("Senha")).toBeDefined();
    expect(screen.queryByText("default.operator")).toBeNull();
    expect(screen.getByRole("button", { name: "Entrar" })).toBeDefined();
  });

  it("shows local development login hints only when enabled", () => {
    vi.stubEnv("NEXT_PUBLIC_SHOW_DEV_LOGIN_HINTS", "true");

    render(<LoginScreen onAuthenticated={vi.fn()} />);

    expect(screen.getByText("Dados iniciais de desenvolvimento")).toBeDefined();
    expect(screen.getByText("default.operator")).toBeDefined();
  });

  it("shows the initial setup form only when the API reports setup availability", async () => {
    getInitialSetupStateMock.mockResolvedValueOnce({
      available: true,
      storage_configured: true,
      requires_setup_token: false,
      tenant_id: "default",
    });

    render(<LoginScreen onAuthenticated={vi.fn()} />);

    expect(await screen.findByText("Criar administrador inicial")).toBeDefined();
    expect(screen.getByLabelText("Usuário administrador")).toBeDefined();
    expect(screen.getByLabelText("Senha inicial")).toBeDefined();
    expect(screen.queryByLabelText("Token de setup")).toBeNull();
  });

  it("creates the initial admin and prepares the login form for the created account", async () => {
    getInitialSetupStateMock.mockResolvedValueOnce({
      available: true,
      storage_configured: true,
      requires_setup_token: false,
      tenant_id: "default",
    });
    createInitialAdminMock.mockResolvedValueOnce({
      tenant_id: "default",
      operator_id: "operator-1",
      username: "admin.inicial",
      disabled: false,
      is_seed: false,
    });

    render(<LoginScreen onAuthenticated={vi.fn()} />);

    fireEvent.change(await screen.findByLabelText("Usuário administrador"), {
      target: { value: "admin.inicial" },
    });
    fireEvent.change(screen.getByLabelText("Senha inicial"), {
      target: { value: "Setup@2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Criar administrador" }));

    await waitFor(() => {
      expect(createInitialAdminMock).toHaveBeenCalledWith({
        username: "admin.inicial",
        password: "Setup@2026",
        setupToken: "",
      });
    });

    expect(
      await screen.findByText("Administrador inicial criado. Entre com o usuário criado."),
    ).toBeDefined();
    expect(screen.queryByText("Criar administrador inicial")).toBeNull();
    expect((screen.getByLabelText("Código da empresa") as HTMLInputElement).value).toBe(
      "default",
    );
    expect((screen.getByLabelText("Usuário") as HTMLInputElement).value).toBe(
      "admin.inicial",
    );
  });

  it("requires and submits the setup token when configured by the API", async () => {
    getInitialSetupStateMock.mockResolvedValueOnce({
      available: true,
      storage_configured: true,
      requires_setup_token: true,
      tenant_id: "default",
    });
    createInitialAdminMock.mockResolvedValueOnce({
      tenant_id: "default",
      operator_id: "operator-1",
      username: "admin.inicial",
      disabled: false,
      is_seed: false,
    });

    render(<LoginScreen onAuthenticated={vi.fn()} />);

    fireEvent.change(await screen.findByLabelText("Usuário administrador"), {
      target: { value: "admin.inicial" },
    });
    fireEvent.change(screen.getByLabelText("Senha inicial"), {
      target: { value: "Setup@2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Criar administrador" }));

    expect(createInitialAdminMock).not.toHaveBeenCalled();
    expect(await screen.findByText("Informe o token de setup.")).toBeDefined();

    fireEvent.change(screen.getByLabelText("Token de setup"), {
      target: { value: "token-publicado" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Criar administrador" }));

    await waitFor(() => {
      expect(createInitialAdminMock).toHaveBeenCalledWith({
        username: "admin.inicial",
        password: "Setup@2026",
        setupToken: "token-publicado",
      });
    });
  });

  it("validates required fields before calling login", async () => {
    render(<LoginScreen onAuthenticated={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(loginOperatorMock).not.toHaveBeenCalled();
    expect(await screen.findByText("Informe o código da empresa.")).toBeDefined();
    expect(screen.getByText("Informe o usuário autorizado para essa empresa.")).toBeDefined();
    expect(screen.getByText("Informe a senha para continuar.")).toBeDefined();
  });

  it("submits valid credentials and forwards the issued session", async () => {
    const onAuthenticated = vi.fn();
    loginOperatorMock.mockResolvedValueOnce({
      tenant_id: "default",
      operator_id: "op-1",
      api_key_id: "issued-1",
      x_api_key: "vapi_example",
      header_name: "X-API-Key",
    });

    render(<LoginScreen onAuthenticated={onAuthenticated} />);

    fireEvent.change(screen.getByLabelText("Código da empresa"), { target: { value: "default" } });
    fireEvent.change(screen.getByLabelText("Usuário"), { target: { value: "operador" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "segredo" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => {
      expect(loginOperatorMock).toHaveBeenCalledWith({
        tenantId: "default",
        username: "operador",
        password: "segredo",
      });
    });
    expect(onAuthenticated).toHaveBeenCalledWith({
      tenant_id: "default",
      operator_id: "op-1",
      api_key_id: "issued-1",
      x_api_key: "vapi_example",
      header_name: "X-API-Key",
    });
  });

  it("keeps the user on the auth screen when the login requires password setup", async () => {
    const onAuthenticated = vi.fn();
    loginOperatorMock.mockResolvedValueOnce({
      tenant_id: "default",
      operator_id: "op-1",
      api_key_id: "issued-1",
      x_api_key: "vapi_temp",
      must_change_password: true,
      header_name: "X-API-Key",
    });
    completePasswordSetupMock.mockResolvedValueOnce({
      tenant_id: "default",
      operator_id: "op-1",
      username: "operador",
      disabled: false,
      must_change_password: false,
      is_seed: false,
    });

    render(<LoginScreen onAuthenticated={onAuthenticated} />);

    fireEvent.change(screen.getByLabelText("Código da empresa"), {
      target: { value: "default" },
    });
    fireEvent.change(screen.getByLabelText("Usuário"), {
      target: { value: "operador" },
    });
    fireEvent.change(screen.getByLabelText("Senha"), {
      target: { value: "Temp@2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(
      await screen.findByText("Defina a nova senha antes de acessar a área operacional"),
    ).toBeDefined();
    expect(onAuthenticated).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Nova senha"), {
      target: { value: "SenhaFinal@2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Concluir troca de senha" }));

    await waitFor(() => {
      expect(completePasswordSetupMock).toHaveBeenCalledWith({
        apiKey: "vapi_temp",
        newPassword: "SenhaFinal@2026",
      });
    });
    expect(
      await screen.findByText("Senha temporária atualizada. Entre novamente com a nova senha."),
    ).toBeDefined();
    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  it.each([
    [
      "credenciais inválidas",
      new ApiError("Invalid credentials", 401),
      "Credenciais inválidas. Revise usuário e senha.",
    ],
    [
      "empresa inexistente",
      new ApiError("Tenant not found", 404),
      "Empresa inexistente. Revise o código informado.",
    ],
    [
      "empresa incompatível",
      new ApiError("Operator is not allowed for this tenant", 403),
      "Este usuário não pode acessar a empresa informada.",
    ],
  ])("shows a clear message for %s", async (_label, error, message) => {
    loginOperatorMock.mockRejectedValueOnce(error);

    render(<LoginScreen onAuthenticated={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Código da empresa"), { target: { value: "default" } });
    fireEvent.change(screen.getByLabelText("Usuário"), { target: { value: "operador" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "segredo" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect((await screen.findByRole("alert")).textContent).toContain(message);
  });

  it("blocks tenant and username with invalid characters before calling login", async () => {
    render(<LoginScreen onAuthenticated={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Código da empresa"), { target: { value: "default';--" } });
    fireEvent.change(screen.getByLabelText("Usuário"), { target: { value: "operador<script>" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "segredo" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(loginOperatorMock).not.toHaveBeenCalled();
    expect(await screen.findByText("Use apenas letras, números, ponto, hífen ou underscore.")).toBeDefined();
    expect(
      screen.getByText("Use apenas letras, números, ponto, arroba, hífen ou underscore."),
    ).toBeDefined();
  });
});
