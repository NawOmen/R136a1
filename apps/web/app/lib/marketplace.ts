import { russianUnit } from "./units";
export { russianUnit } from "./units";
import { russianLabel, displayValue } from "./presentation";
import { russianFetch, russianMessage, validationMessage } from "./russianMessages";
import { displayMoney, type Money } from "./money";
export type { Money } from "./money";
// Клиент marketplace-сервиса (этап 3). Аутентификация — тот же JWT Bearer, что и у
// gateway-auth: токен хранится в localStorage ("token") и передаётся в каждый запрос.
// Базовый URL задаётся через NEXT_PUBLIC_MARKETPLACE_URL.

import { ApiError, handleUnauthorized } from "./api";
import { serviceUrl } from "./serviceUrl";
import categoryRegistry from "./category-registry.generated.json";
import { registryCharacteristicLabel } from "./categoryProfiles";

// Тот же класс ошибок, что у gateway-auth — страницы ловят единый тип.
export { ApiError };

const marketplaceBaseUrl = () => serviceUrl(process.env.NEXT_PUBLIC_MARKETPLACE_URL, 8002);

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
export type OfferStatus = "sent" | "selected" | "rejected" | "stale";
export type DealStatus = "created" | "in_production" | "partially_shipped" | "shipped" | "delivered" | "partially_accepted" | "fulfilled" | "cancelled" | "returned";

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

export interface CategoryProfileSnapshot {
  snapshot_version: number;
  registry_version: string;
  category_id: string;
  leaf_revision: number;
  profile_version: number;
  state: string;
  fields: Record<string, { label: string; type: string; aliases: string[]; unit?: string; positive?: boolean; max_length?: number }>;
  required_for_product: string[];
  passport?: Record<string, unknown>;
}

export interface PackagingDefinition {from_unit:string;to_unit:string;factor:number;specification_hash:string;review_hash:string}
export interface Product {
  quantity_conversion?: PackagingDefinition | null;
  id: string;
  company_id: string;
  revision: number;
  external_id: string | null;
  sources: ProductSource[];
  name: string;
  category: string;
  subcategory: string | null;
  category_profile?: CategoryProfileSnapshot | null;
  characteristics: Record<string, unknown>;
  price_rub: Money;
  price_tiers: ProductPriceTier[];
  moq_units: number;
  lead_time_days: number;
  /** Остаток на складе: нужен для роли «поставка со склада». */
  stock_units: number | null;
  stock_updated_at: string | null;
  is_published: boolean;
  images: ProductImage[];
}

export interface ProductImage { id: string; file_name: string; content_type: string; position: number }
export function primaryProductImage(images: ProductImage[]): ProductImage | undefined {
  return images.find(image => !image.file_name?.startsWith("Схематическая иллюстрация:") && !image.file_name?.startsWith("Иллюстрация товара:"))
    ?? images.find(image => image.file_name?.startsWith("Иллюстрация товара:"));
}
export interface ProductSource { label: string; reference: string }
export interface ProductPriceTier { min_units: number; unit_price_rub: Money }
export interface SellerAnalytics { company_id: string; products_total: number; products_published: number; deals_total: number; sold_units: number; revenue_rub: Money | null; available_capacity_units: number; capacity_utilization_pct: number | null }
export interface DealMessage { id: string; deal_id: string; author_user_id: string; author_company_id: string; message: string; created_at: string }
export interface PublicProducer { company_id: string; display_name: string; legal_form: string; region: string | null; about: string | null; production_site_address: string | null; has_photo: boolean; rating: number | null; reviews_count: number; capability_details?: CapabilityDetails | null }
export interface PublicProductDetail extends Product { producer: PublicProducer }
export interface DealCheckpoint { id: string; deal_id: string; kind: "production" | "shipment" | "delivery"; status: "pending" | "completed"; note: string | null; completed_at: string | null }
export interface DeliveryArrangement { id: string; deal_id: string; weight_kg: number; volume_m3: number; cargo_class: "small" | "medium" | "large" | "manual_review"; classification_note: string; method: "buyer_carrier" | "self_pickup" | "seller_delivery"; carrier_name: string | null; tracking_number: string | null; hazard_class: string | null; buyer_responsible: boolean }
export interface DealReview { id: string; deal_id: string; reviewer_company_id: string; reviewed_company_id: string; rating: number; comment: string; created_at: string }
export interface PriceIndexPoint { date: string; average_unit_price_rub: Money; offers_count: number }
export interface MarketWatch { id: string; category: string; demand_changes: boolean; supply_changes: boolean }
export interface BuyerSavings { company_id: string; confirmed_savings_rub: Money; calculated_variants_rub: Money; coalitions_count: number; explanation: string }
export interface RepeatPreview { changes: { field: string; was: string | null; now: string | null }[]; not_carried: string[]; warnings: string[] }
export interface NextStep { title: string; description: string; href: string }

export interface CapacityEntry {
  category_conversions?: {category_id: string; order_unit: string; resource_units_per_order_unit: number; profile_version?: number}[];
  conversions_approved?: boolean;
  reserved_units?: number;
  free_units?: number;
  /** Дата в формате YYYY-MM-DD. */
  date: string;
  category: string;
  unit: string;
  available_units: number;
}

export interface Document {
  id: string;
  company_id: string;
  name: string;
  document_type: string;
  file_key: string;
  content_type: string;
  verification_status: "unverified" | "verified" | "rejected";
  /** Область действия: без неё документ не считается доказательством допуска. */
  scope_category: string | null;
  scope_subcategory: string | null;
  valid_until: string | null;
  /** Подтверждённые проверяющим значения характеристик: материал, покрытие и так далее. */
  confirms: Record<string, string[]>;
  verified_by_user_id: string | null;
  verified_at: string | null;
  verification_note: string | null;
  created_at: string | null;
}

export interface PendingDocument extends Document {
  company_display_name: string | null;
}

export interface DocumentVerificationInput {
  decision: "verified" | "rejected" | "unverified";
  scope_category?: string | null;
  scope_subcategory?: string | null;
  valid_until?: string | null;
  confirms?: Record<string, string[]> | null;
  note?: string | null;
}

/** Состояние обязательного доказательства по категории. */
export interface RequirementStatus {
  code: string;
  title: string;
  legal_reference: string;
  blocking: boolean;
  state: string;
  state_label: string;
  seller_hint: string;
  buyer_note: string;
  document_ids: string[];
  /** Пояснение применимости: например, документ подтверждён для другой подкатегории. */
  scope_note?: string | null;
}

export interface CategoryAdmission {
  category: string;
  subcategory: string | null;
  state: string;
  state_label: string;
  supported: boolean;
  profile_title: string | null;
  summary: string;
  requirements: RequirementStatus[];
  advisories: string[];
  blocking_open: number;
  blocking_message: string;
  blocking_reasons?: string;
  checked_at: string;
  profile_key?: string | null;
  rules_version?: string;
}

export interface CategoryRequirements {
  category: string;
  subcategory: string | null;
  profile_title: string | null;
  supported: boolean;
  summary: string;
  checklist: RequirementStatus[];
  advisories: string[];
  note: string;
}

export interface ProductAdmissionChecklist {
  product_id: string;
  category: string;
  subcategory: string | null;
  state: string;
  state_label: string;
  supported: boolean;
  summary: string;
  checklist: RequirementStatus[];
  advisories: string[];
  note: string;
  checked_at: string;
}

