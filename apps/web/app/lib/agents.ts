import { russianFetch, russianMessage } from "./russianMessages";
import { ApiError, handleUnauthorized } from "./api";
import { serviceUrl } from "./serviceUrl";

const agentsBaseUrl = () => serviceUrl(process.env.NEXT_PUBLIC_LLM_GATEWAY_URL, 8003);

export type FactValue = string | number | boolean | string[];
export type PropertyStatus = "confirmed" | "assumed" | "needs_clarification";

export interface EvidenceItem {
  source_id: string;
  source_name: string;
  source_kind: string;
  value: FactValue;
  confidence: number;
  excerpt: string;
  active?: boolean;
  content_hash?: string;
  original_value?: FactValue;
  normalization?: "model_city_name" | null;
  locator?: { located?: boolean; start?: number; end?: number; page?: number; seconds?: string[]; representation?: string };
}

export interface RequirementProperty {
  key: string;
  label: string;
  value: FactValue | null;
  confidence: number;
  status: PropertyStatus;
  sources: EvidenceItem[];
}

export interface ClarificationQuestion {
  key: string;
  question: string;
  options: FactValue[];
}

export interface CapabilityMatch {
  details?: Record<string, string>;
  cautions?: string[];
  catalog?: { product_id: string; name: string; unit_price_rub: string; total_rub: string | null; moq_units: number; lead_time_days: number; comparable: boolean; note: string }[];
  company_id: string;
  company_name: string;
  score: number;
  reasons: string[];
}

export interface BuyerAgentResult {
  unreadable_sources?: { source_id: string; name: string; content_hash: string }[];
  omitted_source_hashes?: string[];
  category: string;
  properties: RequirementProperty[];
  conflicts: { key: string; label: string; values: FactValue[]; source_ids: string[] }[];
  questions: ClarificationQuestion[];
  matches: CapabilityMatch[];
  warnings: string[];
  summary: string;
  can_confirm: boolean;
}

export interface AgentRun {
  id: string;
  revision: number;
  agent_type: string;
  state: string;
  requested_route: string;
  used_route: string | null;
  result: BuyerAgentResult;
  error: string | null;
  tool_calls: {
    id: string;
    tool_name: string;
    status: string;
    input_summary: string;
    output_summary: string;
    created_at: string;
  }[];
}

export interface SellerExplanation {
  eligible: boolean;
  reasons: string[];
  explanation: string;
  used_route: string;
}

export interface PriceForecast {
  contract_version: "price-forecast-1";
  status: "ready" | "insufficient_data" | "stale_data" | "unstable_data";
  observations: number;
  history_from: string | null;
  history_to: string | null;
  points: { date: string; price_rub: string }[];
  ai_status: "not_requested" | "completed" | "unavailable";
  notes: string[];
}

async function agentFetch(token: string, input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const response = await russianFetch(input, init);
  if (response.status === 401) handleUnauthorized(token);
  return response;
}

