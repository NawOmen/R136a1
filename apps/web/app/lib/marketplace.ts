// Клиент marketplace-сервиса (этап 3). Аутентификация — тот же JWT Bearer, что и у
// gateway-auth: токен хранится в localStorage ("token") и передаётся в каждый запрос.
// Базовый URL задаётся через NEXT_PUBLIC_MARKETPLACE_URL.

import { ApiError, handleUnauthorized } from "./api";

// Тот же класс ошибок, что у gateway-auth — страницы ловят единый тип.
export { ApiError };

const MARKETPLACE_BASE_URL = process.env.NEXT_PUBLIC_MARKETPLACE_URL || "http://localhost:8002";

// ---------- Типы домена ----------

export type NeedVisibility = "open_anonymized" | "selected_producers" | "closed";
export type NeedStatus =
  | "draft"
  | "needs_clarification"
  | "confirmed"
  | "open_for_offers"
  | "waiting_for_match"
  | "coalition_candidate"
  | "awaiting_approvals"
  | "matched"
  | "cancelled"
  | "expired";
export type OfferStatus = "sent" | "selected" | "rejected";
export type DealStatus = "created";

export interface DeliveryAddress {
  id: string;
  company_id: string;
  address: string;
  city: string;
  region: string;
  is_default: boolean;
}

export interface ProductionProfile {
  company_id: string;
  production_site_address: string | null;
  region: string | null;
  about: string | null;
}

export interface Product {
  id: string;
  company_id: string;
  name: string;
  category: string;
  characteristics: Record<string, unknown>;
  price_rub: number;
  moq_units: number;
  lead_time_days: number;
  is_published: boolean;
}

export interface CapacityEntry {
  /** Дата в формате YYYY-MM-DD. */
  date: string;
  available_units: number;
}

export interface Document {
  id: string;
  company_id: string;
  name: string;
  document_type: string;
  file_key: string;
  content_type: string;
}

export interface CapabilityPassport {
  company_id: string;
  technologies: string[];
  equipment: string[];
  materials: string[];
  size_ranges: Record<string, [number, number]>;
  tolerances: string | null;
  certifications: string[];
  min_order_units: number | null;
  max_order_units: number | null;
  delivery_regions: string[];
  completed_order_types: string[];
}

export interface NeedFile {
  id: string;
  file_name: string;
  content_type: string;
}

export interface Need {
  id: string;
  company_id: string;
  created_by_user_id: string | null;
  category: string;
  characteristics: Record<string, unknown>;
  volume_units: number;
  budget_rub: number | null;
  deadline_date: string;
  delivery_address_id: string | null;
  visibility: NeedVisibility;
  status: NeedStatus;
  valid_until: string | null;
  no_match_reason: string | null;
  confirmed_at: string | null;
  files: NeedFile[];
}

export interface NeedFeedItem {
  id: string;
  category: string;
  characteristics: Record<string, unknown>;
  volume_units: number;
  deadline_date: string;
  visibility: NeedVisibility;
  status: NeedStatus;
  valid_until: string | null;
}

export interface Offer {
  id: string;
  need_id: string;
  company_id: string;
  created_by_user_id: string | null;
  price_rub: number;
  available_units: number;
  lead_time_days: number;
  delivery_cost_rub: number;
  moq_units: number;
  price_tiers: { min_units: number; unit_price_rub: number }[];
  valid_until: string | null;
  status: OfferStatus;
}

export interface OptimizationVariant {
  id: string;
  need_id: string;
  kind: "cheapest" | "balanced" | "reliable";
  input_hash: string;
  result: {
    title: string;
    feasible: boolean;
    total_units: number;
    total_cost_rub: number;
    max_lead_time_days: number;
    reliability_score: number;
    reasons: string[];
    allocations: {
      company_id: string;
      units: number;
      unit_price_rub: number;
      total_cost_rub: number;
    }[];
  };
}

export interface MarketOpportunity {
  id: string;
  company_id: string;
  category: string;
  score: number;
  competition_level: string;
  saturation_risk: string;
  unmet_volume_units: number | null;
  buyers_count: number;
  reasons: string[];
  missing_data: string[];
  status: string;
}

export interface GroupOffer {
  id: string;
  coalition_id: string;
  company_id: string;
  opportunity_id: string | null;
  min_total_units: number | null;
  max_total_units: number | null;
  price_tiers: { min_units: number; unit_price_rub: number }[];
  production_start: string | null;
  production_end: string | null;
  fill_deadline: string | null;
  non_fill_rule: string | null;
  status: string;
  seller_approval_status: string;
}

