"use client";

// Документы компании (GET/POST /companies/{id}/documents, DELETE /documents/{id}).
// Загрузка — multipart (file + name + document_type + область действия).
// Рядом — отчёт о категорийном допуске: загрузка файла сама допуск не выдаёт,
// решение принимает проверяющий площадки.

import { russianMessage } from "../../lib/russianMessages";
import { russianLabel } from "../../lib/presentation";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { getToken } from "../../lib/api";
import {
  ApiError,
  CategoryAdmission,
  DOCUMENT_STATUS_LABELS,
  DOCUMENT_TYPES,
  Document,
  PRODUCT_CATEGORY_TREE,
  marketplace,
} from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

const CATEGORIES = Object.keys(PRODUCT_CATEGORY_TREE);
const OTHER_SCOPE = "Другое";

export default function SellerDocumentsPage() {
  const {
    loading,
    error: meError,
    available,
    company,
    companyId,
    setCompanyId,
  } = useCompanySelector("can_sell");

  const [documents, setDocuments] = useState<Document[]>([]);
  const [expiryState, setExpiryState] = useState<{
    companyId: string | null; status: "loading" | "ready" | "error"; list: Document[]; error: string | null;
  }>({ companyId: null, status: "loading", list: [], error: null });
  const [reload, setReload] = useState(0);
  const activeCompany = useRef(companyId);
  activeCompany.current = companyId;
  const expiring = expiryState.companyId === companyId ? expiryState.list : [];
  const expiryStatus = expiryState.companyId === companyId ? expiryState.status : "loading";
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [documentType, setDocumentType] = useState(DOCUMENT_TYPES[0].value);
  const [scopeCategory, setScopeCategory] = useState(CATEGORIES[0]);
  const [scopeSubcategory, setScopeSubcategory] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [admissionCategory, setAdmissionCategory] = useState(CATEGORIES[0]);
  const [admissionSubcategory, setAdmissionSubcategory] = useState("");
  const [admission, setAdmission] = useState<CategoryAdmission | null>(null);
  const [admissionError, setAdmissionError] = useState<string | null>(null);
  const [checkingAdmission, setCheckingAdmission] = useState(false);

  const subcategoryOptions =
    scopeCategory === OTHER_SCOPE ? [] : PRODUCT_CATEGORY_TREE[scopeCategory] ?? [];
  const admissionSubcategoryOptions =
    admissionCategory === OTHER_SCOPE ? [] : PRODUCT_CATEGORY_TREE[admissionCategory] ?? [];

  useEffect(() => {
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setLoaded(false);
    setDocuments([]);
    setAdmission(null);
    setAdmissionError(null);
    setExpiryState({ companyId, status: "loading", list: [], error: null });
    setError(null);
    marketplace
      .getDocuments(token, companyId)
      .then((list) => {
        if (!cancelled) setDocuments(list);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить документы.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    marketplace
      .getExpiringDocuments(token, companyId)
      .then((list) => {
        if (!cancelled) setExpiryState({ companyId, status: "ready", list, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) setExpiryState({ companyId, status: "error", list: [],
          error: err instanceof ApiError ? russianMessage(err.message) : "Не удалось проверить сроки документов." });
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, reload]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company || !file) return;
    setUploading(true);
    setError(null);
    try {
      await marketplace.uploadDocument(token, company.id, file, name.trim() || file.name, documentType, {
        category: scopeCategory === OTHER_SCOPE ? null : scopeCategory,
        subcategory: scopeSubcategory || null,
        validUntil: validUntil || null,
      });
      const updated = await marketplace.getDocuments(token, company.id);
      if (activeCompany.current !== company.id) return;
      setDocuments(updated);
      setReload((value) => value + 1);
      setName("");
      setFile(null);
      setValidUntil("");
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить документ.");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(document: Document) {
    const token = getToken();
    if (!token) return;
    if (!window.confirm(`Удалить документ «${document.name}»?`)) return;
    setDeletingId(document.id);
    setError(null);
    try {
      await marketplace.deleteDocument(token, document.id);
      if (activeCompany.current !== document.company_id) return;
      setDocuments((current) => current.filter((item) => item.id !== document.id));
      setExpiryState((current) => ({ ...current, list: current.list.filter((item) => item.id !== document.id) }));
      setAdmission(null);
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось удалить документ.");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleCheckAdmission() {
    const token = getToken();
    if (!token || !companyId) return;
    setCheckingAdmission(true);
    setAdmissionError(null);
    try {
      const report = await marketplace.getCategoryAdmission(
        token,
        companyId,
        admissionCategory === OTHER_SCOPE ? "Другое" : admissionCategory,
        admissionSubcategory || null,
      );
      if (activeCompany.current !== companyId) return;
      setAdmission(report);
    } catch (err) {
      setAdmission(null);
      setAdmissionError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось проверить допуск.");
    } finally {
      setCheckingAdmission(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (meError) {
    return (
      <div>
        <h1 className="page-title">Документы</h1>
        <div className="alert alert-error">{meError}</div>
        <Link href="/login" className="btn btn-secondary">
          На страницу входа
        </Link>
      </div>
    );
  }

  if (available.length === 0) {
    return (
      <div>
        <h1 className="page-title">Документы</h1>
        <div className="alert alert-error">
          У вас нет компании с правом «Продаю». Создайте компанию и включите режим продажи.
        </div>
        <div className="actions">
          <Link href="/company/new" className="btn btn-primary">
            Создать компанию
          </Link>
          <Link href="/dashboard" className="btn btn-secondary">
            В личный кабинет
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Документы и допуск</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          В личный кабинет
        </Link>
      </div>
      <p className="subtitle">
        Загрузка не подтверждает подлинность и применимость. Нужен действующий документ,
        подтверждённый проверяющим для нужной категории.
      </p>

      {available.length > 1 && (
        <div className="field">
          <label htmlFor="seller_company">Компания</label>
          <select id="seller_company" value={companyId} onChange={(event) => setCompanyId(event.target.value)}>
            {available.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
          </select>
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      <section className="card">
        <h2>Проверка допуска по категории</h2>
        <p className="hint">
          Проверьте недостающие доказательства. Невыполненные обязательные требования
          блокируют публикацию до решения проверяющего.
        </p>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="admission_category">Категория</label>
            <select
              id="admission_category"
              value={admissionCategory}
              onChange={(event) => {
                setAdmissionCategory(event.target.value);
                setAdmissionSubcategory("");
                setAdmission(null);
              }}
            >
              {CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="admission_subcategory">
              Подкатегория<span className="opt">если известна</span>
            </label>
            <select
              id="admission_subcategory"
              value={admissionSubcategory}
              onChange={(event) => {
                setAdmissionSubcategory(event.target.value);
                setAdmission(null);
              }}
            >
              <option value="">Не указана</option>
              {admissionSubcategoryOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={checkingAdmission}
            onClick={() => void handleCheckAdmission()}
          >
            {checkingAdmission ? "Проверяем..." : "Проверить допуск"}
          </button>
        </div>

        {admissionError && <div className="alert alert-error">{admissionError}</div>}

        {admission && (
          <div>
            <div className="company-row">
              <div>
                <div className="company-item__name">
                  {admission.profile_title ?? "Правила категории не заданы"}
                </div>
                <div className="company-meta">{admission.summary}</div>
              </div>
              <span className={`badge ${admission.blocking_open ? "badge-rejected" : "badge-verified"}`}>
                {admission.state_label}
              </span>
            </div>
            {admission.blocking_open > 0 && (
              <div className="alert alert-error">{admission.blocking_message}</div>
            )}
            {admission.requirements.length === 0 ? (
              <p className="hint mode-hint">
                Правила документов для этой категории ещё не настроены. Доступна только проверка компании.
              </p>
            ) : (
              <ul className="company-list">
                {admission.requirements.map((item) => (
                  <li key={item.code} className="card">
                    <div className="company-row">
                      <div>
                        <div className="company-item__name">{item.title}</div>
                        <div className="company-meta">{item.legal_reference}</div>
                        <div className="company-meta">{item.seller_hint}</div>
                        {item.scope_note && (
                          <div className="company-meta">Применимость: {item.scope_note}</div>
                        )}
                      </div>
                      <span
                        className={`badge ${item.state === "satisfied" ? "badge-verified" : "badge-rejected"}`}
                      >
                        {item.state_label}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {admission.advisories.length > 0 && (
              <ul className="company-list">
                {admission.advisories.map((text) => (
                  <li key={text}>
                    <span className="company-meta">Предупреждение: {text}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <section className="card">
        <h2>Загрузить документ</h2>
        <form onSubmit={handleUpload}>
          <div className="field">
            <label htmlFor="document_name">
              Название<span className="opt">если пусто — имя файла</span>
            </label>
            <input
              id="document_name"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Например, Декларация ТР ТС 005/2011"
            />
          </div>
          <div className="field">
            <label htmlFor="document_type">
              Тип документа<span className="req">*</span>
            </label>
            <select
              id="document_type"
              value={documentType}
              onChange={(event) => setDocumentType(event.target.value)}
            >
              {DOCUMENT_TYPES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="scope_category">
              Область действия: категория<span className="opt">обязательна для проверки применимости</span>
            </label>
            <select
              id="scope_category"
              value={scopeCategory}
              onChange={(event) => {
                setScopeCategory(event.target.value);
                setScopeSubcategory("");
              }}
            >
              {CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
              <option value={OTHER_SCOPE}>{OTHER_SCOPE}</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="scope_subcategory">
              Область действия: подкатегория<span className="opt">уточняет изделие</span>
            </label>
            <select
              id="scope_subcategory"
              value={scopeSubcategory}
              onChange={(event) => setScopeSubcategory(event.target.value)}
            >
              <option value="">Не указана</option>
              {subcategoryOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="valid_until">
              Действует до<span className="opt">проверяющий укажет фактический срок</span>
            </label>
            <input
              id="valid_until"
              type="date"
              value={validUntil}
              onChange={(event) => setValidUntil(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="document_file">
              Файл<span className="req">*</span>
              <span className="opt">изображения, PDF, аудио · до 25 МБ</span>
            </label>
            <input
              id="document_file"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              required
            />
          </div>
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={uploading || !file}>
              {uploading ? "Загружаем..." : "Загрузить документ"}
            </button>
          </div>
        </form>
      </section>

      {expiryStatus === "loading" && <p className="hint" role="status">Проверяем сроки документов...</p>}
      {expiryStatus === "error" && (
        <div className="alert alert-error" role="alert">
          <p>{expiryState.error ?? "Не удалось проверить сроки документов."}</p>
          <button type="button" className="btn btn-secondary" onClick={() => setReload((value) => value + 1)}>Повторить проверку сроков</button>
        </div>
      )}
      {expiryStatus === "ready" && expiring.length === 0 && <p className="hint">Истекающих подтверждений нет.</p>}
      {expiring.length > 0 && (
        <section className="card" aria-live="polite">
          <h2>Истекающие подтверждения</h2>
          <p className="hint">
            Продлите документы до блокировки новых публикаций и сделок.
            Действующие договорённости автоматически не отменяются.
          </p>
          <ul className="company-list">
            {expiring.map((document) => (
              <li key={document.id} className="company-item">
                <span className="company-item__name">{document.name}</span>
                <span className="company-meta">Действует до {document.valid_until ?? "—"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>Список документов</h2>
        {!loaded ? (
          <p className="hint mode-hint">Загрузка документов...</p>
        ) : documents.length === 0 ? (
          <p className="hint mode-hint">Документов пока нет.</p>
        ) : (
          <ul className="company-list">
            {documents.map((document) => {
              const typeLabel =
                DOCUMENT_TYPES.find((item) => item.value === document.document_type)?.label ??
                document.document_type;
              const scope = [document.scope_category, document.scope_subcategory]
                .filter(Boolean)
                .join(" · ");
              return (
                <li key={document.id} className="card">
                  <div className="company-row">
                    <div>
                      <div className="company-item__name">{document.name}</div>
                      <div className="company-meta">
                        {typeLabel} · {document.content_type}
                      </div>
                      <div className="company-meta">
                        Область действия: {scope || "не указана — проверка применимости невозможна"}
                      </div>
                      {Object.entries(document.confirms ?? {}).length > 0 && (
                        <div className="company-meta">
                          Подтверждено проверяющим:{" "}
                          {Object.entries(document.confirms)
                            .map(([key, values]) => `${key}: ${values.join(", ")}`)
                            .join(" · ")}
                        </div>
                      )}
                      {document.valid_until && (
                        <div className="company-meta">Действует до {document.valid_until}</div>
                      )}
                      {document.verification_note && (
                        <div className="company-meta">Решение проверяющего: {document.verification_note}</div>
                      )}
                      <span className={`badge badge-${document.verification_status}`}>
                        {DOCUMENT_STATUS_LABELS[document.verification_status] ?? russianLabel(document.verification_status, "Статус уточняется")}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="btn btn-danger btn-sm"
                      disabled={deletingId === document.id}
                      onClick={() => void handleDelete(document)}
                    >
                      {deletingId === document.id ? "..." : "Удалить"}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
