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


test("explicit local service port survives localhost and LAN routing", async () => {
  const { serviceUrl } = await import("../../apps/web/app/lib/serviceUrl");
  const original = Object.getOwnPropertyDescriptor(globalThis, "window");
  try {
    for (const host of ["127.0.0.1", "192.168.1.10"]) {
      Object.defineProperty(globalThis, "window", { configurable: true, value: { location: { protocol: "http:", hostname: host, origin: `http://${host}:13000` } } });
      expect(serviceUrl("http://127.0.0.1:18001", 8001)).toBe(`http://${host}:18001`);
    }
    Object.defineProperty(globalThis, "window", { configurable: true, value: { location: { protocol: "https:", hostname: "market.example", origin: "https://market.example" } } });
    expect(serviceUrl("http://localhost:8001", 8001)).toBe("/gateway");
    expect(serviceUrl("https://api.example/gateway", 8001)).toBe("https://api.example/gateway");
  } finally {
    if (original) Object.defineProperty(globalThis, "window", original);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
