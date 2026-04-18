import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearApiSession, listTenants, loginOperator, setApiSession } from "@/lib/api";

describe("api auth session helpers", () => {
  beforeEach(() => {
    clearApiSession();
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

    setApiSession({
      tenant_id: "default",
      operator_id: "op-1",
      api_key_id: "issued-1",
      x_api_key: "vapi_example",
      header_name: "X-API-Key",
    });

    await listTenants();

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(requestInit?.headers);
    expect(headers.get("X-API-Key")).toBe("vapi_example");
  });
});
