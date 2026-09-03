// Минимальный клиент gateway-auth. Все запросы — JSON,
// аутентификация — JWT Bearer, токен хранится в localStorage ("token").

import { serviceUrl } from "./serviceUrl";
const apiBaseUrl = () => serviceUrl(process.env.NEXT_PUBLIC_API_URL, 8001);
const TOKEN_KEY = "token";
export const AUTH_CHANGED_EVENT = "porukam-auth-changed";

// ---------- Типы домена ----------

export type AccountStatus = "active" | "blocked";
export type LegalForm = "ООО" | "ИП";
export type VerificationStatus = "draft" | "pending_review" | "verified" | "rejected";

export interface User {
  id: string;
  last_name: string;
  first_name: string;
  middle_name: string | null;
  email: string;
  phone: string | null;
  account_status: AccountStatus;
  is_marketplace_admin: boolean;
}

export interface Membership {
  can_buy: boolean;
  can_sell: boolean;
  is_admin: boolean;
}

export interface Company {
  id: string;
  full_name: string;
  display_name: string;
  legal_form: LegalForm;
  inn: string;
  ogrn: string | null;
  ogrnip: string | null;
  kpp: string | null;
  legal_address: string;
  country: string;
  verification_status: VerificationStatus;
  /** Присутствует в ответах «от моего лица» (auth/me, создание компании). */
  membership?: Membership;
  /** Может возвращаться бэкендом при отклонении заявки. */
  rejection_reason?: string | null;
  created_at: string;
  updated_at: string;
}

export interface VerificationEvent {
  id: string;
  company_id: string;
  from_status: VerificationStatus;
  to_status: VerificationStatus;
  performed_by_user_id: string | null;
  reason: string | null;
  created_at: string;
}

export interface AuthResponse {
  user: User;
  access_token: string;
  token_type: string;
}

export interface MeResponse {
  user: User;
  companies: Company[];
}

// ---------- Входные данные ----------

export interface RegisterInput {
  last_name: string;
  first_name: string;
  middle_name?: string;
  email: string;
  password: string;
  phone?: string;
}

export interface CreateCompanyInput {
  full_name: string;
  display_name: string;
  legal_form: LegalForm;
  inn: string;
  ogrn?: string | null;
  ogrnip?: string | null;
  kpp?: string | null;
  legal_address: string;
  can_buy: boolean;
  can_sell: boolean;
}

export type UpdateCompanyInput = Partial<CreateCompanyInput>;

// ---------- Подписи статусов (русский язык) ----------

export const VERIFICATION_STATUS_LABELS: Record<VerificationStatus, string> = {
  draft: "Черновик",
  pending_review: "На проверке",
  verified: "Проверена",
  rejected: "Отклонена",
};

export const ACCOUNT_STATUS_LABELS: Record<AccountStatus, string> = {
  active: "Активен",
  blocked: "Заблокирован",
};

// ---------- Ошибки ----------

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// ---------- Разбор ошибок валидации FastAPI (422) ----------

const FIELD_LABELS: Record<string, string> = {
  last_name: "Фамилия",
  first_name: "Имя",
  middle_name: "Отчество",
  email: "Email",
  password: "Пароль",
  phone: "Телефон",
  full_name: "Название",
  display_name: "Отображаемое название",
  legal_form: "Организационно-правовая форма",
  inn: "ИНН",
  ogrn: "ОГРН",
  ogrnip: "ОГРНИП",
  kpp: "КПП",
  legal_address: "Юридический адрес",
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
  if (msg.toLowerCase().includes("valid email")) {
    return "Введите корректный email";
  }
  if (msg.toLowerCase().includes("string type")) {
    return `«${label}» должно быть строкой`;
  }
  if (label) {
    return `«${label}»: ${msg}`;
  }
  return msg;
}

// ---------- Работа с токеном ----------

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

// При истёкшем/недействительном токене (401) сбрасываем токен и отправляем на вход.
export function handleUnauthorized(): void {
  if (typeof window === "undefined") return;
  clearToken();
  if (window.location.pathname !== "/login") {
    window.location.replace("/login");
  }
}

