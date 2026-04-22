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

    expect(screen.getByLabelText("Codigo da empresa")).toBeDefined();
    expect(screen.getByLabelText("Usuario")).toBeDefined();
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

  it("keeps first access as a separate mode instead of mixing it into the login form", async () => {
    getInitialSetupStateMock.mockResolvedValueOnce({
      available: true,
      storage_configured: true,
      requires_setup_token: false,
      tenant_id: "default",
    });

    render(<LoginScreen onAuthenticated={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "Primeiro acesso" })).toBeDefined();
    expect(screen.queryByLabelText("Usuario administrador")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Primeiro acesso" }));

    expect(await screen.findByLabelText("Usuario administrador")).toBeDefined();
    expect(screen.queryByLabelText("Codigo da empresa")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Voltar ao login" }));

    expect(await screen.findByLabelText("Codigo da empresa")).toBeDefined();
    expect(screen.queryByLabelText("Usuario administrador")).toBeNull();
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

    fireEvent.click(await screen.findByRole("button", { name: "Primeiro acesso" }));
    fireEvent.change(screen.getByLabelText("Usuario administrador"), {
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
      await screen.findByText("Administrador inicial criado. Entre com o usuario criado."),
    ).toBeDefined();
    expect(screen.queryByLabelText("Usuario administrador")).toBeNull();
    expect((screen.getByLabelText("Codigo da empresa") as HTMLInputElement).value).toBe(
      "default",
    );
    expect((screen.getByLabelText("Usuario") as HTMLInputElement).value).toBe(
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

    fireEvent.click(await screen.findByRole("button", { name: "Primeiro acesso" }));
    fireEvent.change(screen.getByLabelText("Usuario administrador"), {
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
    expect(await screen.findByText("Informe o codigo da empresa.")).toBeDefined();
    expect(screen.getByText("Informe o usuario autorizado para essa empresa.")).toBeDefined();
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

    fireEvent.change(screen.getByLabelText("Codigo da empresa"), {
      target: { value: "default" },
    });
    fireEvent.change(screen.getByLabelText("Usuario"), {
      target: { value: "operador" },
    });
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

    fireEvent.change(screen.getByLabelText("Codigo da empresa"), {
      target: { value: "default" },
    });
    fireEvent.change(screen.getByLabelText("Usuario"), {
      target: { value: "operador" },
    });
    fireEvent.change(screen.getByLabelText("Senha"), {
      target: { value: "Temp@2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(
      await screen.findByText("Conclua esta etapa para liberar o acesso"),
    ).toBeDefined();
    expect(screen.queryByLabelText("Codigo da empresa")).toBeNull();
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
      await screen.findByText("Senha temporaria atualizada. Entre novamente com a nova senha."),
    ).toBeDefined();
    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  it.each([
    [
      "credenciais invalidas",
      new ApiError("Invalid credentials", 401),
      "Credenciais invalidas. Revise usuario e senha.",
    ],
    [
      "empresa inexistente",
      new ApiError("Tenant not found", 404),
      "Empresa inexistente. Revise o codigo informado.",
    ],
    [
      "empresa incompativel",
      new ApiError("Operator is not allowed for this tenant", 403),
      "Este usuario nao pode acessar a empresa informada.",
    ],
  ])("shows a clear message for %s", async (_label, error, message) => {
    loginOperatorMock.mockRejectedValueOnce(error);

    render(<LoginScreen onAuthenticated={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Codigo da empresa"), {
      target: { value: "default" },
    });
    fireEvent.change(screen.getByLabelText("Usuario"), {
      target: { value: "operador" },
    });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "segredo" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect((await screen.findByRole("alert")).textContent).toContain(message);
  });

  it("blocks tenant and username with invalid characters before calling login", async () => {
    render(<LoginScreen onAuthenticated={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Codigo da empresa"), {
      target: { value: "default';--" },
    });
    fireEvent.change(screen.getByLabelText("Usuario"), {
      target: { value: "operador<script>" },
    });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "segredo" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(loginOperatorMock).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Use apenas letras, numeros, ponto, hifen ou underscore."),
    ).toBeDefined();
    expect(
      screen.getByText(
        "Use apenas letras, numeros, ponto, arroba, hifen ou underscore.",
      ),
    ).toBeDefined();
  });
});
