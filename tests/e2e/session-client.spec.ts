import { expect, test } from "@playwright/test";
import { api, getToken, setToken } from "../../apps/web/app/lib/api";
import { marketplace } from "../../apps/web/app/lib/marketplace";

const protectedRequests = [
  ["account", (token: string) => api.me(token)],
  ["marketplace", (token: string) => marketplace.getNotifications(token)],
  ["document download", (token: string) => marketplace.downloadEditorDocument(token, "synthetic-document")],
] as const;

async function withBrowserSession(work: (redirects: string[]) => Promise<void>) {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalFetch = globalThis.fetch;
  const storage = new Map<string, string>();
  const redirects: string[] = [];
  Object.defineProperty(globalThis, "window", { configurable: true, value: {
    localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
    dispatchEvent: () => true,
    location: { origin: "http://localhost:3010", protocol: "http:", hostname: "localhost", pathname: "/settings", replace: (path: string) => redirects.push(path) },
  } });
  try { await work(redirects); }
  finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
}

for (const [name, request] of protectedRequests) {
  for (const action of ["end sessions", "change password"] as const) {
    test(`${name}: delayed old-token 401 preserves replacement after ${action}`, async () => {
      await withBrowserSession(async redirects => {
        let finishOld!: (response: Response) => void;
        globalThis.fetch = async (url, init) => {
          expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer old-session");
          return /\/(sessions\/end|password\/change)$/.test(String(url))
            ? Response.json({ access_token: "replacement-session", user: {} })
            : new Promise<Response>(resolve => { finishOld = resolve; });
        };
        setToken("old-session");
        const old = request("old-session").catch(error => error);
        const result = action === "end sessions"
          ? await api.endOtherSessions("old-session")
          : await api.changePassword("old-session", "old-password-123", "new-password-123");
        setToken(result.access_token);
        finishOld(Response.json({ detail: "Сеанс завершён. Войдите снова." }, { status: 401 }));
        expect((await old).status).toBe(401);
        expect(getToken()).toBe("replacement-session");
        expect(redirects).toEqual([]);
      });
    });
  }

  test(`${name}: current-token 401 still clears the session and opens login`, async () => {
    await withBrowserSession(async redirects => {
      globalThis.fetch = async () => Response.json({ detail: "Сеанс завершён. Войдите снова." }, { status: 401 });
      setToken("current-session");
      await expect(request("current-session")).rejects.toMatchObject({ status: 401 });
      expect(getToken()).toBeNull();
      expect(redirects).toEqual(["/login"]);
    });
  });
}

test("an unauthenticated request cannot erase an existing session on 401", async () => {
  await withBrowserSession(async redirects => {
    globalThis.fetch = async () => Response.json({ detail: "Доступ временно недоступен." }, { status: 401 });
    setToken("current-session");
    await expect(marketplace.getCatalog()).rejects.toMatchObject({ status: 401 });
    expect(getToken()).toBe("current-session");
    expect(redirects).toEqual([]);
  });
});