export interface CoalitionMember {
  need_id: string;
  buyer_company_id: string | null;
  units: number;
  individual_operations: Record<string, unknown>;
  common_cost_rub: number | null;
  individual_cost_rub: number | null;
  delivery_cost_rub: number | null;
  total_cost_rub: number | null;
  baseline_cost_rub: number | null;
  benefit_rub: number | null;
  approval_status: string;
}

export interface Coalition {
  id: string;
  producer_company_id: string | null;
  category: string;
  combined_volume_units: number;
  target_moq_units: number | null;
  status: string;
  version: number;
  explanation: string[];
  members: CoalitionMember[];
  group_offer: GroupOffer | null;
}

export interface PublishGroupOfferInput {
  min_total_units: number;
  max_total_units: number;
  available_capacity_units: number;
  price_tiers: { min_units: number; unit_price_rub: number }[];
  production_start: string;
  production_end: string;
  fill_deadline: string;
  non_fill_rule: "extend_with_approval" | "recalculate" | "close_without_obligations";
  participant_terms: {
    need_id: string;
    individual_operations_cost_rub: number;
    delivery_cost_rub: number;
    individual_baseline_cost_rub: number | null;
    delivery_days: number;
  }[];
}

export interface Deal {
  id: string;
  offer_id: string;
  need_id: string;
  buyer_company_id: string;
  seller_company_id: string;
  units: number;
  total_price_rub: number;
  status: DealStatus;
}

export interface Notification {
  id: string;
  user_id: string;
  message: string;
  type: string;
  is_read: boolean;
}

// ---------- Входные данные ----------

export interface CreateAddressInput {
  address: string;
  city: string;
  region: string;
  is_default: boolean;
}

export interface UpdateProductionProfileInput {
  production_site_address: string;
  region: string;
  about: string;
}

export interface CreateProductInput {
  name: string;
  category: string;
  characteristics: Record<string, unknown>;
  price_rub: number;
  moq_units: number;
  lead_time_days: number;
}

export type UpdateProductInput = Partial<CreateProductInput>;

export interface CreateNeedInput {
  company_id: string;
  category: string;
  characteristics: Record<string, unknown>;
  volume_units: number;
  budget_rub: number;
  deadline_date: string;
  delivery_address_id: string;
  visibility: NeedVisibility;
  valid_until?: string;
}

export interface CreateOfferInput {
  company_id: string;
  price_rub: number;
  available_units: number;
  lead_time_days: number;
  delivery_cost_rub?: number;
  moq_units?: number;
  price_tiers?: { min_units: number; unit_price_rub: number }[];
  valid_until?: string;
}

export interface UpdateCapabilityPassportInput {
  technologies: string[];
  equipment: string[];
  materials: string[];
  size_ranges: Record<string, [number, number]>;
  tolerances: string;
  certifications: string[];
  min_order_units: number;
  max_order_units: number;
  delivery_regions: string[];
  completed_order_types: string[];
}

// ---------- Подписи статусов (русский язык) ----------

export const NEED_STATUS_LABELS: Record<NeedStatus, string> = {
  draft: "Черновик",
  needs_clarification: "Нужно уточнение",
  confirmed: "Подтверждена",
  open_for_offers: "Открыта для предложений",
  waiting_for_match: "Ожидает подходящего варианта",
  coalition_candidate: "Найдена совместимая группа",
  awaiting_approvals: "Ожидает подтверждений участников",
  matched: "Сделка заключена",
  cancelled: "Отменена",
  expired: "Истекла",
};

export const OFFER_STATUS_LABELS: Record<OfferStatus, string> = {
  sent: "Отправлено",
  selected: "Выбрано",
  rejected: "Отклонено",
};

export const DEAL_STATUS_LABELS: Record<DealStatus, string> = {
  created: "Создана",
};

export const NEED_VISIBILITY_LABELS: Record<NeedVisibility, string> = {
  open_anonymized: "Открытая (анонимизированная)",
  selected_producers: "Для выбранных производителей",
  closed: "Закрытая",
};

export const PRODUCT_CATEGORIES = [
  "бумажные стаканы",
  "бумажные тарелки",
  "бумажные пакеты",
  "упаковка для еды",
  "прочее",
];

export const DOCUMENT_TYPES: { value: string; label: string }[] = [
  { value: "certificate", label: "Сертификат" },
  { value: "declaration", label: "Декларация соответствия" },
  { value: "test_report", label: "Протокол испытаний" },
  { value: "other", label: "Прочее" },
];

