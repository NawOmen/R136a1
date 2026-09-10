import { expect, test } from "@playwright/test";
import { api } from "../../apps/web/app/lib/api";

test("security audit and alerts use the versioned API over HTTP and HTTPS", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalUrl = process.env.NEXT_PUBLIC_API_URL;
  delete process.env.NEXT_PUBLIC_API_URL;
  const received: { url: string; authorization: string | null }[] = [];
  globalThis.fetch = async (input, init) => {
    received.push({ url: String(input), authorization: new Headers(init?.headers).get("Authorization") });
    return Response.json([{ event: "auth.rate_limited", correlation_id: "synthetic-event" }]);
  };
  try {
    for (const [protocol, prefix] of [["http:", "http://localhost:8001"], ["https:", "/gateway"]]) {
      Object.defineProperty(globalThis, "window", {
        configurable: true, value: { location: { protocol, hostname: "localhost" } },
      });
      for (const alertsOnly of [false, true]) {
        const events = await api.getSecurityEvents("synthetic-token", alertsOnly);
        expect(events[0].event).toBe("auth.rate_limited");
        expect(received.at(-1)).toEqual({
          url: prefix + "/api/v1/admin/security-events" + (alertsOnly ? "?alerts_only=true" : ""),
          authorization: "Bearer synthetic-token",
        });
      }
    }
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
    if (originalUrl === undefined) delete process.env.NEXT_PUBLIC_API_URL;
    else process.env.NEXT_PUBLIC_API_URL = originalUrl;
  }
});
