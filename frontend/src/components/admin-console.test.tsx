import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createAdminTenant,
  createOperatorAccount,
  getTenantValidationProfile,
  listAdminTenants,
  listOperators,
  publishTenantValidationProfileDraft,
  saveTenantValidationProfileDraft,
} from "@/lib/api";
import type { TenantValidationProfileResponse } from "@/lib/types";

import { AdminConsole } from "./admin-console";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    ApiError: actual.ApiError,
    createAdminTenant: vi.fn(),
    createOperatorAccount: vi.fn(),
    createOperatorInvitation: vi.fn(),
    disableAdminTenant: vi.fn(),
    disableOperatorAccount: vi.fn(),
    getTenantValidationProfile: vi.fn(),
    listAdminTenants: vi.fn(),
    listOperators: vi.fn(),
    publishTenantValidationProfileDraft: vi.fn(),
    reactivateAdminTenant: vi.fn(),
    resetOperatorAccountPassword: vi.fn(),
    rollbackTenantValidationProfile: vi.fn(),
    saveTenantValidationProfileDraft: vi.fn(),
    updateAdminTenant: vi.fn(),
  };
});

const createAdminTenantMock = vi.mocked(createAdminTenant);
const createOperatorAccountMock = vi.mocked(createOperatorAccount);
const getTenantValidationProfileMock = vi.mocked(getTenantValidationProfile);
const listAdminTenantsMock = vi.mocked(listAdminTenants);
const listOperatorsMock = vi.mocked(listOperators);
const publishTenantValidationProfileDraftMock = vi.mocked(
  publishTenantValidationProfileDraft,
);
const saveTenantValidationProfileDraftMock = vi.mocked(saveTenantValidationProfileDraft);

const PROFILE_STATE: TenantValidationProfileResponse = {
  tenant_id: "default",
  source: "file",
  current_profile: {
    columns: {
      item: "Item",
      placa_anterior: "Placa Anterior",
      descricao: "Descrição",
      marca: "Marca",
      modelo: "Modelo",
      ns: "NS",
      local: "Local",
      cc: "CC",
      complemento: "Complemento",
      observacao: "Observação",
    },
    enabled_rules: ["duplicate_item", "flag_consistency"],
    disabled_rules: [],
    thresholds: {
      short_complement_max_words: 3,
    },
    categories: [],
    normalization: {
      brand_aliases: {},
      model_aliases: {},
      model_brands: {},
    },
    suspicious_patterns: {
      literal_patterns: [],
      regex_patterns: [],
    },
    llm: {
      enabled: false,
      healthcheck_enabled: false,
      model: "",
      fallback_model: null,
      parallel_requests: 1,
      temperature: 0,
      max_tokens: 1024,
      prompt_file: "",
      cache_ttl_seconds: 0,
    },
  },
  draft: null,
  published_version: null,
  versions: [],
};

describe("AdminConsole", () => {
  beforeEach(() => {
    createAdminTenantMock.mockReset();
    createOperatorAccountMock.mockReset();
    getTenantValidationProfileMock.mockReset();
    listAdminTenantsMock.mockReset();
    listOperatorsMock.mockReset();
    publishTenantValidationProfileDraftMock.mockReset();
    saveTenantValidationProfileDraftMock.mockReset();
    listOperatorsMock.mockResolvedValue([]);
    getTenantValidationProfileMock.mockResolvedValue(PROFILE_STATE);
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

  it("lets an admin save and publish a validation profile draft", async () => {
    saveTenantValidationProfileDraftMock.mockResolvedValueOnce({
      ...PROFILE_STATE,
      draft: {
        tenant_id: "default",
        profile: PROFILE_STATE.current_profile,
        updated_at: "2026-04-22T12:00:00Z",
        updated_by_operator_id: "operator-1",
        updated_by_username: "admin",
        updated_by_role: "tenant_admin",
      },
    });
    publishTenantValidationProfileDraftMock.mockResolvedValueOnce({
      ...PROFILE_STATE,
      source: "published",
      published_version: {
        tenant_id: "default",
        version_id: "profile-1",
        version_number: 1,
        profile: PROFILE_STATE.current_profile,
        published_at: "2026-04-22T12:01:00Z",
        published_by_operator_id: "operator-1",
        published_by_username: "admin",
        published_by_role: "tenant_admin",
        source: "publish",
        rollback_source_version_id: null,
      },
      versions: [
        {
          tenant_id: "default",
          version_id: "profile-1",
          version_number: 1,
          profile: PROFILE_STATE.current_profile,
          published_at: "2026-04-22T12:01:00Z",
          published_by_operator_id: "operator-1",
          published_by_username: "admin",
          published_by_role: "tenant_admin",
          source: "publish",
          rollback_source_version_id: null,
        },
      ],
    });

    render(
      <AdminConsole role="tenant_admin" sessionTenantId="default" onClose={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Perfis" }));

    expect(await screen.findByText("Editor JSON do perfil")).toBeDefined();
    expect(screen.getByDisplayValue(/"duplicate_item"/)).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Salvar rascunho" }));

    await waitFor(() => {
      expect(saveTenantValidationProfileDraftMock).toHaveBeenCalledWith(
        "default",
        expect.objectContaining({
          enabled_rules: ["duplicate_item", "flag_consistency"],
        }),
      );
    });
    expect(await screen.findByText("Rascunho salvo. A validação em produção continua usando a versão publicada.")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Publicar perfil" }));

    await waitFor(() => {
      expect(publishTenantValidationProfileDraftMock).toHaveBeenCalledWith("default");
    });
    expect(screen.getByText(/Perfil publicado na versão 1/)).toBeDefined();
  });
});