const CHARACTERISTIC_LABELS: Record<string, string> = {
  volume_ml: "Объём, мл",
  coating: "Покрытие",
  material: "Материал",
  color: "Цвет",
  height_mm: "Высота, мм",
  diameter_mm: "Диаметр, мм",
};

export function characteristicLabel(key: string): string {
  return CHARACTERISTIC_LABELS[key] ?? key;
}

export function formatCharacteristics(characteristics: Record<string, unknown>): string {
  const entries = Object.entries(characteristics);
  if (entries.length === 0) return "—";
  return entries.map(([key, value]) => `${characteristicLabel(key)}: ${String(value)}`).join(" · ");
}

export function formatRub(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value) + " ₽";
}

export function formatUnits(value: number): string {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value) + " шт.";
}

// ---------- Разбор ошибок валидации FastAPI (422) ----------

const FIELD_LABELS: Record<string, string> = {
  company_id: "Компания",
  category: "Категория",
  characteristics: "Характеристики",
  volume_units: "Объём",
  budget_rub: "Бюджет",
  deadline_date: "Срок выполнения",
  delivery_address_id: "Адрес доставки",
  visibility: "Видимость",
  name: "Название",
  price_rub: "Цена",
  moq_units: "Минимальный объём заказа",
  lead_time_days: "Срок производства",
  is_published: "Публикация",
  published: "Публикация",
  address: "Адрес",
  city: "Город",
  region: "Регион",
  is_default: "Основной адрес",
  production_site_address: "Адрес производства",
  about: "О компании",
  entries: "Записи мощности",
  date: "Дата",
  available_units: "Доступный объём",
  file: "Файл",
  document_type: "Тип документа",
  technologies: "Технологии",
  equipment: "Оборудование",
  materials: "Материалы",
  size_ranges: "Диапазоны размеров",
  tolerances: "Допуски",
  certifications: "Сертификации",
  min_order_units: "Минимальный заказ",
  max_order_units: "Максимальный заказ",
  delivery_regions: "Регионы доставки",
  completed_order_types: "Типы выполненных заказов",
  files: "Файлы",
};

interface ValidationErrorItem {
  loc?: unknown[];
  msg?: string;
  ctx?: { min_length?: number };
}

function describeValidationError(item: ValidationErrorItem): string {
  const loc = Array.isArray(item.loc) ? item.loc : [];
  const field = String(loc[loc.length - 1] ?? "");
  const label = FIELD_LABELS[field] ?? field;
  const msg = item.msg ?? "";

  if (msg.toLowerCase().includes("at least")) {
    const min = item.ctx?.min_length;
    return min ? `«${label}» должно быть не короче ${min} символов` : `«${label}» слишком короткое`;
  }
  if (msg.toLowerCase().includes("string type")) {
    return `«${label}» должно быть строкой`;
  }
  if (label) {
    return `«${label}»: ${msg}`;
  }
  return msg;
}

// ---------- HTTP ----------

type RequestOptions = RequestInit & { token?: string | null };

async function marketplaceFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { token, ...init } = options;
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  // Для multipart браузер сам выставляет Content-Type с границей.
  if (init.body !== undefined && !isFormData) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${MARKETPLACE_BASE_URL}${path}`, { ...init, headers });

  if (!response.ok) {
    if (response.status === 401) handleUnauthorized();
    let message = `Ошибка запроса: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        message = body.detail
          .map((item) => describeValidationError(item as ValidationErrorItem))
          .join("; ");
      }
    } catch {
      // тело ответа не JSON — оставляем стандартное сообщение
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function marketplaceFetchBlob(path: string, token: string): Promise<Blob> {
  const response = await fetch(`${MARKETPLACE_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    if (response.status === 401) handleUnauthorized();
    let message = `Ошибка запроса: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Не-JSON ответ — оставляем стандартное сообщение.
    }
    throw new ApiError(message, response.status);
  }
  return response.blob();
}

// Списочные эндпоинты могут возвращать как голый массив, так и обёртку
// вида { products: [...] } — нормализуем оба варианта.
function unwrapList<T>(body: unknown, keys: string[]): T[] {
  if (Array.isArray(body)) return body as T[];
  if (body !== null && typeof body === "object") {
    const record = body as Record<string, unknown>;
    for (const key of keys) {
      if (Array.isArray(record[key])) return record[key] as T[];
    }
  }
  return [];
}

// ---------- Эндпоинты ----------

