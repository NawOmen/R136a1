"use client";

// Товары компании (GET/POST /companies/{id}/products): список, форма создания,
// публикация/снятие с публикации (POST /products/{id}/publish).

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import {
  ApiError,
  formatCharacteristics,
  formatRub,
  formatUnits,
  marketplace,
  Product,
  PRODUCT_CATEGORIES,
} from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

interface CharacteristicRow {
  key: string;
  value: string;
}

function newRow(key = "", value = ""): CharacteristicRow {
  return { key, value };
}

export default function SellerProductsPage() {
  const {
    loading,
    error: meError,
    available,
    company,
    companyId,
    setCompanyId,
  } = useCompanySelector("can_sell");

  const [products, setProducts] = useState<Product[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Форма создания
  const [name, setName] = useState("");
  const [category, setCategory] = useState(PRODUCT_CATEGORIES[0]);
  const [rows, setRows] = useState<CharacteristicRow[]>([
    newRow("volume_ml", ""),
    newRow("coating", ""),
  ]);
  const [price, setPrice] = useState("");
  const [moq, setMoq] = useState("");
  const [leadTime, setLeadTime] = useState("");
  const [creating, setCreating] = useState(false);
  const [publishingId, setPublishingId] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setLoaded(false);
    setError(null);
    marketplace
      .getCompanyProducts(token, companyId)
      .then((list) => {
        if (!cancelled) setProducts(list);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Не удалось загрузить товары.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  function updateRow(index: number, patch: Partial<CharacteristicRow>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company) return;
    if (rows.length === 0 || rows.some((row) => !row.key.trim() || !row.value.trim())) {
      setError("Заполните ключ и значение каждой характеристики.");
      return;
    }
    const characteristics: Record<string, unknown> = {};
    for (const row of rows) {
      characteristics[row.key.trim()] = row.value.trim();
    }
    setCreating(true);
    setError(null);
    try {
      await marketplace.createProduct(token, company.id, {
        name: name.trim(),
        category,
        characteristics,
        price_rub: Number(price),
        moq_units: Number(moq),
        lead_time_days: Number(leadTime),
      });
      const updated = await marketplace.getCompanyProducts(token, company.id);
      setProducts(updated);
      setName("");
      setRows([newRow("volume_ml", ""), newRow("coating", "")]);
      setPrice("");
      setMoq("");
      setLeadTime("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось создать товар.");
    } finally {
      setCreating(false);
    }
  }

  async function handlePublish(product: Product, published: boolean) {
    const token = getToken();
    if (!token) return;
    setPublishingId(product.id);
    setError(null);
    try {
      await marketplace.setProductPublished(token, product.id, published);
      const updated = await marketplace.getCompanyProducts(token, companyId);
      setProducts(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось изменить публикацию.");
    } finally {
      setPublishingId(null);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (meError) {
    return (
      <div>
        <h1 className="page-title">Мои товары</h1>
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
        <h1 className="page-title">Мои товары</h1>
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
        <h1 className="page-title">Мои товары</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          На главную
        </Link>
      </div>
      <p className="subtitle">Товары компании и управление публикацией</p>

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
        <h2>Новый товар</h2>
        <form onSubmit={handleCreate}>
          <div className="field">
            <label htmlFor="product_name">
              Название<span className="req">*</span>
            </label>
            <input
              id="product_name"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Например, Стакан 400 мл PE"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="product_category">
              Категория<span className="req">*</span>
            </label>
            <select id="product_category" value={category} onChange={(event) => setCategory(event.target.value)}>
              {PRODUCT_CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>
              Характеристики<span className="req">*</span>
            </label>
            {rows.map((row, index) => (
              <div key={index} className="char-row">
                <input
                  type="text"
                  placeholder="Ключ (например, volume_ml)"
                  value={row.key}
                  onChange={(event) => updateRow(index, { key: event.target.value })}
                />
                <input
                  type="text"
                  placeholder="Значение (например, 400)"
                  value={row.value}
                  onChange={(event) => updateRow(index, { value: event.target.value })}
                />
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                >
                  Удалить
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setRows((current) => [...current, newRow()])}
            >
              + Добавить характеристику
            </button>
          </div>
          <div className="field">
            <label htmlFor="product_price">
              Цена за единицу, ₽<span className="req">*</span>
            </label>
            <input
              id="product_price"
              type="number"
              min="0"
              step="0.01"
              value={price}
              onChange={(event) => setPrice(event.target.value)}
              placeholder="Например, 11.2"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="product_moq">
              Минимальный объём заказа, шт.<span className="req">*</span>
            </label>
            <input
              id="product_moq"
              type="number"
              min="1"
              value={moq}
              onChange={(event) => setMoq(event.target.value)}
              placeholder="Например, 20000"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="product_lead">
              Срок производства, дней<span className="req">*</span>
            </label>
            <input
              id="product_lead"
              type="number"
              min="1"
              value={leadTime}
              onChange={(event) => setLeadTime(event.target.value)}
              placeholder="Например, 9"
              required
            />
          </div>
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={creating}>
              {creating ? "Создаём..." : "Создать товар"}
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <h2>Список товаров</h2>
        {!loaded ? (
          <p className="hint mode-hint">Загрузка товаров...</p>
        ) : products.length === 0 ? (
          <p className="hint mode-hint">Товаров пока нет — создайте первый выше.</p>
        ) : (
          <ul className="company-list">
            {products.map((product) => (
              <li key={product.id} className="card">
                <div className="company-row">
                  <div>
                    <div className="company-item__name">{product.name}</div>
                    <div className="company-meta">
                      {product.category} · {formatRub(product.price_rub)} · МОЗ{" "}
                      {formatUnits(product.moq_units)} · {product.lead_time_days} дн.
                    </div>
                    <div className="company-meta">{formatCharacteristics(product.characteristics)}</div>
                  </div>
                  <span className={`badge ${product.is_published ? "badge-verified" : "badge-draft"}`}>
                    {product.is_published ? "Опубликован" : "Не опубликован"}
                  </span>
                </div>
                <div className="actions">
                  <button
                    type="button"
                    className={`btn btn-sm ${product.is_published ? "btn-secondary" : "btn-success"}`}
                    disabled={publishingId === product.id}
                    onClick={() => void handlePublish(product, !product.is_published)}
                  >
                    {publishingId === product.id
                      ? "..."
                      : product.is_published
                        ? "Снять с публикации"
                        : "Опубликовать"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