export const ADMISSION_STATE_LABELS: Record<string, string> = {
  admitted: "Допуск подтверждён",
  blocked: "Доказательства не подтверждены",
  not_configured: "Обязательные доказательства не заданы",
  not_supported: "Категория не поддерживается",
  needs_classification: "Нужна классификация товара",
};

/** Характеристики, которые проверяющий сопоставляет с изделием. */
export const CONFIRMABLE_ATTRIBUTES: { value: string; label: string }[] = [
  { value: "material", label: "Материал" },
  { value: "coating", label: "Покрытие" },
  { value: "purpose", label: "Назначение" },
];

export interface CategoryCapability {
  category_id: string; unit: string; characteristics: Record<string, unknown[]>;
  min_units: number; max_units: number | null; profile_version?: number;
}
export interface CapabilityDetails {
  business_kind: "manufacturer" | "stock_supplier" | "both";
  category_scopes?: CategoryCapability[];
  product_types: string;
  complexity: string;
  material_grades: string;
  limitations: string;
  packaging: string;
  delivery: string;
  quality_control: string;
  trial_batch: string;
}

export interface CapabilityPassport {
  details: CapabilityDetails;
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

export interface NeedEditImpact {
  expected_revision: number;
  changes: Record<string, { before: unknown; after: unknown }>;
  affected: Record<string, string[]>;
  editable: boolean;
  requires_confirmation: boolean;
  impact_hash: string;
}

export interface NeedFile {
  id: string;
  file_name: string;
  content_type: string;
}

export interface Need {
  revision: number;
  requirement_decisions?: { field: string; confirmed_value: unknown }[];
  requirements_evidence?: { stale?: boolean; run?: { id: string; revision: number } | null; fields: Record<string, { value: unknown; original_value?: unknown; original_unit?: string | null; normalized_unit?: string | null; status: string; origin: string; confirmed_by_user_id: string; confirmed_at: string; sources: import("./agents").EvidenceItem[] }> } | null;
  id: string;
  company_id: string;
  created_by_user_id: string | null;
  category: string;
  subcategory?: string | null;
  category_profile?: CategoryProfileSnapshot | null;
  characteristics: Record<string, unknown>;
  volume_units: number;
  budget_rub: Money | null;
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
  revision: number;
  requirement_decisions?: Need["requirement_decisions"];
  id: string;
  category: string;
  subcategory?: string | null;
  category_profile?: CategoryProfileSnapshot | null;
  characteristics: Record<string, unknown>;
  volume_units: number;
  deadline_date: string;
  visibility: NeedVisibility;
  status: NeedStatus;
  valid_until: string | null;
}

export interface Offer {
  commercial_terms?: CommercialTerms | null;
  commercial_quote?: CommercialSnapshot | null;
  revision: number;
  request_key?: string | null;
  id: string;
  need_id: string;
  company_id: string;
  created_by_user_id: string | null;
  price_rub: Money;
  available_units: number;
  lead_time_days: number;
  delivery_cost_rub: Money | null;
  moq_units: number;
  price_tiers: { min_units: number; unit_price_rub: Money }[];
  valid_until: string | null;
  status: OfferStatus;
  /** Недостающие данные допуска на момент отправки (не блокируют). */
  sending_warnings?: string[];
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
    total_cost_rub: Money;
    max_lead_time_days: number;
    reliability_score: number | null;
    comparison_basis?: {tax_basis:string;vat_rate_pct:string|null;delivery_method:string;delivery_conditions:string|null};
    reasons: string[];
    allocations: {
      company_id: string;
      units: number;
      unit_price_rub: Money;
      total_cost_rub: Money;
    }[];
  };
}

export interface MarketOpportunity {
  id: string;
  company_id: string;
  category: string;
  unit: string;
  score: number;
  competition_level: string;
  saturation_risk: string;
  unmet_volume_units: number | null;
  buyers_count: number;
  reasons: string[];
  missing_data: string[];
  status: string;
  dismissal_reason?: string | null;
}

export interface GroupOffer {
  id: string;
  coalition_id: string;
  company_id: string;
  opportunity_id: string | null;
  min_total_units: number | null;
  max_total_units: number | null;
  price_tiers: { min_units: number; unit_price_rub: Money }[];
  production_start: string | null;
  production_end: string | null;
  fill_deadline: string | null;
  non_fill_rule: string | null;
  status: string;
  seller_approval_status: string;
}

export interface CoalitionMember {
  commercial_estimate?: CommercialEstimate | null;
  need_id: string;
  buyer_company_id: string | null;
  units: number;
  individual_operations: Record<string, unknown>;
  common_cost_rub: Money | null;
  individual_cost_rub: Money | null;
  delivery_cost_rub: Money | null;
  total_cost_rub: Money | null;
  baseline_cost_rub: Money | null;
  benefit_rub: Money | null;
  approval_status: string;
}

export interface Coalition {
  id: string;
  producer_company_id: string | null;
  category: string;
  unit: string;
  combined_volume_units: number;
  target_moq_units: number | null;
  status: string;
  version: number;
  explanation: string[];
  members: CoalitionMember[];
  group_offer: GroupOffer | null;
}

export interface PublishGroupOfferInput {
  shared_cost_rub?: Money;
  min_total_units: number;
  max_total_units: number;
  available_capacity_units: number;
  price_tiers: { min_units: number; unit_price_rub: Money }[];
  production_start: string;
  production_end: string;
  fill_deadline: string;
  non_fill_rule: "extend_with_approval" | "recalculate" | "close_without_obligations";
  participant_terms: { commercial_terms?: CommercialTerms | null; baseline_offer_id?: string | null;
    need_id: string;
    individual_operations_cost_rub: Money;
    delivery_cost_rub: Money | null;
    individual_baseline_cost_rub: Money | null;
    delivery_days: number;
  }[];
}

export interface Deal {
  commercial_snapshot?: CommercialSnapshot | null;
  id: string;
  offer_id: string;
  need_id: string;
  buyer_company_id: string;
  seller_company_id: string;
  units: number;
  total_price_rub: Money;
  status: DealStatus;
}

export interface ReserveCommitment {
  effective_tier: "hot" | "warm" | "cold";
  available_units: number;
  availability_reason: string | null;
  commercial_snapshot?: CommercialSnapshot | null;
  commercial_terms?: CommercialTerms | null;
  id: string;
  plan_id: string;
  company_id: string;
  offer_id: string | null;
  reserve_tier: "hot" | "warm" | "cold";
  confirmation_status: string;
  proposed_capacity_units: number | null;
  proposed_moq_units: number | null;
  proposed_unit_price_rub: Money | null;
  proposed_delivery_cost_rub: Money | null;
  proposed_lead_time_days: number | null;
  confirmed_capacity_units: number | null;
  confirmed_moq_units: number | null;
  confirmed_unit_price_rub: Money | null;
  confirmed_delivery_cost_rub: Money | null;
  confirmed_lead_time_days: number | null;
  held_until: string | null;
  switchover_days: number | null;
}

export interface ResilienceScenario {
  is_current: boolean;
  id: string;
  plan_id: string;
  scenario_type: string;
  failed_company_ids: string[];
  result: {
    failed_units: number;
    confirmed_covered_units: number;
    uncovered_units: number;
    unconfirmed_units: number;
    price_delta_rub: Money | null;
    price_delta_pct: number | null;
    cost_comparison_applicable: boolean;
    delay_days: number;
    auto_eligible: boolean;
    solver_status?: string;
    explanations: string[];
  };
  status: string;
  is_simulation: boolean;
}