async function readResponse(response: Response): Promise<AgentRun> {
  if (!response.ok) {
    let message = `Ошибка анализа: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = russianMessage(body.detail, message);
    } catch {
      // Оставляем безопасное стандартное сообщение.
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as AgentRun;
}

export const agents = {
  async priceForecast(token: string, productId: string): Promise<PriceForecast> {
    const response = await agentFetch(token, `${agentsBaseUrl()}/api/v1/price-forecasts`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ product_id: productId }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(russianMessage(body.detail, "Не удалось построить прогноз. Повторите попытку."), response.status);
    }
    return response.json();
  },
  getRun(token: string, runId: string): Promise<AgentRun> {
    return agentFetch(token, `${agentsBaseUrl()}/api/v2/agent-runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } }).then(readResponse);
  },
  async source(token: string, runId: string, sourceId: string, original = false): Promise<string | Blob> {
    const response = await agentFetch(token, `${agentsBaseUrl()}/api/v2/agent-runs/${runId}/sources/${encodeURIComponent(sourceId)}?original=${original}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new ApiError("Источник недоступен или удалён", response.status);
    if (original) return response.blob();
    return ((await response.json()) as { extracted_text: string }).extracted_text;
  },
  invalidateSource(token: string, runId: string, sourceId: string, revision: number): Promise<AgentRun> {
    return agentFetch(token, `${agentsBaseUrl()}/api/v2/agent-runs/${runId}/sources/${encodeURIComponent(sourceId)}/invalidate`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: revision }),
    }).then(readResponse);
  },
  async askPlatform(token: string, question: string): Promise<{ answer: string; links: string[] }> {
    const response = await agentFetch(token, `${agentsBaseUrl()}/api/v1/platform-assistant`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
    if (!response.ok) { let message="Помощник временно недоступен"; try { const body=(await response.json()) as {detail?:string}; message=russianMessage(body.detail,message); } catch {} throw new ApiError(message,response.status); }
    return response.json();
  },
  async transcribe(token: string, file: File): Promise<string> {
    const form = new FormData();
    form.set("file", file);
    const response = await agentFetch(token, `${agentsBaseUrl()}/api/v1/transcribe`, {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form,
    });
    if (!response.ok) {
      let message = "Не удалось распознать речь";
      try { const body = (await response.json()) as { detail?: string }; message = russianMessage(body.detail, message); } catch {}
      throw new ApiError(message, response.status);
    }
    return ((await response.json()) as { text: string }).text;
  },
  async trial(token: string): Promise<{ enabled: boolean; limit: number; used: number; remaining: number | null; status: string }> {
    const response = await agentFetch(token, `${agentsBaseUrl()}/api/v1/buyer-agent/trial`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new ApiError("Не удалось проверить пробный доступ. Ручное заполнение доступно.", response.status);
    return response.json();
  },
  async analyze(
    token: string,
    requestText: string,
    files: File[],
    route: "local" | "complex_auto",
    companyId?: string,
    intentScope = "default",
    externalContextAllowed = false,
  ): Promise<AgentRun> {
    const fileHashes = await Promise.all(files.map(async (file) => [file.name, file.type, Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await file.arrayBuffer()))).map((value) => value.toString(16).padStart(2, "0")).join("")]));
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(externalContextAllowed ? [intentScope, companyId, requestText, route, fileHashes, true] : [intentScope, companyId, requestText, route, fileHashes])));
    const storageKey = "porukam:analysis:" + Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, "0")).join("");
    const requestKey = sessionStorage.getItem(storageKey) ?? crypto.randomUUID();
    sessionStorage.setItem(storageKey, requestKey);
    const form = new FormData();
    form.set("request_key", requestKey);
    form.set("request_text", requestText);
    form.set("route", route);
    form.set("external_context_allowed", String(externalContextAllowed));
    if (companyId) form.set("company_id", companyId);
    files.forEach((file) => form.append("files", file));
    let run = await readResponse(await agentFetch(token, `${agentsBaseUrl()}/api/v3/buyer-agent/runs`, {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form,
    }));
    // A replay can arrive while the first request is still processing.
    for (let attempt = 0; ["received", "processing_sources", "extracting_requirements", "extracting", "matching", "explaining"].includes(run.state) && attempt < 90; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      run = await agents.getRun(token, run.id);
    }
    if (["received", "processing_sources", "extracting_requirements", "extracting", "matching", "explaining"].includes(run.state)) throw new ApiError("Разбор ещё выполняется. Повторите запрос позже: новый сценарий не будет списан.", 503);
    if (run.state === "failed") { sessionStorage.removeItem(storageKey); throw new ApiError(russianMessage(run.error, "Разбор не завершён; пробный сценарий не списан."), 503); }
    return run;
  },

  async clarify(
    token: string,
    runId: string,
    answers: Record<string, FactValue>,
    revision: number,
  ): Promise<AgentRun> {
    return readResponse(
      await agentFetch(token, `${agentsBaseUrl()}/api/v2/agent-runs/${runId}/clarify`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ answers, expected_revision: revision }),
      }),
    );
  },

  async confirm(token: string, runId: string, revision: number): Promise<AgentRun> {
    return readResponse(
      await agentFetch(token, `${agentsBaseUrl()}/api/v2/agent-runs/${runId}/confirm`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: revision }),
      }),
    );
  },

  async explainSellerMatch(
    token: string,
    companyId: string,
    category: string,
    requirements: Record<string, FactValue>,
  ): Promise<SellerExplanation> {
    const response = await agentFetch(token, `${agentsBaseUrl()}/api/v1/seller-agent/explain`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ company_id: companyId, category, requirements }),
    });
    if (!response.ok) {
      let message = `Не удалось объяснить совпадение: ${response.status}`;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string") message = russianMessage(body.detail, message);
      } catch {
        // Оставляем стандартное сообщение.
      }
      throw new ApiError(message, response.status);
    }
    return (await response.json()) as SellerExplanation;
  },
};

export const PROPERTY_STATUS_LABELS: Record<PropertyStatus, string> = {
  confirmed: "Подтверждено",
  assumed: "Предполагается",
  needs_clarification: "Нужно уточнить",
};
