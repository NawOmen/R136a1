import { expect, test } from "@playwright/test";
import { agents } from "../../apps/web/app/lib/agents";

test("clarification and confirmation bind the displayed Gateway revision", async () => {
  const savedFetch = globalThis.fetch;
  const requests: { url: string; body: unknown; auth: string | null }[] = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : null, auth: new Headers(init?.headers).get("Authorization") });
    return Response.json({ id: "synthetic-run", revision: 4, state: "confirmed_by_user" });
  };
  try {
    await agents.clarify("synthetic-token", "synthetic-run", { material: "дерево" }, 3);
    expect(requests[0].url).toContain("/api/v2/agent-runs/synthetic-run/clarify");
    expect(requests[0].body).toEqual({ answers: { material: "дерево" }, expected_revision: 3 });
    await agents.confirm("synthetic-token", "synthetic-run", 4);
    expect(requests[1].body).toEqual({ expected_revision: 4 });
    await agents.invalidateSource("synthetic-token", "synthetic-run", "file_1", 4);
    expect(requests[2].url).toContain("/sources/file_1/invalidate");
    expect(requests[2].body).toEqual({ expected_revision: 4 });
    expect(requests.every(item => item.auth === "Bearer synthetic-token")).toBe(true);
  } finally { globalThis.fetch = savedFetch; }
});
