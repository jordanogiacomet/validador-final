import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, loginOperator } from "@/lib/api";

import { LoginScreen } from "./login-screen";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    loginOperator: vi.fn(),
  };
});

const loginOperatorMock = vi.mocked(loginOperator);

describe("LoginScreen", () => {
  beforeEach(() => {
    loginOperatorMock.mockReset();
  });

  it("renders the typed tenant login fields", () => {
    render(<LoginScreen onAuthenticated={vi.fn()} />);

    expect(screen.getByLabelText("Código da empresa")).toBeDefined();
    expect(screen.getByLabelText("Usuário")).toBeDefined();
    expect(screen.getByLabelText("Senha")).toBeDefined();
    expect(screen.getByText("Dados iniciais já configurados")).toBeDefined();
    expect(screen.getByText("default.operator")).toBeDefined();
    expect(screen.getByRole("button", { name: "Entrar" })).toBeDefined();
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
