import { expect, test } from "@playwright/test";
import { displayMoney, lineAmount, scaledMoney } from "../../apps/web/app/lib/money";
import { marketplace } from "../../apps/web/app/lib/marketplace";

test("exact subkopeck prices, large quantities and negative money retain their values", () => {
  expect(lineAmount("0.00000000125", 1_000_000_000)).toBe("1.250000000000");
  expect(lineAmount("0.005",1)).toBe("0.010000000000");
  expect(displayMoney("2.675")).toBe("2,68 ₽");
  expect(displayMoney("-1000.01")).toBe("−1\u00a0000,01 ₽");
  expect(displayMoney("150.123456789012",12)).toBe("150,123456789012 ₽");
  expect(()=>scaledMoney("NaN")).toThrow();
});

test("marketplace client uses exact v3 without converting submitted prices", async () => {
  const original=globalThis.fetch;
  let url="",body="";
  globalThis.fetch=async (input,init)=> {url=String(input);body=String(init?.body);return Response.json({id:"quote"});};
  try {
    await marketplace.createOffer("synthetic-token","need",{company_id:"seller",price_rub:"0.00000000125",available_units:1000000000,lead_time_days:1,moq_units:1,delivery_cost_rub:null});
    expect(url).toContain("/api/v3/needs/need/offers");
    expect(JSON.parse(body).price_rub).toBe("0.00000000125");
    expect(JSON.parse(body).delivery_cost_rub).toBeNull();
  } finally {globalThis.fetch=original;}
});
