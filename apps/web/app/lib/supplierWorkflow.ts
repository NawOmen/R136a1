import { marketplaceFetch, marketplaceFetchBlob, type Money } from "./marketplace";
import { ApiError, handleUnauthorized } from "./api";
import { serviceUrl } from "./serviceUrl";
import { russianFetch, russianMessage } from "./russianMessages";

export type SupplierStatus = "draft" | "sent" | "replied" | "selected";
export type PriceBasis = "unknown" | "unit" | "total";
export const SUPPLIER_STATUS: Record<SupplierStatus, string> = { draft: "Черновик", sent: "Отправлено", replied: "Получен ответ", selected: "Выбрано" };
export interface SupplierRequest {
  id: string; need_id: string; need_revision: number; buyer_company_id: string; seller_company_id: string;
  buyer_name: string; seller_name: string; specification: { category: string; subcategory: string | null; characteristics: Record<string, unknown>; quantity: number; unit: string; deadline_date: string };
  status: SupplierStatus; revision: number; quoted_price_rub: Money | null; price_basis: PriceBasis;
  lead_time_days: number | null; delivery_date: string | null; note: string; sent_at: string | null; updated_at: string;
}
export interface SupplierCandidate { company_id: string; company_name: string; specialization: string[]; relevant: boolean; products: string[] }
export interface SupplierMessage { id: string; author_company_id: string; message: string; created_at: string }
export interface SupplierFile { id: string; file_name: string; content_type: string; content_hash: string; created_at: string }
export interface QuoteProposal {
  price_rub: string | null; price_basis: PriceBasis; price_evidence: string;
  lead_time_days: number | null; lead_time_evidence: string; delivery_date: string | null; date_evidence: string;
  request_revision: number; file_id: string; content_hash: string; warnings: string[];
}
export interface SupplierUpdate {
  company_id: string; expected_revision: number; status: SupplierStatus; quoted_price_rub: Money | null;
  price_basis: PriceBasis; lead_time_days: number | null; delivery_date: string | null; note: string; human_approved: true;
}
const path = (id: string) => `/api/v3/supplier-requests/${encodeURIComponent(id)}`;
async function assist<T>(token: string, action: string, body: unknown): Promise<T> {
  const response = await russianFetch(`${serviceUrl(process.env.NEXT_PUBLIC_LLM_GATEWAY_URL, 8003)}/api/v1/procurement-assistant/${action}`, {
    method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401) handleUnauthorized(token);
    const data = await response.json().catch(() => ({}));
    throw new ApiError(russianMessage(typeof data.detail === "string" ? data.detail : "Локальный ИИ недоступен. Повторите попытку или заполните вручную."), response.status);
  }
  return response.json();
}
export const supplierWorkflow = {
  candidates: (token: string, needId: string, companyId: string) => marketplaceFetch<SupplierCandidate[]>(`/api/v3/needs/${needId}/suppliers?company_id=${companyId}`, { token }),
  list: (token: string, companyId: string, needId?: string, role: "buyer" | "seller" = "buyer") => marketplaceFetch<SupplierRequest[]>(`/api/v3/supplier-requests?company_id=${companyId}&role=${role}${needId ? `&need_id=${needId}` : ""}`, { token }),
  create: (token: string, needId: string, companyId: string, sellerId: string, revision: number) => marketplaceFetch<SupplierRequest>(`/api/v3/needs/${needId}/supplier-requests`, { token, method: "POST", body: JSON.stringify({ company_id: companyId, seller_company_id: sellerId, expected_need_revision: revision }) }),
  update: (token: string, id: string, data: SupplierUpdate) => marketplaceFetch<SupplierRequest>(path(id), { token, method: "PATCH", body: JSON.stringify(data) }),
  messages: (token: string, id: string, companyId: string) => marketplaceFetch<SupplierMessage[]>(`${path(id)}/messages?company_id=${companyId}`, { token }),
  send: (token: string, id: string, companyId: string, message: string, revision: number, key: string) => marketplaceFetch<SupplierMessage>(`${path(id)}/messages`, { token, method: "POST", body: JSON.stringify({ company_id: companyId, message, expected_revision: revision, request_key: key, human_approved: true }) }),
  files: (token: string, id: string, companyId: string) => marketplaceFetch<SupplierFile[]>(`${path(id)}/files?company_id=${companyId}`, { token }),
  upload: (token: string, id: string, companyId: string, file: File) => { const body = new FormData(); body.append("file", file); return marketplaceFetch<SupplierFile>(`${path(id)}/files?company_id=${companyId}`, { token, method: "POST", body }); },
  download: (token: string, id: string, companyId: string, fileId: string) => marketplaceFetchBlob(`${path(id)}/files/${fileId}?company_id=${companyId}`, token),
  draft: (token: string, row: SupplierRequest, companyId: string, mode: "rfq" | "reply", guidance: string) => assist<{ text: string; request_revision: number; warnings?: string[] }>(token, "draft", { company_id: companyId, request_id: row.id, expected_revision: row.revision, mode, guidance }),
  extract: (token: string, row: SupplierRequest, companyId: string, fileId: string) => assist<QuoteProposal>(token, "extract-reply", { company_id: companyId, request_id: row.id, expected_revision: row.revision, file_id: fileId }),
};

export function updateValues(row: SupplierRequest, status: SupplierStatus = row.status): SupplierUpdate {
  return { company_id: row.buyer_company_id, expected_revision: row.revision, status, quoted_price_rub: row.quoted_price_rub, price_basis: row.price_basis, lead_time_days: row.lead_time_days, delivery_date: row.delivery_date, note: row.note, human_approved: true };
}
export function saveDownload(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob), anchor = document.createElement("a");
  anchor.href = url; anchor.download = name; document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