export interface ResiliencePlan {
  commercial_snapshot?: { holding_quotes: CommercialSnapshot[]; reserve_holding_total_rub: Money; total_rub: Money } | null;
  id: string;
  need_id: string;
  baseline_variant_id: string;
  baseline_allocations: { company_id: string; units: number; total_cost_rub: Money; commercial_snapshot?: CommercialSnapshot | null }[];
  baseline_total_cost_rub: Money;
  baseline_lead_time_days: number;
  current_allocations: { company_id: string; units: number; total_cost_rub: Money; deal_id?: string; role?: string }[];
  current_total_cost_rub: Money;
  current_lead_time_days: number;
  max_price_increase_pct: number;
  max_delay_days: number;
  auto_replace_within_thresholds: boolean;
  failed_company_ids: string[];
  status: string;
  version: number;
  confirmed_at: string | null;
  reserves: ReserveCommitment[];
  scenarios: ResilienceScenario[];
}

export interface PrimaryObligation {
  plan_id: string;
  need_id: string;
  company_id: string;
  allocation: { company_id: string; units: number; total_cost_rub: Money };
  plan_status: string;
  confirmed_at: string | null;
}

export interface Notification {
  id: string;
  user_id: string;
  message: string;
  type: string;
  is_read: boolean;
}

