import { ApiError, clearToken } from "./api";
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
  company_id: string;
  company_name: string;
  score: number;
  reasons: string[];
}

export interface BuyerAgentResult {
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

async function readResponse(response: Response): Promise<AgentRun> {
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      clearToken();
      window.location.assign("/login");
    }
    let message = `Ошибка анализа: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Оставляем безопасное стандартное сообщение.
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as AgentRun;
}

export const agents = {
  async analyze(
    token: string,
    requestText: string,
    files: File[],
    route: "local" | "complex_auto",
    companyId?: string,
  ): Promise<AgentRun> {
    const form = new FormData();
    form.set("request_text", requestText);
    form.set("route", route);
    if (companyId) form.set("company_id", companyId);
    files.forEach((file) => form.append("files", file));
    return readResponse(
      await fetch(`${agentsBaseUrl()}/api/v1/buyer-agent/runs`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      }),
    );
  },

  async clarify(
    token: string,
    runId: string,
    answers: Record<string, FactValue>,
  ): Promise<AgentRun> {
    return readResponse(
      await fetch(`${agentsBaseUrl()}/api/v1/agent-runs/${runId}/clarify`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ answers }),
      }),
    );
  },

  async confirm(token: string, runId: string): Promise<AgentRun> {
    return readResponse(
      await fetch(`${agentsBaseUrl()}/api/v1/agent-runs/${runId}/confirm`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  },

  async explainSellerMatch(
    token: string,
    companyId: string,
    category: string,
    requirements: Record<string, FactValue>,
  ): Promise<SellerExplanation> {
    const response = await fetch(`${agentsBaseUrl()}/api/v1/seller-agent/explain`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ company_id: companyId, category, requirements }),
    });
    if (!response.ok) {
      if (response.status === 401 && typeof window !== "undefined") {
        clearToken();
        window.location.assign("/login");
      }
      let message = `Не удалось объяснить совпадение: ${response.status}`;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string") message = body.detail;
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
