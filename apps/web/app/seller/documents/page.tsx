"use client";

// Документы компании (GET/POST /companies/{id}/documents, DELETE /documents/{id}).
// Загрузка — multipart (file + name + document_type).

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import { ApiError, DOCUMENT_TYPES, Document, marketplace } from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

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
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [documentType, setDocumentType] = useState(DOCUMENT_TYPES[0].value);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setLoaded(false);
    setError(null);
    marketplace
      .getDocuments(token, companyId)
      .then((list) => {
        if (!cancelled) setDocuments(list);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Не удалось загрузить документы.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company || !file) return;
    setUploading(true);
    setError(null);
    try {
      await marketplace.uploadDocument(token, company.id, file, name.trim() || file.name, documentType);
      const updated = await marketplace.getDocuments(token, company.id);
      setDocuments(updated);
      setName("");
      setFile(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось загрузить документ.");
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
      setDocuments((current) => current.filter((item) => item.id !== document.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось удалить документ.");
    } finally {
      setDeletingId(null);
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
            На главную
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">Документы</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          На главную
        </Link>
      </div>
      <p className="subtitle">Сертификаты, декларации и прочие документы компании</p>

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
              return (
                <li key={document.id} className="card">
                  <div className="company-row">
                    <div>
                      <div className="company-item__name">{document.name}</div>
                      <div className="company-meta">
                        {typeLabel} · {document.content_type}
                      </div>
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
