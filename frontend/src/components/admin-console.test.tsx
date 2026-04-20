import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createAdminTenant,
  createOperatorAccount,
  listAdminTenants,
  listOperators,
} from "@/lib/api";

import { AdminConsole } from "./admin-console";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createAdminTenant: vi.fn(),
    createOperatorAccount: vi.fn(),
    createOperatorInvitation: vi.fn(),
    disableAdminTenant: vi.fn(),
    disableOperatorAccount: vi.fn(),
    listAdminTenants: vi.fn(),
    listOperators: vi.fn(),
    reactivateAdminTenant: vi.fn(),
    resetOperatorAccountPassword: vi.fn(),
    updateAdminTenant: vi.fn(),
  };
});

const createAdminTenantMock = vi.mocked(createAdminTenant);
const createOperatorAccountMock = vi.mocked(createOperatorAccount);
const listAdminTenantsMock = vi.mocked(listAdminTenants);
const listOperatorsMock = vi.mocked(listOperators);

describe("AdminConsole", () => {
  beforeEach(() => {
    createAdminTenantMock.mockReset();
    createOperatorAccountMock.mockReset();
    listAdminTenantsMock.mockReset();
    listOperatorsMock.mockReset();
    listOperatorsMock.mockResolvedValue([]);
  });

  it("shows only tenant-scoped user controls for tenant_admin", async () => {
    listOperatorsMock.mockResolvedValueOnce([
      {
        tenant_id: "default",
        operator_id: "operator-1",
        username: "operador.local",
        role: "operator",
        disabled: false,
        must_change_password: false,
        is_seed: false,
      },
    ]);

    render(
      <AdminConsole role="tenant_admin" sessionTenantId="default" onClose={vi.fn()} />,
    );

    expect(await screen.findByRole("button", { name: "Criar usuário" })).toBeDefined();
    expect(screen.queryByRole("tab", { name: "Empresas" })).toBeNull();
    expect(screen.getByText("operador.local")).toBeDefined();
    expect(listAdminTenantsMock).not.toHaveBeenCalled();
    expect(listOperatorsMock).toHaveBeenCalledWith("default");
  });

  it("shows the tenant section only for platform_admin", async () => {
    listAdminTenantsMock.mockResolvedValueOnce([
      {
        tenant_id: "default",
        display_name: "Default Tenant",
        aliases: [],
        disabled: false,
        source: "file",
        is_default: true,
      },
      {
        tenant_id: "cliente_novo",
        display_name: "Cliente Novo",
        aliases: ["cliente-antigo"],
        disabled: false,
        source: "runtime",
        is_default: false,
      },
    ]);

    render(
      <AdminConsole role="platform_admin" sessionTenantId="default" onClose={vi.fn()} />,
    );

    expect(await screen.findByRole("tab", { name: "Empresas" })).toBeDefined();

    fireEvent.click(screen.getByRole("tab", { name: "Empresas" }));

    expect(await screen.findByText("Nova empresa")).toBeDefined();
    expect(screen.getAllByRole("button", { name: "Salvar dados" }).length).toBeGreaterThan(0);
  });

  it("shows a local permission error when an admin action returns 403", async () => {
    const onClose = vi.fn();
    createOperatorAccountMock.mockRejectedValueOnce(
      new ApiError("Acesso negado para esta operação.", 403, {
        detail: "Operator is not allowed to manage this tenant",
      }),
    );

    render(
      <AdminConsole role="tenant_admin" sessionTenantId="default" onClose={onClose} />,
    );

    await screen.findByRole("button", { name: "Criar usuário" });

    fireEvent.change(screen.getByLabelText("Usuário do novo acesso"), {
      target: { value: "novo.operador" },
    });
    fireEvent.change(screen.getByLabelText("Senha inicial"), {
      target: { value: "SenhaNova@2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Criar usuário" }));

    await waitFor(() => {
      expect(screen.getByText("Ação não concluída")).toBeDefined();
    });
    expect(screen.getByText("Acesso negado para esta operação.")).toBeDefined();
    expect(screen.getByText("Console administrativo")).toBeDefined();
    expect(onClose).not.toHaveBeenCalled();
  });
});
