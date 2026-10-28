import { expect, type Page } from "@playwright/test";

type Run = {
  id: string;
  used_route: string;
  result: {
    can_confirm: boolean;
    conflicts: unknown[];
    questions: { key: string; options: unknown[] }[];
    properties: { key: string; value: unknown; status: string }[];
  };
};

// These are declared buyer answers for the synthetic request, never model output.
const answers: Record<string, string> = { quantity_units: "200", unit: "шт", lead_time_days: "30", delivery_city: "Москва" };

export async function completeLiveClarifications(page: Page, initial: Run) {
  let run = initial;
  const manualAnswers: { key: string; value: string }[] = [];
  const initialQuantity = initial.result.properties.find(property => property.key === "quantity_units");
  if (initialQuantity?.value != null) expect(Number(initialQuantity.value), "Извлечённое количество должно соответствовать исходному тексту").toBe(200);
  for (let round = 0; !run.result.can_confirm && round < 5; round++) {
    expect(run.result.questions.length, "Не готовый к проверке разбор должен показывать уточнения").toBeGreaterThan(0);
    for (const question of run.result.questions) {
      const value = answers[question.key];
      expect(value, `Неожиданное уточнение ${question.key}: тест не должен придумывать ответ`).toBeDefined();
      const input = page.locator(`#answer_${question.key}`);
      if (question.options.length) {
        expect(question.options.map(String)).toContain(value);
        await input.selectOption(value);
      } else await input.fill(value);
      manualAnswers.push({ key: question.key, value });
    }
    const responsePromise = page.waitForResponse(response => response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith(`/agent-runs/${run.id}/clarify`));
    await page.getByRole("button", { name: "Продолжить", exact: true }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    run = await response.json() as Run;
    expect(run.used_route).toBe("local_qwen");
  }
  expect(run.result.can_confirm, "После явных ответов покупателя разбор должен завершиться").toBe(true);
  expect(run.result.conflicts).toEqual([]);
  expect(Number(run.result.properties.find(property => property.key === "quantity_units")?.value)).toBe(200);
  return { run, manualAnswers, quantityExtractedInitially: initialQuantity?.value != null && initialQuantity.status === "confirmed" };
}