export const marketplace = {
  // Публичный каталог (без Bearer)
  getCatalog(): Promise<Product[]> {
    return marketplaceFetch("/api/v1/products", {}).then((body) => unwrapList<Product>(body, ["products", "items"]));
  },

  // Адреса доставки
  getAddresses(token: string, companyId: string): Promise<DeliveryAddress[]> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/addresses`, { token }).then((body) =>
      unwrapList<DeliveryAddress>(body, ["addresses", "items"]),
    );
  },

  createAddress(token: string, companyId: string, input: CreateAddressInput): Promise<DeliveryAddress> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/addresses`, {
      method: "POST",
      token,
      body: JSON.stringify(input),
    });
  },

  updateAddress(
    token: string,
    companyId: string,
    addressId: string,
    input: Partial<CreateAddressInput>,
  ): Promise<DeliveryAddress> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/addresses/${addressId}`, {
      method: "PATCH",
      token,
      body: JSON.stringify(input),
    });
  },

  deleteAddress(token: string, companyId: string, addressId: string): Promise<void> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/addresses/${addressId}`, {
      method: "DELETE",
      token,
    });
  },

  // Производственный профиль
  getProductionProfile(token: string, companyId: string): Promise<ProductionProfile> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/production-profile`, { token });
  },

  updateProductionProfile(
    token: string,
    companyId: string,
    input: UpdateProductionProfileInput,
  ): Promise<ProductionProfile> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/production-profile`, {
      method: "PUT",
      token,
      body: JSON.stringify(input),
    });
  },

  // Товары
  getCompanyProducts(token: string, companyId: string): Promise<Product[]> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/products`, { token }).then((body) =>
      unwrapList<Product>(body, ["products", "items"]),
    );
  },

  createProduct(token: string, companyId: string, input: CreateProductInput): Promise<Product> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/products`, {
      method: "POST",
      token,
      body: JSON.stringify(input),
    });
  },

  updateProduct(token: string, productId: string, input: UpdateProductInput): Promise<Product> {
    return marketplaceFetch(`/api/v1/products/${productId}`, {
      method: "PATCH",
      token,
      body: JSON.stringify(input),
    });
  },

  setProductPublished(token: string, productId: string, published: boolean): Promise<Product> {
    return marketplaceFetch(`/api/v1/products/${productId}/publish`, {
      method: "POST",
      token,
      body: JSON.stringify({ published }),
    });
  },

  // Мощности
  getCapacity(token: string, companyId: string, from?: string, to?: string): Promise<CapacityEntry[]> {
    const query = from || to ? `?from=${from ?? ""}&to=${to ?? ""}` : "";
    return marketplaceFetch(`/api/v1/companies/${companyId}/capacity${query}`, { token }).then((body) =>
      unwrapList<CapacityEntry>(body, ["entries", "items"]),
    );
  },

  updateCapacity(token: string, companyId: string, entries: CapacityEntry[]): Promise<CapacityEntry[]> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/capacity`, {
      method: "PUT",
      token,
      body: JSON.stringify({ entries }),
    }).then((body) => unwrapList<CapacityEntry>(body, ["entries", "items"]));
  },

  // Документы
  getDocuments(token: string, companyId: string): Promise<Document[]> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/documents`, { token }).then((body) =>
      unwrapList<Document>(body, ["documents", "items"]),
    );
  },

  uploadDocument(
    token: string,
    companyId: string,
    file: File,
    name: string,
    documentType: string,
  ): Promise<Document> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("name", name);
    formData.append("document_type", documentType);
    return marketplaceFetch(`/api/v1/companies/${companyId}/documents`, {
      method: "POST",
      token,
      body: formData,
    });
  },

  deleteDocument(token: string, documentId: string): Promise<void> {
    return marketplaceFetch(`/api/v1/documents/${documentId}`, { method: "DELETE", token });
  },

  // Capability Passport
  getCapabilityPassport(token: string, companyId: string): Promise<CapabilityPassport> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/capability-passport`, { token });
  },

  updateCapabilityPassport(
    token: string,
    companyId: string,
    input: UpdateCapabilityPassportInput,
  ): Promise<CapabilityPassport> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/capability-passport`, {
      method: "PUT",
      token,
      body: JSON.stringify(input),
    });
  },

  // Потребности
  getMyNeeds(token: string): Promise<Need[]> {
    return marketplaceFetch("/api/v1/needs/mine", { token }).then((body) =>
      unwrapList<Need>(body, ["needs", "items"]),
    );
  },

  getNeedsFeed(token: string, sellerCompanyId: string): Promise<NeedFeedItem[]> {
    return marketplaceFetch(`/api/v1/needs?seller_company_id=${sellerCompanyId}`, { token }).then((body) =>
      unwrapList<NeedFeedItem>(body, ["needs", "items"]),
    );
  },

  createNeed(token: string, input: CreateNeedInput): Promise<Need> {
    return marketplaceFetch("/api/v1/needs", { method: "POST", token, body: JSON.stringify(input) });
  },

  publishNeed(token: string, needId: string): Promise<Need> {
    return marketplaceFetch(`/api/v1/needs/${needId}/publish`, { method: "POST", token });
  },

  getNeed(token: string, needId: string): Promise<Need> {
    return marketplaceFetch(`/api/v1/needs/${needId}`, { token });
  },

  uploadNeedFile(token: string, needId: string, file: File): Promise<Need> {
    const formData = new FormData();
    formData.append("file", file);
    return marketplaceFetch(`/api/v1/needs/${needId}/files`, {
      method: "POST",
      token,
      body: formData,
    });
  },

  downloadNeedFile(token: string, fileId: string): Promise<Blob> {
    return marketplaceFetchBlob(`/api/v1/need-files/${fileId}/download`, token);
  },

  cancelNeed(token: string, needId: string): Promise<Need> {
    return marketplaceFetch(`/api/v1/needs/${needId}/cancel`, { method: "POST", token });
  },

  // Предложения
  getOffers(token: string, needId: string): Promise<Offer[]> {
    return marketplaceFetch(`/api/v1/needs/${needId}/offers`, { token }).then((body) =>
      unwrapList<Offer>(body, ["offers", "items"]),
    );
  },

  createOffer(token: string, needId: string, input: CreateOfferInput): Promise<Offer> {
    return marketplaceFetch(`/api/v1/needs/${needId}/offers`, {
      method: "POST",
      token,
      body: JSON.stringify(input),
    });
  },

  optimizeNeed(token: string, needId: string): Promise<OptimizationVariant[]> {
    return marketplaceFetch(`/api/v1/needs/${needId}/optimize`, { method: "POST", token }).then((body) =>
      unwrapList<OptimizationVariant>(body, ["variants", "items"]),
    );
  },

  getMarketOpportunities(token: string, companyId: string): Promise<MarketOpportunity[]> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/market-opportunities`, { token }).then((body) =>
      unwrapList<MarketOpportunity>(body, ["opportunities", "items"]),
    );
  },

  prepareGroupOffer(token: string, opportunityId: string): Promise<GroupOffer> {
    return marketplaceFetch(`/api/v1/opportunities/${opportunityId}/prepare-offer`, {
      method: "POST",
      token,
    });
  },

  publishGroupOffer(token: string, groupOfferId: string, input: PublishGroupOfferInput): Promise<Coalition> {
    return marketplaceFetch(`/api/v1/group-offers/${groupOfferId}/publish`, {
      method: "POST",
      token,
      body: JSON.stringify(input),
    });
  },

  getCoalitions(token: string): Promise<Coalition[]> {
    return marketplaceFetch("/api/v1/coalitions/mine", { token }).then((body) =>
      unwrapList<Coalition>(body, ["coalitions", "items"]),
    );
  },

  decideCoalition(
    token: string,
    coalitionId: string,
    companyId: string,
    decision: "approved" | "rejected",
  ): Promise<Coalition> {
    return marketplaceFetch(`/api/v1/coalitions/${coalitionId}/decision`, {
      method: "POST",
      token,
      body: JSON.stringify({ company_id: companyId, decision }),
    });
  },

  // Сделка (покупатель выбирает предложение)
  selectOffer(token: string, offerId: string): Promise<Deal> {
    return marketplaceFetch(`/api/v1/offers/${offerId}/select`, { method: "POST", token });
  },

  // Уведомления
  getNotifications(token: string): Promise<Notification[]> {
    return marketplaceFetch("/api/v1/notifications", { token }).then((body) =>
      unwrapList<Notification>(body, ["notifications", "items"]),
    );
  },

  markNotificationRead(token: string, notificationId: string): Promise<Notification> {
    return marketplaceFetch(`/api/v1/notifications/${notificationId}/read`, { method: "POST", token });
  },

  markAllNotificationsRead(token: string): Promise<void> {
    return marketplaceFetch("/api/v1/notifications/read-all", { method: "POST", token });
  },
};