// ---------- HTTP ----------

type RequestOptions = RequestInit & { token?: string | null };

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { token, ...init } = options;
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${apiBaseUrl()}${path}`, { ...init, headers });

  if (!response.ok) {
    if (
      response.status === 401 &&
      path !== "/api/v1/auth/login" &&
      path !== "/api/v1/auth/register"
    ) {
      handleUnauthorized();
    }
    let message = `Ошибка запроса: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        message = body.detail.map((item) => describeValidationError(item as ValidationErrorItem)).join("; ");
      }
    } catch {
      // тело ответа не JSON — оставляем стандартное сообщение
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ---------- Эндпоинты ----------

export const api = {
  // 1. Регистрация
  register(input: RegisterInput): Promise<AuthResponse> {
    return request("/api/v1/auth/register", { method: "POST", body: JSON.stringify(input) });
  },

  // 2. Вход
  login(input: { email: string; password: string }): Promise<AuthResponse> {
    return request("/api/v1/auth/login", { method: "POST", body: JSON.stringify(input) });
  },

  // 3. Текущий пользователь и его компании
  me(token: string): Promise<MeResponse> {
    return request("/api/v1/auth/me", { token });
  },

  // 4. Создание компании
  createCompany(token: string, input: CreateCompanyInput): Promise<Company> {
    return request("/api/v1/companies", { method: "POST", token, body: JSON.stringify(input) });
  },

  // 5. Частичное обновление компании
  updateCompany(token: string, id: string, input: UpdateCompanyInput): Promise<Company> {
    return request(`/api/v1/companies/${id}`, { method: "PATCH", token, body: JSON.stringify(input) });
  },

  // 5.1 Изменение разрешений (режимы «Покупаю / Продаю»)
  updateMembership(
    token: string,
    id: string,
    input: { can_buy: boolean; can_sell: boolean },
  ): Promise<Membership> {
    return request(`/api/v1/companies/${id}/membership`, {
      method: "PATCH",
      token,
      body: JSON.stringify(input),
    });
  },

  // 6. Отправка компании на проверку
  submitCompanyForReview(token: string, id: string): Promise<Company> {
    return request(`/api/v1/companies/${id}/submit-review`, { method: "POST", token });
  },

  // 7. Компании на проверке (для marketplace-администратора)
  getPendingCompanies(token: string): Promise<{ companies: Company[] }> {
    return request("/api/v1/admin/companies?status=pending_review", { token });
  },

  getAdminCompanies(token: string, status?: VerificationStatus, search?: string): Promise<{ companies: Company[] }> {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (search?.trim()) params.set("search", search.trim());
    return request(`/api/v1/admin/companies?${params.toString()}`, { token });
  },

  getAdminUsers(token: string, search?: string): Promise<{ users: User[] }> {
    const query = search?.trim() ? `?search=${encodeURIComponent(search.trim())}` : "";
    return request(`/api/v1/admin/users${query}`, { token });
  },

  getCompanyVerificationHistory(token: string, id: string): Promise<VerificationEvent[]> {
    return request(`/api/v1/admin/companies/${id}/verification-events`, { token });
  },

  // 8. Решение по проверке компании
  decideCompanyVerification(
    token: string,
    id: string,
    decision: "approve" | "reject",
    reason?: string,
  ): Promise<Company> {
    const body: { decision: "approve" | "reject"; reason?: string } = { decision };
    if (reason && reason.trim()) body.reason = reason.trim();
    return request(`/api/v1/admin/companies/${id}/verification`, {
      method: "POST",
      token,
      body: JSON.stringify(body),
    });
  },

  // 9. Блокировка/разблокировка пользователя
  setUserBlocked(token: string, id: string, blocked: boolean): Promise<User> {
    return request(`/api/v1/admin/users/${id}/block`, {
      method: "POST",
      token,
      body: JSON.stringify({ blocked }),
    });
  },
};