export interface SupportTicket {
  id: string;
  user_id: string;
  company_id: string | null;
  subject: string;
  message: string;
  status: "new" | "in_progress" | "resolved" | "closed";
  admin_response: string | null;
  assigned_admin_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TrustKpi {
  scope: "company" | "marketplace";
  company_id: string | null;
  generated_from_events: number;
  buyer: Record<string, number>;
  seller: Record<string, number>;
  marketplace: Record<string, number>;
  baseline_note: string;
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

/** Строка предпросмотра импорта: diff со своей карточкой и решение загрузки. */
export interface ImportPreviewRow {
  line: number;
  product: CreateProductInput;
  import_status: "new" | "unchanged" | "changed" | "published_skipped";
  diff: { field: string; was: unknown; now: unknown }[];
  note: string;
  product_id: string | null;
  product_revision: number | null;
}
export interface ImportPreview {
  content_hash: string;
  rows: ImportPreviewRow[];
  errors: { line: number; message: string }[];
  created_ids: string[];
  updated_ids?: string[];
  import_id?: string;
}
export interface CreateProductInput {
  quantity_conversion_approved?: boolean;
  stock_units?: number | null;
  name: string;
  category: string;
  subcategory?: string | null;
  characteristics: Record<string, unknown>;
  sources?: ProductSource[];
  external_id?: string | null;
  price_rub: Money;
  price_tiers: ProductPriceTier[];
  moq_units: number;
  lead_time_days: number;
}

export type UpdateProductInput = Partial<CreateProductInput> & { expected_revision?: number };

export interface CreateNeedInput {
  agent_run_id?: string;
  agent_run_revision?: number;
  quantity_conversion_approved?: boolean;
  request_key?: string;
  company_id: string;
  category: string;
  subcategory?: string | null;
  characteristics: Record<string, unknown>;
  volume_units: number;
  budget_rub: Money;
  deadline_date: string;
  delivery_address_id: string;
  visibility: NeedVisibility;
  valid_until?: string;
}

export interface CreateOfferInput {
  commercial_terms?: CommercialTerms | null;
  resource_kind?: "stock" | "capacity";
  product_id?: string;
  company_id: string;
  price_rub: Money;
  available_units: number;
  lead_time_days: number;
  delivery_cost_rub?: Money | null;
  moq_units?: number;
  price_tiers?: { min_units: number; unit_price_rub: Money }[];
  valid_until?: string;
  /** Черновик агента, из которого подготовлено предложение. */
  draft_id?: string;
  /** Ключ идемпотентности повторной отправки: повтор возвращает то же КП. */
  request_key?: string;
}

/** Поле черновика КП: значение и источник, чтобы человек видел основание. */
export interface OfferDraftField {
  name: string;
  label: string;
  value: Money | null;
  source: string;
  confirmed: boolean;
  note: string | null;
}

export interface OfferDraft {
  id: string;
  need_id: string;
  company_id: string;
  status: "draft" | "used" | "discarded";
  payload: {
    product_id: string | null;
    resource_kind: "stock" | "capacity";
    source_updated_at: string | null;
    price_rub: Money | null;
    available_units: number | null;
    moq_units: number | null;
    lead_time_days: number | null;
    delivery_cost_rub: Money | null;
    price_tiers: { min_units: number; unit_price_rub: Money }[];
  };
  fields: OfferDraftField[];
  missing: string[];
  warnings: string[];
  explanation: string;
  created_at: string | null;
}

/** Оценка работы агентов: конверсия сценариев и участие человека. */
export interface AgentScorecard {
  scope: string;
  window_days: number;
  offer_drafts_total: number;
  offer_drafts_used: number;
  offer_draft_conversion_pct: number | null;
  average_changed_fields: number | null;
  offer_drafts_excluded: number; offer_drafts_open: number; agent_timed_runs: number;
  offers_total: number;
  offers_from_drafts: number;
  offer_rejections: number;
  deals_total: number;
  deals_from_drafts: number;
  selected_origin_offers:number; open_origin_offers:number; rejected_origin_offers:number; expired_origin_offers:number;
  recommendations_total: number;
  recommendations_converted: number;
  recommendation_conversion_pct: number | null;
  human_approvals: number;
  blocked_actions: number;
  admission_checks: number;
  admission_blocked: number;
  agent_runs_total: number;
  agent_runs_failed: number;
  agent_runs_local_route: number;
  agent_runs_external_route: number;
  agent_runs_mixed_route: number;
  agent_runs_rules_route: number;
  agent_runs_unknown_route: number;
  agent_costed_runs: number;
  agent_average_duration_ms: number | null;
  agent_estimated_cost_rub: Money | null;
  agent_model_versions: string[];
  agent_prompt_versions: string[];
  llm_metrics_available: boolean;
  notes: string[];
}

export interface AuditEvent {
  id: string;
  sequence: number;
  event_type: string;
  entity_type: string;
  entity_id: string | null;
  explanation: string;
  created_at: string;
}

export interface AuditVerification {
  valid: boolean;
  checked_events: number;
  broken_sequence: number | null;
}

export interface UpdateCapabilityPassportInput {
  details?: CapabilityDetails;
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
  stale: "Требуется новое КП: спецификация изменилась",
  sent: "Отправлено",
  selected: "Выбрано",
  rejected: "Отклонено",
};

export const DEAL_STATUS_LABELS: Record<DealStatus, string> = {
  created: "Создана", in_production: "В производстве", shipped: "Отгружена", delivered: "Доставлена",
  partially_shipped: "Частично отгружена", partially_accepted: "Частично принята", fulfilled: "Исполнена", cancelled: "Отменена", returned: "Возвращена",
};

export const NEED_VISIBILITY_LABELS: Record<NeedVisibility, string> = {
  open_anonymized: "Открытая (анонимизированная)",
  selected_producers: "Для выбранных производителей",
  closed: "Закрытая",
};

// Generated from the canonical backend registry; v1 still sends Russian labels.
export const PRODUCT_CATEGORY_REGISTRY_VERSION = categoryRegistry.registry_version;
export const PRODUCT_CATEGORY_IDS: Record<string, Record<string, string>> = categoryRegistry.leaf_ids;
export const PRODUCT_CATEGORY_TREE: Record<string, string[]> = categoryRegistry.tree;
export const PRODUCT_CATEGORIES = Object.keys(PRODUCT_CATEGORY_TREE);

export const DOCUMENT_TYPES: { value: string; label: string }[] = [
  { value: "certificate", label: "Сертификат" },
  { value: "declaration", label: "Декларация соответствия" },
  { value: "test_report", label: "Протокол испытаний" },
  { value: "license", label: "Лицензия или разрешение" },
  { value: "other", label: "Прочее" },
];

export const DOCUMENT_STATUS_LABELS: Record<string, string> = {
  unverified: "Загружено, не проверено",
  verified: "Проверено",
  rejected: "Не соответствует",
};

const CHARACTERISTIC_LABELS: Record<string, string> = {
  print: "Печать",
  top_diameter_mm: "Диаметр верха, мм",
  bottom_diameter_mm: "Диаметр дна, мм",
  width_mm: "Ширина, мм",
  length_mm: "Длина, мм",
  dimensions_mm: "Габариты, мм",
  volume_ml: "Объём, мл",
  coating: "Покрытие",
  material: "Материал",
  color: "Цвет",
  height_mm: "Высота, мм",
  diameter_mm: "Диаметр, мм",
};

export function characteristicLabel(key: string, profile?: CategoryProfileSnapshot | null): string {
  const normalize = (value: string) => value.trim().toLowerCase().replace(/ё/g, "е");
  const normalized = normalize(key);
  for (const [fieldKey, field] of Object.entries(profile?.fields ?? {})) {
    if ([fieldKey, ...(field.aliases ?? [])].some((alias) => normalize(alias) === normalized)) {
      return field.label;
    }
  }
  return registryCharacteristicLabel(key) ?? CHARACTERISTIC_LABELS[key] ?? key;
}

export function formatCharacteristics(characteristics: Record<string, unknown>, profile?: CategoryProfileSnapshot | null): string {
  const entries = Object.entries(characteristics);
  if (entries.length === 0) return "—";
  return entries.map(([key, value]) => `${characteristicLabel(key, profile)}: ${["unit", "единица измерения"].includes(key) && typeof value === "string" ? russianUnit(value) : displayValue(value)}`).join(" · ");
}

export function formatRub(value: Money | null | undefined, maximumFractionDigits = 2): string {
  return displayMoney(value, maximumFractionDigits);
}

export function itemUnit(characteristics?: Record<string, unknown>): string {
  const value = characteristics?.unit ?? characteristics?.["единица измерения"];
  return typeof value === "string" && value.trim() ? russianUnit(value.trim()) : "шт.";
}

export function formatUnits(value: number, unit = "шт."): string {
  const normalized = russianUnit(unit);
  const forms: Record<string, [string, string, string]> = {
    "предложение": ["предложение", "предложения", "предложений"],
    "рулон": ["рулон", "рулона", "рулонов"],
    "бухта": ["бухта", "бухты", "бухт"],
    "упаковка": ["упаковка", "упаковки", "упаковок"],
    "коробка": ["коробка", "коробки", "коробок"],
    "комплект": ["комплект", "комплекта", "комплектов"],
    "мешок": ["мешок", "мешка", "мешков"],
    "пачка": ["пачка", "пачки", "пачек"],
  };
  const plural = new Intl.PluralRules("ru-RU").select(Math.round(value));
  const label = forms[normalized]?.[plural === "one" ? 0 : plural === "few" ? 1 : 2] ?? normalized;
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value) + " " + label;
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

interface ValidationErrorItem { loc?: unknown[]; msg?: string; type?: string; ctx?: Record<string, unknown> }
function describeValidationError(item: ValidationErrorItem): string { return validationMessage(item, FIELD_LABELS); }

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

  const response = await russianFetch(`${marketplaceBaseUrl()}${path.replace("/api/v1", "/api/v3").replace("/api/v2", "/api/v3/physical")}`, { ...init, headers });

  if (!response.ok) {
    if (response.status === 401) handleUnauthorized(token);
    let message = `Ошибка запроса: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) {
        message = russianMessage(body.detail, message);
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
  const response = await russianFetch(`${marketplaceBaseUrl()}${path.replace("/api/v1", "/api/v3").replace("/api/v2", "/api/v3/physical")}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    if (response.status === 401) handleUnauthorized(token);
    let message = `Ошибка запроса: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = russianMessage(body.detail, message);
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

export type ExecutionKind = "acceptance" | "return" | "cancellation" | "shipment";
export interface ExecutionEvent {
  id: string; actor_company_id: string; kind: ExecutionKind; units: number; note: string;
  status: "pending" | "approved" | "confirmed" | "rejected"; created_at: string; decided_at: string | null;
}
export interface ExecutionTotals {
  ordered_units: number; accepted_units: number; returned_units: number;
  cancelled_units: number; net_units: number; open_units: number; shipped_units?: number; unshipped_units?: number;
}
export interface CommercialValues {
  unit_price_rub: Money | null; ordered_value_rub: Money; delivery_price_rub: Money | null;
  net_goods_revenue_rub: Money | null; payments_rub: Money | null;
  profit_missing_reason?: string | null; profit_tax_basis?: string; comparable_revenue_rub?: Money | null;
  cost_of_goods_rub?: Money | null; gross_profit_rub?: Money | null;
  attributable_expenses_rub?: Money | null; contribution_rub?: Money | null;
}
export interface DealExecution extends ExecutionTotals {
  deal_id: string; status: string; events: ExecutionEvent[]; financials: CommercialValues;
  cost_revision?: number; unit_cost_rub?: Money | null; cost_note?: string; cost_tax_basis?: string;
  cost_updated_at?: string | null;
  cost_history?: {revision:number;unit_cost_rub:Money|null;attributable_expenses_rub:Money|null;tax_basis:string;source:string;effective_from:string;recorded_at:string;legacy_history_unknown:boolean}[];
}
export interface CommercialOrder extends ExecutionTotals, CommercialValues {
  deal_id: string; category: string; unit: string; created_at: string; status: string; cost_tax_basis?: string;
  product_name: string|null; discount_rub: Money|null; charge_lines: {code:string;title:string;amount_rub:Money|null;source:unknown}[];
  estimate_complete: boolean; missing:string[]; cost_revision?:number|null;cost_effective_from?:string|null;cost_source?:string|null;
  profit_missing_reason?:string|null; cost_history?:{revision:number;unit_cost_rub:Money|null;tax_basis:string;source:string;effective_from:string;legacy_history_unknown:boolean}[];
}
export interface RejectionRate {
  offers_total: number; rejected: number; selected: number; open: number; stale: number;
  known_outcomes: number; rate_pct: number | null;
}
export interface AveragePrice { cohort_key: string; product_name: string | null; net_units: number; unit: string; accepted_units: number; average_unit_price_rub: Money }
export interface MonthlyPoint {
  month: string; orders_count: number; accepted_value_rub: Money | null;
  accepted_units: number | null; unit: string | null; value_known_orders: number;
}
export interface CommercialReport {
  company_id: string; role: "buyer" | "seller"; period_basis: string; built_at: string;
  report_id: string; historical_recalculated: boolean;
  period_events: {event_id:string;deal_id:string;kind:string;status:string;units:number;unit:string;occurred_at:string;goods_value_rub:Money|null;source_acceptances:{acceptance_event_id:string|null;units:number}[]}[];
  reliability: {status:string;known_outcomes:number;orders:number;on_time_share_pct:number|null;outcomes:Record<string,number>};
  filters: { start: string | null; end: string | null; category: string | null; status: string | null; counterparty: string | null; product: string | null; source: string };
  orders_count: number; offers_count: number; rejected_offers_count: number; rejection_rate: RejectionRate;
  average_prices: AveragePrice[]; monthly: MonthlyPoint[];
  payments_rub: null; totals: Record<string, Money | number | null>; orders: CommercialOrder[]; explanation: string;
  group_orders_count: number;
  group_orders: { order_id: string; coalition_id: string; category: string; unit: string; created_at: string; status: string; units: number; contract_value_rub: Money; payments_rub: null }[];
}

export interface EditableCategoryProfile {
  version: number; state: string; fields: string[]; required_for_product: string[];
  passport: Record<string, unknown>;
}
export interface EditorRegistry {
  registry_hash: string;
  registry: { registry_version: string; characteristic_fields: Record<string, { label: string; type: string; aliases: string[]; unit?: string; positive?: boolean }>;
    groups: { label: string; leaves: { id: string; label: string; admission_state: string; technical_profile: EditableCategoryProfile }[] }[] };
}
export interface QuantityConversionPreview {
  input_unit: string; stored_unit: string; factor: number;
  quantities: Record<string, number | null>; price_rub: Money | null; price_tiers?: {min_units:number;unit_price_rub:Money}[];
}
export interface ProfileRevisionPreview {
  state: "current" | "update_available" | "unknown" | "unclassified";
  expected_specification_hash: string;
  expected_snapshot_hash: string;
  expected_current_hash: string;
  previous: CategoryProfileSnapshot | null;
  current: CategoryProfileSnapshot | null;
  changes: { label: string; kind: "added" | "removed" | "changed"; before: unknown; after: unknown }[];
}

export const marketplace = {
  chooseBaseline(token:string,coalitionId:string,data:{company_id:string;offer_id:string|null;expected_revision:number}):Promise<Coalition> {
    return marketplaceFetch(`/api/v1/coalitions/${coalitionId}/baseline`,{token,method:'POST',body:JSON.stringify(data)});
  },
  reviewPackaging(token:string,id:string,input:{target_unit:string;factor:number;approved:boolean;expected_specification_hash?:string;expected_review_hash?:string}):Promise<PackagingDefinition> {return marketplaceFetch(`/api/v1/products/${id}/packaging-conversion`,{token,method:"POST",body:JSON.stringify(input)});},
  getCategoryRegistry(): Promise<EditorRegistry["registry"]> { return marketplaceFetch("/api/v1/categories/profiles"); },
  getEditorRegistry(token: string): Promise<EditorRegistry> { return marketplaceFetch("/api/v1/editor/categories", { token }); },
  reviewCategoryRules(token: string, input: { category_id: string; expected_registry_hash: string; technical_profile: EditableCategoryProfile; reason: string; approved: boolean }, publish = false): Promise<EditorRegistry> {
    return marketplaceFetch(`/api/v1/editor/categories/${publish ? "publish" : "preview"}`, { token, method: "POST", body: JSON.stringify(input) });
  },
  downloadEditorDocument(token: string, id: string): Promise<Blob> { return marketplaceFetchBlob(`/api/v1/editor/documents/${id}/download`, token); },
  previewPhysicalQuantity(kind: "product" | "need", values: Record<string, unknown>): Promise<{ normalized: Record<string, unknown>; conversion: QuantityConversionPreview }> {
    return marketplaceFetch("/api/v2/physical-quantities/preview", { method: "POST", body: JSON.stringify({ kind, values }) });
  },
  getProfileRevision(token: string, kind: "products" | "needs", id: string): Promise<ProfileRevisionPreview> {
    return marketplaceFetch(`/api/v1/${kind}/${id}/category-profile`, { token });
  },
  adoptProfileRevision(token: string, kind: "products" | "needs", id: string, preview: ProfileRevisionPreview, revision?: number): Promise<ProfileRevisionPreview> {
    return marketplaceFetch(`/api/v1/${kind}/${id}/category-profile/adopt`, { token, method: "POST", body: JSON.stringify({
      approved: true, expected_snapshot_hash: preview.expected_snapshot_hash,
      expected_specification_hash: preview.expected_specification_hash,
      expected_current_hash: preview.expected_current_hash, expected_revision: revision,
    }) });
  },
  getExecution(token: string, dealId: string, companyId: string): Promise<DealExecution> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/execution?company_id=${companyId}`, { token });
  },
  recordExecution(token: string, dealId: string, data: { company_id: string; kind: ExecutionKind; units: number; note: string; idempotency_key: string }): Promise<ExecutionEvent> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/execution`, { token, method: "POST", body: JSON.stringify({ ...data, human_approved: true }) });
  },
  decideExecution(token: string, dealId: string, eventId: string, companyId: string, approved: boolean): Promise<ExecutionEvent> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/execution/${eventId}/decision`, { token, method: "POST", body: JSON.stringify({ company_id: companyId, approved, human_approved: true }) });
  },
  saveDealCosts(token: string, dealId: string, data: { company_id: string; expected_revision: number; unit_cost_rub: string | null; attributable_expenses_rub: string | null; tax_basis: string; note: string }): Promise<{ revision: number }> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/costs`, { token, method: "PUT", body: JSON.stringify({ ...data, human_approved: true }) });
  },
  getCommercialReport(token: string, companyId: string, role: "buyer" | "seller", filters: { start?: string; end?: string; category?: string; status?: string; counterparty?: string; product?: string; source?: string } = {}): Promise<CommercialReport> {
    const params = new URLSearchParams({ role });
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
    return marketplaceFetch(`/api/v1/companies/${companyId}/commercial-analytics?${params}`, { token });
  },
  downloadCommercialCsv(token: string, companyId: string, role: "buyer" | "seller", filters: { start?: string; end?: string; category?: string; status?: string; counterparty?: string; product?: string; source?: string } = {}, reportId?: string): Promise<Blob> {
    const params = new URLSearchParams({ role });
    if (reportId) params.set("report_id", reportId);
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
    return marketplaceFetchBlob(`/api/v1/companies/${companyId}/commercial-report.csv?${params}`, token);
  },
  // Публичный каталог (без Bearer)
  getCatalog(sort: "catalog" | "popular" = "catalog"): Promise<Product[]> {
    return marketplaceFetch(`/api/v1/products${sort === "popular" ? "?sort=popular" : ""}`, {}).then((body) => unwrapList<Product>(body, ["products", "items"]));
  },

  getProductDetail(productId: string): Promise<PublicProductDetail> {
    return marketplaceFetch(`/api/v1/products/${productId}/detail`);
  },

  getProducer(companyId: string): Promise<PublicProducer> {
    return marketplaceFetch(`/api/v1/producers/${companyId}`);
  },

  producerPhotoUrl(companyId: string): string {
    return `${marketplaceBaseUrl()}/api/v1/producers/${companyId}/photo`;
  },

  uploadProductionPhoto(token: string, companyId: string, file: File): Promise<void> {
    const body = new FormData(); body.set("file", file);
    return marketplaceFetch(`/api/v1/companies/${companyId}/production-photo`, { method: "POST", token, body });
  },

  getPriceIndex(category: string, productId: string): Promise<PriceIndexPoint[]> {
    return marketplaceFetch(`/api/v1/price-index/${encodeURIComponent(category)}?product_id=${encodeURIComponent(productId)}`);
  },

  importCatalog(token: string, companyId: string, file: File, confirmation?: { hash: string; requestKey: string; expectedRevisions?: Record<string, number | { revision: number; status: string }> }): Promise<ImportPreview> {
    const body = new FormData(); body.set("file", file);
    if (confirmation) { body.set("commit", "true"); body.set("human_approved", "true"); body.set("expected_hash", confirmation.hash); body.set("request_key", confirmation.requestKey); if (confirmation.expectedRevisions) body.set("expected_revisions", JSON.stringify(confirmation.expectedRevisions)); }
    return marketplaceFetch(`/api/v1/companies/${companyId}/catalog-import`, { method: "POST", token, body });
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
    return marketplaceFetch(`/api/v2/companies/${companyId}/products`, {
      method: "POST",
      token,
      body: JSON.stringify(input),
    });
  },

  updateProduct(token: string, productId: string, input: UpdateProductInput): Promise<Product> {
    return marketplaceFetch(`${input.characteristics ? "/api/v2" : "/api/v1"}/products/${productId}`, {
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

  uploadProductImage(token: string, productId: string, file: File): Promise<ProductImage> {
    const body = new FormData();
    body.append("file", file);
    return marketplaceFetch(`/api/v1/products/${productId}/images`, { method: "POST", token, body });
  },

  deleteProductImage(token: string, imageId: string): Promise<void> {
    return marketplaceFetch(`/api/v1/product-images/${imageId}`, { method: "DELETE", token });
  },

  productImageUrl(imageId: string): string {
    return `${marketplaceBaseUrl()}/api/v1/product-images/${imageId}`;
  },

  getSellerAnalytics(token: string, companyId: string): Promise<SellerAnalytics> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/seller-analytics`, { token });
  },

  getMyDeals(token: string): Promise<Deal[]> {
    return marketplaceFetch("/api/v1/deals/mine", { token });
  },

  getDealMessages(token: string, dealId: string, companyId: string): Promise<DealMessage[]> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/messages?company_id=${companyId}`, { token });
  },

  sendDealMessage(token: string, dealId: string, companyId: string, message: string): Promise<DealMessage> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/messages`, { method: "POST", token, body: JSON.stringify({ company_id: companyId, message }) });
  },

  getDealTimeline(token: string, dealId: string, companyId: string): Promise<DealCheckpoint[]> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/timeline?company_id=${companyId}`, { token });
  },

  updateDealCheckpoint(token: string, dealId: string, kind: DealCheckpoint["kind"], companyId: string, completed: boolean): Promise<DealCheckpoint[]> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/timeline/${kind}`, { method: "PATCH", token, body: JSON.stringify({ company_id: companyId, completed, human_approved: true }) });
  },

  getDelivery(token: string, dealId: string, companyId: string): Promise<DeliveryArrangement | null> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/delivery?company_id=${companyId}`, { token });
  },

  saveDelivery(token: string, dealId: string, input: { company_id: string; weight_kg: number; volume_m3: number; method: DeliveryArrangement["method"]; carrier_name?: string; tracking_number?: string; hazard_class?: string | null }): Promise<DeliveryArrangement> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/delivery`, { method: "PUT", token, body: JSON.stringify({ ...input, human_approved: true }) });
  },

  createReview(token: string, dealId: string, companyId: string, rating: number, comment: string): Promise<DealReview> {
    return marketplaceFetch(`/api/v1/deals/${dealId}/reviews`, { method: "POST", token, body: JSON.stringify({ company_id: companyId, rating, comment }) });
  },

  repeatNeed(token: string, needId: string, deadlineDate: string, requestKey: string, validUntil?: string): Promise<Need> {
    return marketplaceFetch(`/api/v1/needs/${needId}/repeat`, { method: "POST", token, body: JSON.stringify({ deadline_date: deadlineDate, request_key: requestKey, ...(validUntil ? { valid_until: validUntil } : {}) }) });
  },

  previewRepeat(token: string, needId: string, deadlineDate?: string, validUntil?: string): Promise<RepeatPreview> {
    return marketplaceFetch(`/api/v1/needs/${needId}/repeat-preview`, { method: "POST", token, ...(deadlineDate ? { body: JSON.stringify({ deadline_date: deadlineDate, valid_until: validUntil || null }) } : {}) });
  },

  getNextStep(token: string, companyId?: string, mode?: "buy" | "sell" | null): Promise<NextStep> {
    return marketplaceFetch(`/api/v1/next-step${companyId ? `?company_id=${encodeURIComponent(companyId)}${mode ? `&mode=${mode}` : ""}` : ""}`, { token });
  },

  duplicateProduct(token: string, productId: string): Promise<Product> {
    return marketplaceFetch(`/api/v1/products/${productId}/duplicate`, { method: "POST", token });
  },

  validateCharacteristics(input: { category: string; subcategory?: string; characteristics: Record<string, unknown>; moq_units: number }): Promise<{ valid: boolean; errors: string[]; warnings: string[] }> {
    return marketplaceFetch("/api/v1/products/validate-characteristics", { method: "POST", body: JSON.stringify(input) });
  },

  getMarketWatches(token: string): Promise<MarketWatch[]> { return marketplaceFetch("/api/v1/market-watches", { token }); },
  createMarketWatch(token: string, category: string): Promise<MarketWatch> { return marketplaceFetch("/api/v1/market-watches", { method: "POST", token, body: JSON.stringify({ category, demand_changes: true, supply_changes: true }) }); },
  deleteMarketWatch(token: string, watchId: string): Promise<void> { return marketplaceFetch(`/api/v1/market-watches/${watchId}`, { method: "DELETE", token }); },
  getBuyerSavings(token: string, companyId: string): Promise<BuyerSavings> { return marketplaceFetch(`/api/v1/companies/${companyId}/buyer-savings`, { token }); },

  // Мощности
  getCapacity(token: string, companyId: string, from?: string, to?: string): Promise<CapacityEntry[]> {
    const params = new URLSearchParams();
    if (from) params.set("start", from);
    if (to) params.set("end", to);
    const query = params.size ? `?${params}` : "";
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

  getExpiringDocuments(token: string, companyId: string, withinDays = 30): Promise<Document[]> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/documents/expiring?within_days=${withinDays}`, { token }).then((body) =>
      unwrapList<Document>(body, ["documents", "items"]),
    );
  },

  uploadDocument(
    token: string,
    companyId: string,
    file: File,
    name: string,
    documentType: string,
    scope?: { category?: string | null; subcategory?: string | null; validUntil?: string | null },
  ): Promise<Document> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("name", name);
    formData.append("document_type", documentType);
    if (scope?.category) formData.append("scope_category", scope.category);
    if (scope?.subcategory) formData.append("scope_subcategory", scope.subcategory);
    if (scope?.validUntil) formData.append("valid_until", scope.validUntil);
    return marketplaceFetch(`/api/v1/companies/${companyId}/documents`, {
      method: "POST",
      token,
      body: formData,
    });
  },

  deleteDocument(token: string, documentId: string): Promise<void> {
    return marketplaceFetch(`/api/v1/documents/${documentId}`, { method: "DELETE", token });
  },

  // Категорийный допуск: решение по документу принимает администратор площадки.
  verifyDocument(
    token: string,
    documentId: string,
    input: DocumentVerificationInput,
  ): Promise<Document> {
    return marketplaceFetch(`/api/v3/documents/${documentId}/decision`, {
      method: "POST",
      token,
      body: JSON.stringify(input),
    });
  },

  getEditorDocuments(token: string, status: "unverified" | "verified" | "rejected"): Promise<PendingDocument[]> { return marketplaceFetch(`/api/v1/editor/documents?verification_status=${status}&limit=200`, {token}); },
  getPendingDocuments(token: string): Promise<PendingDocument[]> {
    return marketplaceFetch("/api/v1/admin/documents/pending", { token }).then((body) =>
      unwrapList<PendingDocument>(body, ["documents", "items"]),
    );
  },

  getCategoryAdmission(
    token: string,
    companyId: string,
    category: string,
    subcategory?: string | null,
  ): Promise<CategoryAdmission> {
    const query = new URLSearchParams({ category });
    if (subcategory) query.set("subcategory", subcategory);
    return marketplaceFetch(`/api/v1/companies/${companyId}/category-admission?${query.toString()}`, {
      token,
    });
  },

  getCategoryRequirements(category: string, subcategory?: string | null): Promise<CategoryRequirements> {
    const query = new URLSearchParams({ category });
    if (subcategory) query.set("subcategory", subcategory);
    return marketplaceFetch(`/api/v1/category-requirements?${query.toString()}`);
  },

  getProductAdmission(productId: string): Promise<ProductAdmissionChecklist> {
    return marketplaceFetch(`/api/v1/products/${productId}/admission`);
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

  getNeedsFeed(token: string, sellerCompanyId: string, filters?: { subcategory?: string; unit?: string }): Promise<NeedFeedItem[]> {
    const params = new URLSearchParams({ seller_company_id: sellerCompanyId });
    if (filters?.subcategory) params.set("subcategory", filters.subcategory);
    if (filters?.unit) params.set("unit", filters.unit);
    return marketplaceFetch(`/api/v1/needs?${params}`, { token }).then((body) =>
      unwrapList<NeedFeedItem>(body, ["needs", "items"]),
    );
  },

  createNeed(token: string, input: CreateNeedInput): Promise<Need> {
    return marketplaceFetch("/api/v2/needs", { method: "POST", token, body: JSON.stringify(input) });
  },

  editNeed(token: string, needId: string, input: Omit<CreateNeedInput, "budget_rub" | "delivery_address_id"> & { budget_rub: Money | null; delivery_address_id: string | null; expected_revision: number; impact_hash?: string }): Promise<Need> {
    return marketplaceFetch(`/api/v2/needs/${needId}`, { method: "PUT", token, body: JSON.stringify(input) });
  },

  previewNeedEdit(token: string, needId: string, input: Omit<CreateNeedInput, "budget_rub" | "delivery_address_id"> & { budget_rub: Money | null; delivery_address_id: string | null; expected_revision: number }): Promise<NeedEditImpact> {
    return marketplaceFetch(`/api/v2/needs/${needId}/edit-preview`, { method: "POST", token, body: JSON.stringify(input) });
  },

  needRevisions(token: string, needId: string): Promise<{ revision: number; snapshot: Record<string, unknown>; impact: NeedEditImpact; created_at: string }[]> {
    return marketplaceFetch(`/api/v1/needs/${needId}/revisions`, { token });
  },

  publishNeed(token: string, needId: string): Promise<Need> {
    return marketplaceFetch(`/api/v1/needs/${needId}/publish`, { method: "POST", token });
  },

  getNeed(token: string, needId: string): Promise<Need | NeedFeedItem> {
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

  previewOfferSend(token: string, needId: string, input: CreateOfferInput): Promise<{ blockers: string[]; warnings: string[]; missing: string[]; can_send: boolean }> {
    return marketplaceFetch(`/api/v1/needs/${needId}/offers/preview`, {
      method: "POST", token, body: JSON.stringify(input),
    });
  },

  createOffer(token: string, needId: string, input: CreateOfferInput): Promise<Offer> {
    return marketplaceFetch(`/api/v1/needs/${needId}/offers`, {
      method: "POST",
      token,
      body: JSON.stringify(input),
    });
  },

  prepareOfferDraft(token: string, needId: string, companyId: string): Promise<OfferDraft> {
    return marketplaceFetch(`/api/v1/needs/${needId}/offer-draft`, {
      method: "POST",
      token,
      body: JSON.stringify({ company_id: companyId }),
    });
  },

  getAgentScorecard(token: string, companyId: string): Promise<AgentScorecard> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/agent-scorecard`, { token });
  },

  getPlatformAgentScorecard(token: string): Promise<AgentScorecard> {
    return marketplaceFetch("/api/v1/platform/agent-scorecard", { token });
  },

  optimizeNeed(token: string, needId: string): Promise<OptimizationVariant[]> {
    return marketplaceFetch(`/api/v1/needs/${needId}/optimize`, { method: "POST", token }).then((body) =>
      unwrapList<OptimizationVariant>(body, ["variants", "items"]),
    );
  },

  createResiliencePlan(
    token: string,
    needId: string,
    variantId: string,
    maxPriceIncreasePct = 5,
    maxDelayDays = 0,
    autoReplace = false,
  ): Promise<ResiliencePlan> {
    return marketplaceFetch(`/api/v1/needs/${needId}/resilience-plans`, {
      method: "POST",
      token,
      body: JSON.stringify({
        variant_id: variantId,
        max_price_increase_pct: maxPriceIncreasePct,
        max_delay_days: maxDelayDays,
        auto_replace_within_thresholds: autoReplace,
      }),
    });
  },

  getResiliencePlans(token: string): Promise<ResiliencePlan[]> {
    return marketplaceFetch("/api/v1/resilience-plans/mine", { token }).then((body) =>
      unwrapList<ResiliencePlan>(body, ["plans", "items"]),
    );
  },

  recalculateResiliencePlan(token: string, planId: string): Promise<ResiliencePlan> {
    return marketplaceFetch(`/api/v1/resilience-plans/${planId}/recalculate`, { method: "POST", token });
  },

  confirmResiliencePlan(token: string, planId: string, expectedRevision: number): Promise<ResiliencePlan> {
    return marketplaceFetch(`/api/v1/resilience-plans/${planId}/confirm`, {
      method: "POST", token, body: JSON.stringify({ approved: true, expected_revision: expectedRevision }),
    });
  },

  simulateFailure(token: string, planId: string, companyIds: string[]): Promise<ResilienceScenario> {
    return marketplaceFetch(`/api/v1/resilience-plans/${planId}/simulate-failure`, {
      method: "POST", token, body: JSON.stringify({ failed_company_ids: companyIds }),
    });
  },

  approveRecovery(token: string, scenarioId: string, expectedRevision: number): Promise<ResiliencePlan> {
    return marketplaceFetch(`/api/v1/resilience-scenarios/${scenarioId}/approve`, {
      method: "POST", token, body: JSON.stringify({ approved: true, expected_revision: expectedRevision }),
    });
  },

  getReserveInvitations(token: string, companyId: string): Promise<ReserveCommitment[]> {
    return marketplaceFetch(`/api/v1/reserve-invitations/${companyId}`, { token }).then((body) =>
      unwrapList<ReserveCommitment>(body, ["commitments", "items"]),
    );
  },

  decideReserve(
    token: string,
    commitmentId: string,
    input: Record<string, unknown>,
  ): Promise<ReserveCommitment> {
    return marketplaceFetch(`/api/v1/reserve-commitments/${commitmentId}/decision`, {
      method: "POST", token, body: JSON.stringify(input),
    });
  },

  getPrimaryObligations(token: string, companyId: string): Promise<PrimaryObligation[]> {
    return marketplaceFetch(`/api/v1/primary-obligations/${companyId}`, { token }).then((body) =>
      unwrapList<PrimaryObligation>(body, ["obligations", "items"]),
    );
  },

  reportFailure(token: string, planId: string, companyId: string, reason: string): Promise<ResiliencePlan> {
    return marketplaceFetch(`/api/v1/resilience-plans/${planId}/failures`, {
      method: "POST", token, body: JSON.stringify({ company_id: companyId, reason }),
    });
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

  dismissOpportunity(token: string, opportunityId: string, reason: string): Promise<MarketOpportunity> {
    return marketplaceFetch(`/api/v1/opportunities/${opportunityId}/dismiss`, {
      method: "POST", token, body: JSON.stringify({ reason }),
    });
  },

  rollbackCatalogImport(token: string, companyId: string, importId: string): Promise<{ import_id: string; deleted_ids: string[]; restored_ids: string[]; skipped_published_ids: string[] }> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/catalog-imports/${importId}/rollback`, {
      method: "POST", token,
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
    expectedRevision: number,
    requestKey?: string,
  ): Promise<Coalition> {
    return marketplaceFetch(`/api/v1/coalitions/${coalitionId}/decision`, {
      method: "POST",
      token,
      body: JSON.stringify({ company_id: companyId, decision, expected_revision: expectedRevision, ...(requestKey ? { request_key: requestKey } : {}) }),
    });
  },

  // Сделка (покупатель выбирает предложение)
  selectOffer(token: string, offerId: string, revision: number, requestKey?: string): Promise<Deal> {
    return marketplaceFetch(`/api/v1/offers/${offerId}/select`, { method: "POST", token, body: JSON.stringify({ expected_revision: revision, human_approved: true, ...(requestKey ? { request_key: requestKey } : {}) }) });
  },

  // Уведомления
  getAddressSuggestions(token: string, companyId: string, query: string): Promise<{ label: string; address: string; city: string; region: string; house: string | null }[]> {
    return marketplaceFetch(`/api/v1/companies/${companyId}/address-suggestions?query=${encodeURIComponent(query)}`, { token });
  },
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

  createSupportTicket(
    token: string,
    input: { company_id?: string; subject: string; message: string; request_key?: string },
  ): Promise<SupportTicket> {
    return marketplaceFetch("/api/v1/support/tickets", {
      method: "POST", token, body: JSON.stringify(input),
    });
  },

  getMySupportTickets(token: string): Promise<SupportTicket[]> {
    return marketplaceFetch("/api/v1/support/tickets/mine", { token });
  },

  getAdminSupportTickets(token: string, status?: string): Promise<SupportTicket[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return marketplaceFetch(`/api/v1/admin/support/tickets${query}`, { token });
  },

  updateAdminSupportTicket(
    token: string,
    ticketId: string,
    input: { status: SupportTicket["status"]; admin_response?: string },
  ): Promise<SupportTicket> {
    return marketplaceFetch(`/api/v1/admin/support/tickets/${ticketId}`, {
      method: "PATCH", token, body: JSON.stringify(input),
    });
  },

  getKpi(token: string, companyId?: string): Promise<TrustKpi> {
    const query = companyId ? `?company_id=${companyId}` : "";
    return marketplaceFetch(`/api/v1/kpi${query}`, { token });
  },
  getAuditEvents(token: string, companyId?: string): Promise<AuditEvent[]> {
    const query = new URLSearchParams({ limit: "50" });
    if (companyId) query.set("company_id", companyId);
    return marketplaceFetch(`/api/v1/audit/events?${query}`, { token });
  },
  verifyAudit(token: string): Promise<AuditVerification> {
    return marketplaceFetch("/api/v1/audit/verify", { token });
  },
};

export interface CommercialTerms {
  delivery_method: "included" | "separate" | "self_pickup" | "unknown";
  tax_basis: "includes_vat" | "no_vat" | "unknown";
  vat_rate_pct?: string | null;
  delivery_conditions?: string | null;
  exceptions?: string;
  expenses?: {code:"individual_operations"|"reserve_holding"|"switching"|"other";title:string;amount_rub:Money|null;required:boolean;source:string;version:string}[];
}
export interface CommercialEstimate {schema_version:number;complete:boolean;missing:string[];total_rub:Money|null;known_total_rub:Money;lines:{code:string;title:string;amount_rub:Money|null;conditional:boolean;source:unknown;tax_basis:string}[];terms:CommercialTerms;benefit_rub?:Money|null;baseline_comparable?:boolean}
export interface CommercialSnapshot {schema_version:number;estimate:CommercialEstimate;need:{id:string;revision:number};offer:{id:string;revision:number}|null}


export interface FulfillmentRecord {
  id: string; company_id: string; terms_version: number; actual_date: string | null;
  expected_date?: string; note: string; attachments: string[]; action?: string;
  status?: string; kind?: string; units?: number; batch_id?: string; line_id?: string;
  resolution?: string; responses?: FulfillmentRecord[]; method?: string; carrier?: string; cost_rub?: string | null;
}
export interface FulfillmentBatch extends FulfillmentRecord {
  batch: string; line_id: string; units: number; received: number; inspected: number;
  accepted: number; rejected: number; missing: number;
}
export interface FulfillmentState {
  deal_id: string; line_id: string; revision: number; terms_version: number; status: string;
  totals: { ordered_units: number; shipped_units: number; unshipped_units: number; received_units: number;
    accepted_units: number; returned_units: number; cancelled_units: number; net_units: number; open_units: number };
  dispatch: (FulfillmentRecord & { address: string; city: string; region: string; packaging: string;
    places: number; weight_kg: number; volume_m3: number; hazard_class: string | null; restrictions: string; classification_note?: string }) | null;
  commercial: { seller_total_rub: string; seller_delivery_rub: string | null; external_carrier_rub: string | null };
  destination: string | null;
  logistics: (FulfillmentRecord & { method: string; carrier: string; cost_rub: string | null; confirmed: boolean }) | null;
  stages: Record<string, FulfillmentRecord>; batches: FulfillmentBatch[];
  disputes: FulfillmentRecord[]; requests: FulfillmentRecord[]; messages: FulfillmentRecord[];
  proposals: FulfillmentRecord[]; history: FulfillmentRecord[]; completed: boolean; rating_rule: string;
}
export interface FulfillmentCommand {
  company_id: string; expected_revision: number; terms_version: number;
  idempotency_key: string; human_approved: true; action: string; payload: Record<string, unknown>;
}
export const fulfillmentApi = {
  get(token: string, deal: string, company: string): Promise<FulfillmentState> {
    return marketplaceFetch(`/api/v3/deals/${deal}/fulfillment?company_id=${company}`, { token });
  },
  act(token: string, deal: string, command: FulfillmentCommand): Promise<FulfillmentState> {
    return marketplaceFetch(`/api/v3/deals/${deal}/fulfillment`, { token, method: "POST", body: JSON.stringify(command) });
  },
  upload(token: string, deal: string, company: string, version: number, file: File): Promise<{id: string; filename: string}> {
    const body = new FormData(); body.set("company_id", company); body.set("terms_version", String(version)); body.set("file", file);
    return marketplaceFetch(`/api/v3/deals/${deal}/attachments`, { token, method: "POST", body });
  },
  download(token: string, deal: string, company: string, id: string): Promise<Blob> {
    return marketplaceFetchBlob(`/api/v3/deals/${deal}/attachments/${id}?company_id=${company}`, token);
  },
};
