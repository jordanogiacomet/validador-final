import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearApiSession,
  downloadGeneratedFile,
  downloadApiFile,
  getApiSession,
  getApiSessionExpiresAtMs,
  listAuditEvents,
  listTenants,
  loginOperator,
  renewApiSession,
  setApiSession,
  setApiSessionInvalidHandler,
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
