import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearApiSession,
  completePasswordSetup,
  createInitialAdmin,
  downloadTenantTemplate,
  extractUploadPreflightPayload,
  downloadGeneratedFile,
  downloadApiFile,
  getApiSession,
  getApiSessionExpiresAtMs,
  getInitialSetupState,
  getTenantValidationProfile,
  listAuditEvents,
  listJobs,
  listTenants,
  loginOperator,
  publishTenantValidationProfileDraft,
  renewApiSession,
  rollbackTenantValidationProfile,
  saveTenantValidationProfileDraft,
  setApiSession,
  setApiSessionInvalidHandler,
  validateFile,
} from "@/lib/api";

const SESSION = {
  tenant_id: "default",
  operator_id: "op-1",
  api_key_id: "issued-1",
  x_api_key: "vapi_example",
  header_name: "X-API-Key",
};

describe("api auth session helpers", () => {
  beforeEach(() => {
    clearApiSession();
    setApiSessionInvalidHandler(null);
    window.sessionStorage.clear();
  });

  it("calls login without sending an existing X-API-Key header", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          tenant_id: "default",
          operator_id: "op-1",
          api_key_id: "issued-1",
          x_api_key: "vapi_example",
          header_name: "X-API-Key",
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    await loginOperator({
      tenantId: "default",
      username: "operador",
      password: "segredo",
    });

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(headers.get("X-API-Key")).toBeNull();
  });

  it("loads initial setup state without sending an existing X-API-Key header", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          available: true,
          storage_configured: true,
          requires_setup_token: true,
          tenant_id: "default",
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    setApiSession(SESSION);

    const state = await getInitialSetupState();

    const [requestUrl, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(requestUrl).toContain("/setup");
    expect(headers.get("X-API-Key")).toBeNull();
    expect(state.available).toBe(true);
    expect(state.requires_setup_token).toBe(true);
  });

  it("creates the initial admin without sending an existing X-API-Key header", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          tenant_id: "default",
          operator_id: "operator-1",
          username: "admin.inicial",
          disabled: false,
          is_seed: false,
        }),
        {
          status: 201,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    setApiSession(SESSION);

    const operator = await createInitialAdmin({
      username: " admin.inicial ",
      password: "Setup@2026",
      setupToken: " token-publicado ",
    });

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    const body = JSON.parse(String(requestInit?.body));
    expect(headers.get("X-API-Key")).toBeNull();
    expect(body).toEqual({
      username: "admin.inicial",
      password: "Setup@2026",
      setup_token: "token-publicado",
    });
    expect(operator.username).toBe("admin.inicial");
  });

  it("completes mandatory password setup with the provided temporary API key", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          tenant_id: "default",
          operator_id: "operator-1",
          username: "temporario.operador",
          disabled: false,
          must_change_password: false,
          is_seed: false,
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    setApiSession(SESSION);

    const operator = await completePasswordSetup({
      apiKey: " vapi_temp_setup ",
      newPassword: "SenhaFinal@2026",
    });

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    const body = JSON.parse(String(requestInit?.body));
    expect(headers.get("X-API-Key")).toBe("vapi_temp_setup");
    expect(body).toEqual({ new_password: "SenhaFinal@2026" });
    expect(operator.must_change_password).toBe(false);
  });

  it("attaches the issued X-API-Key to authenticated requests", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    setApiSession(SESSION);

    await listTenants();

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(headers.get("X-API-Key")).toBe("vapi_example");
  });

  it("loads audit events through the authenticated API helper", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    setApiSession(SESSION);

    await listAuditEvents({ tenantId: "default", limit: 25 });

    const [requestUrl, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(requestUrl).toContain("/audit?");
    expect(requestUrl).toContain("tenant_id=default");
    expect(requestUrl).toContain("limit=25");
    expect(headers.get("X-API-Key")).toBe("vapi_example");
  });

  it("manages tenant validation profiles through authenticated admin helpers", async () => {
    const profile = {
      columns: {
        item: "Item",
      },
      enabled_rules: ["duplicate_item"],
      disabled_rules: [],
      thresholds: {},
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
      },
    };
    const fetchMock = vi.spyOn(global, "fetch").mockImplementation(async () =>
      new Response(
        JSON.stringify({
          tenant_id: "default",
          source: "file",
          current_profile: profile,
          draft: null,
          published_version: null,
          versions: [],
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    setApiSession(SESSION);

    await getTenantValidationProfile("default");
    await saveTenantValidationProfileDraft("default", profile);
    await publishTenantValidationProfileDraft("default");
    await rollbackTenantValidationProfile("default", "profile-1");

    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      "/admin/tenants/default/validation-profile",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toContain(
      "/admin/tenants/default/validation-profile/draft",
    );
    expect(fetchMock.mock.calls[2]?.[0]).toContain(
      "/admin/tenants/default/validation-profile/publish",
    );
    expect(fetchMock.mock.calls[3]?.[0]).toContain(
      "/admin/tenants/default/validation-profile/rollback",
    );
    const headers = new Headers(fetchMock.mock.calls[1]?.[1]?.headers);
    expect(headers.get("X-API-Key")).toBe("vapi_example");
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      profile,
    });
    expect(JSON.parse(String(fetchMock.mock.calls[3]?.[1]?.body))).toEqual({
      version_id: "profile-1",
    });
  });

  it("lists recent jobs with an optional limit", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    setApiSession(SESSION);

    await listJobs({ limit: 8 });

    const [requestUrl, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(requestUrl).toContain("/jobs?");
    expect(requestUrl).toContain("limit=8");
    expect(requestUrl).not.toContain("active_only=true");
    expect(headers.get("X-API-Key")).toBe("vapi_example");
  });

  it("preserves structured upload preflight payloads on validate errors", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Faltam colunas obrigatorias no cabecalho do CSV.",
          preflight: {
            file_name: "lote.csv",
            file_size_bytes: 256,
            detected_columns: ["Item", "Descricao"],
            missing_columns: ["Complemento"],
            guidance: ["Inclua as colunas faltantes no cabecalho antes de reenviar."],
            issues: [
              {
                code: "missing_columns",
                message:
                  "O cabecalho foi lido, mas ainda nao contem todas as colunas necessarias.",
              },
            ],
          },
        }),
        {
          status: 400,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    setApiSession(SESSION);

    try {
      await validateFile({
        file: new File(["Item,Descricao\n001,Mesa\n"], "lote.csv", {
          type: "text/csv",
        }),
        tenantId: "default",
        validationScope: "zero_items",
      });
      throw new Error("validateFile should have rejected");
    } catch (error) {
      const preflight = extractUploadPreflightPayload(error);
      expect(preflight).not.toBeNull();
      expect(preflight?.missing_columns).toEqual(["Complemento"]);
      expect(preflight?.issues[0]?.code).toBe("missing_columns");
    }
  });

  it("persists the issued session in sessionStorage", () => {
    setApiSession(SESSION);

    expect(window.sessionStorage.length).toBe(1);
    const storedValue = window.sessionStorage.getItem(window.sessionStorage.key(0) || "");
    expect(storedValue ? JSON.parse(storedValue) : null).toEqual(SESSION);

    clearApiSession();
    expect(window.sessionStorage.length).toBe(0);
  });

  it("clears the session and notifies the UI when the API rejects the key", async () => {
    const onSessionInvalid = vi.fn();
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Invalid API key" }), {
        status: 401,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    setApiSession(SESSION);
    setApiSessionInvalidHandler(onSessionInvalid);

    await expect(listTenants()).rejects.toMatchObject({ status: 401 });

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(headers.get("X-API-Key")).toBe("vapi_example");
    expect(getApiSession()).toBeNull();
    expect(window.sessionStorage.length).toBe(0);
    expect(onSessionInvalid).toHaveBeenCalledTimes(1);
  });

  it("includes the request id in operator-facing API errors", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Job not completed: running" }), {
        status: 409,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": "req-123",
        },
      }),
    );

    setApiSession(SESSION);

    await expect(listTenants()).rejects.toMatchObject({
      status: 409,
      detail: "Job not completed: running",
      requestId: "req-123",
      message:
        "O lote ainda não foi concluído. Aguarde o fim do processamento para baixar ou revisar. Código de suporte: req-123.",
    });
  });

  it("keeps the session when the API returns a tenant-scope 403", async () => {
    const onSessionInvalid = vi.fn();
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "API key does not grant access to tenant 'default'" }),
        {
          status: 403,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    setApiSession(SESSION);
    setApiSessionInvalidHandler(onSessionInvalid);

    await expect(listAuditEvents({ tenantId: "default" })).rejects.toMatchObject({ status: 403 });

    expect(getApiSession()).toEqual(SESSION);
    expect(onSessionInvalid).not.toHaveBeenCalled();
  });

  it("renews the session and replaces the stored X-API-Key", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          tenant_id: "default",
          operator_id: "op-1",
          api_key_id: "issued-2",
          previous_api_key_id: "issued-1",
          x_api_key: "vapi_renewed",
          expires_at: "2026-04-18T20:00:00+00:00",
          header_name: "X-API-Key",
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    setApiSession(SESSION);

    const nextSession = await renewApiSession();

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(headers.get("X-API-Key")).toBe("vapi_example");
    expect(nextSession.x_api_key).toBe("vapi_renewed");
    expect(nextSession.api_key_id).toBe("issued-2");
    expect(nextSession.expires_at).toBe("2026-04-18T20:00:00+00:00");
    expect(getApiSession()?.x_api_key).toBe("vapi_renewed");
    expect(getApiSessionExpiresAtMs()).toBe(
      Date.parse("2026-04-18T20:00:00+00:00"),
    );
  });

  it("clears the session when renewal is rejected as expired", async () => {
    const onSessionInvalid = vi.fn();
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Expired API key" }), {
        status: 401,
        headers: {
          "Content-Type": "application/json",
        },
      }),
    );

    setApiSession(SESSION);
    setApiSessionInvalidHandler(onSessionInvalid);

    await expect(renewApiSession()).rejects.toMatchObject({ status: 401 });

    expect(getApiSession()).toBeNull();
    expect(onSessionInvalid).toHaveBeenCalledTimes(1);
  });

  it("downloads protected artifacts with the issued X-API-Key", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response("csv-data", {
        status: 200,
        headers: {
          "Content-Type": "text/csv",
          "Content-Disposition": 'attachment; filename="corrigido.csv"',
        },
      }),
    );
    const createObjectUrl = vi.fn(() => "blob:download");
    const revokeObjectUrl = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    const link = originalCreateElement("a");
    const clickSpy = vi.spyOn(link, "click").mockImplementation(() => {});
    const removeSpy = vi.spyOn(link, "remove");

    window.URL.createObjectURL = createObjectUrl;
    window.URL.revokeObjectURL = revokeObjectUrl;
    vi.spyOn(document, "createElement").mockImplementation(((tagName: string) => {
      if (tagName.toLowerCase() === "a") {
        return link;
      }
      return originalCreateElement(tagName);
    }) as typeof document.createElement);

    setApiSession(SESSION);

    await downloadApiFile("/jobs/job-1/csv", "fallback.csv");

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(headers.get("X-API-Key")).toBe("vapi_example");
    expect(link.download).toBe("corrigido.csv");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(removeSpy).toHaveBeenCalledTimes(1);
    expect(createObjectUrl).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:download");
  });

  it("downloads the tenant template through the authenticated API helper", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response("xlsx-data", {
        status: 200,
        headers: {
          "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "Content-Disposition": 'attachment; filename="default_modelo_validacao.xlsx"',
        },
      }),
    );
    const createObjectUrl = vi.fn(() => "blob:template");
    const revokeObjectUrl = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    const link = originalCreateElement("a");
    const clickSpy = vi.spyOn(link, "click").mockImplementation(() => {});

    window.URL.createObjectURL = createObjectUrl;
    window.URL.revokeObjectURL = revokeObjectUrl;
    vi.spyOn(document, "createElement").mockImplementation(((tagName: string) => {
      if (tagName.toLowerCase() === "a") {
        return link;
      }
      return originalCreateElement(tagName);
    }) as typeof document.createElement);

    setApiSession(SESSION);

    await downloadTenantTemplate("default");

    const [requestUrl, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(requestUrl).toContain("/tenants/default/template");
    expect(headers.get("X-API-Key")).toBe("vapi_example");
    expect(link.download).toBe("default_modelo_validacao.xlsx");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:template");
  });

  it("downloads generated files through the shared browser helper", () => {
    const createObjectUrl = vi.fn(() => "blob:generated");
    const revokeObjectUrl = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    const link = originalCreateElement("a");
    const clickSpy = vi.spyOn(link, "click").mockImplementation(() => {});
    const removeSpy = vi.spyOn(link, "remove");

    window.URL.createObjectURL = createObjectUrl;
    window.URL.revokeObjectURL = revokeObjectUrl;
    vi.spyOn(document, "createElement").mockImplementation(((tagName: string) => {
      if (tagName.toLowerCase() === "a") {
        return link;
      }
      return originalCreateElement(tagName);
    }) as typeof document.createElement);

    downloadGeneratedFile("csv-data", "operacional.csv", { type: "text/csv" });

    expect(link.download).toBe("operacional.csv");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(removeSpy).toHaveBeenCalledTimes(1);
    expect(createObjectUrl).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:generated");
  });
});
