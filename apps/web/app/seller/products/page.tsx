"use client";
import { lineAmount, previewLineAmount } from "../../lib/money";

// Товары компании (GET/POST /companies/{id}/products): список, форма создания,
// публикация/снятие с публикации (POST /products/{id}/publish).

import Link from "next/link";
import PhysicalQuantityReview from "../../components/PhysicalQuantityReview";
import ProfileRevisionPanel from "../../components/ProfileRevisionPanel";
import CatalogImport from "../../components/CatalogImport";
import PackagingConversionPanel from "../../components/PackagingConversionPanel";
import CharacteristicSuggestions from "../../components/CharacteristicSuggestions";
import { characteristicField } from "../../lib/categoryProfiles";
import { countUserCharacteristics, requiredCharacteristicKeys } from "../../lib/categoryProfiles";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import {
  ApiError,
  formatCharacteristics,
  formatRub,
  formatUnits,
  itemUnit,
  marketplace,
  Product,
  PRODUCT_CATEGORIES,
  PRODUCT_CATEGORY_TREE,
  ProductPriceTier,
} from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

interface CharacteristicRow {
  key: string;
  value: string;
}

function newRow(key = "", value = ""): CharacteristicRow {
  return { key, value };
}

function userRowCount(rows: CharacteristicRow[], category: string, subcategory: string): number {
  return countUserCharacteristics(rows, category, subcategory);
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
  const [subcategory, setSubcategory] = useState(PRODUCT_CATEGORY_TREE[PRODUCT_CATEGORIES[0]][0]);
  const [rows, setRows] = useState<CharacteristicRow[]>([
    newRow("unit", "шт"),
    newRow("материал", ""),
  ]);
  const [price, setPrice] = useState("");
  const [moq, setMoq] = useState("");
  const [leadTime, setLeadTime] = useState("");
  // Остаток склада: нужен для роли «поставка со склада» и для черновика КП.
  const [stock, setStock] = useState("");
  const [tiers, setTiers] = useState<ProductPriceTier[]>([]);
  const [image, setImage] = useState<File | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingRevision, setEditingRevision] = useState<number>(1);
  const [sources, setSources] = useState<{ label: string; reference: string }[]>([]);
  const [creating, setCreating] = useState(false);
  const [quantityApproved, setQuantityApproved] = useState(false);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [duplicatingId, setDuplicatingId] = useState<string | null>(null);

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
    if (rows.some((row) => !row.key.trim() || !row.value.trim())) {
      setError("Заполните ключ и значение каждой характеристики.");
      return;
    }
    const keys = rows.map((row) => row.key.trim().toLowerCase().replaceAll("ё", "е"));
    if (new Set(keys).size !== keys.length) {
      setError("Названия характеристик не должны повторяться.");
      return;
    }
    const characteristics: Record<string, unknown> = {};
    for (const row of rows) {
      characteristics[row.key.trim()] = row.value.trim();
    }
    setCreating(true);
    setError(null);
    try {
    const input = {
      quantity_conversion_approved: quantityApproved,
      name: name.trim(),
      category,
      subcategory,
      characteristics,
      sources: sources.filter((item) => item.label.trim() && item.reference.trim()),
      price_rub: String(price),
      price_tiers: tiers,
      moq_units: Number(moq),
      lead_time_days: Number(leadTime),
      stock_units: stock.trim() === "" ? null : Number(stock),
    };
      const preview = await marketplace.previewPhysicalQuantity("product", input);
      const validation = await marketplace.validateCharacteristics({ category, subcategory, characteristics: preview.normalized.characteristics as Record<string, unknown>, moq_units: preview.conversion.quantities.moq_units ?? 0 });
      if (!validation.valid) { setError(validation.errors.join(". ")); return; }
      if (editingId) {
        const previous = products.find(item=>item.id === editingId);
        const labels: Record<string,string> = {name:"Название",category:"Категория",subcategory:"Подкатегория",characteristics:"Характеристики",price_rub:"Цена",price_tiers:"Ценовые ступени",moq_units:"MOQ",lead_time_days:"Срок",stock_units:"Остаток"};
        const changes = previous ? Object.entries(labels).filter(([key])=>JSON.stringify(previous[key as keyof Product]) !== JSON.stringify(preview.normalized[key])).map(([key,label])=>`${label}: ${JSON.stringify(previous[key as keyof Product])} → ${JSON.stringify(preview.normalized[key])}`) : [];
        if (changes.length && !window.confirm(`Сохранить новую версию каталога?\n${changes.join("\n")}\nСогласованные сделки сохранят свои цены и условия.`)) return;
      }
      const saved = editingId
        ? await marketplace.updateProduct(token, editingId, { ...input, expected_revision: editingRevision })
        : await marketplace.createProduct(token, company.id, input);
      // Сразу принимаем ревизию сохранённой карточки: повторная отправка
      // старого снимка после упавшей загрузки фото даёт 409, а не перезапись.
      setEditingRevision(saved.revision ?? editingRevision);
      setProducts((current) => current.some((item) => item.id === saved.id)
        ? current.map((item) => (item.id === saved.id ? saved : item))
        : [...current, saved]);
      if (image) {
        try {
          await marketplace.uploadProductImage(token, saved.id, image);
        } catch (uploadError) {
          setError(uploadError instanceof ApiError ? uploadError.message : "Карточка сохранена, но фото не загрузилось. Повторите загрузку отдельно.");
        }
      }
      const updated = await marketplace.getCompanyProducts(token, company.id);
      setProducts(updated);
      setName("");
      setRows([newRow("unit", "шт"), newRow("материал", "")]);
      setSources([]);
      setPrice("");
      setMoq("");
      setLeadTime("");
      setStock("");
      setTiers([]);
      setImage(null);
      setEditingId(null);
      setEditingRevision(1);
      setSources([]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось создать товар.");
    } finally {
      setCreating(false);
    }
  }

  function beginEdit(product: Product) {
    setEditingId(product.id);
    setEditingRevision(product.revision ?? 1);
    setSources((product.sources ?? []).map((item) => ({ label: item.label, reference: item.reference })));
    setName(product.name);
    setCategory(product.category);
    setSubcategory(product.subcategory ?? PRODUCT_CATEGORY_TREE[product.category]?.[0] ?? "Другая продукция");
    setRows(Object.entries(product.characteristics).map(([key, value]) => newRow(key, String(value))));
    setPrice(String(product.price_rub));
    setMoq(String(product.moq_units));
    setLeadTime(String(product.lead_time_days));
    setStock(product.stock_units != null ? String(product.stock_units) : "");
    setTiers(product.price_tiers);
    window.scrollTo({ top: 0, behavior: "smooth" });
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

  async function handleDuplicate(product: Product) {
    const token = getToken();
    if (!token) return;
    setDuplicatingId(product.id);
    setError(null);
    try {
      await marketplace.duplicateProduct(token, product.id);
      const updated = await marketplace.getCompanyProducts(token, companyId);
      setProducts(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось создать черновик из шаблона.");
    } finally {
      setDuplicatingId(null);
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

      {company?.membership?.is_admin && <CatalogImport key={companyId} companyId={companyId} onImported={setProducts} />}

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
        <h2>{editingId ? "Редактирование товара" : "Новый товар"}</h2>
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
              placeholder="Например, Гофрокороб 400×300×300 мм"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="product_category">
              Категория<span className="req">*</span>
            </label>
            <select id="product_category" value={category} onChange={(event) => {
              const value = event.target.value;
              setCategory(value);
              setSubcategory(PRODUCT_CATEGORY_TREE[value][0]);
            }}>
              {PRODUCT_CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="product_subcategory">Подкатегория<span className="req">*</span></label>
            <select id="product_subcategory" value={subcategory} onChange={(event) => setSubcategory(event.target.value)}>
              {PRODUCT_CATEGORY_TREE[category].map((item) => <option key={item}>{item}</option>)}
            </select>
          </div>
          <div className="field">
            <label>
              Характеристики
            </label>
            <CharacteristicSuggestions category={category} subcategory={subcategory} keys={rows.map((row) => row.key)}
              disabled={creating} product onAdd={(key) => setRows((current) => {
                const required = requiredCharacteristicKeys(category, subcategory);
                const normalizeKey = (value: string) => value.trim().toLowerCase().replaceAll("ё", "е");
                if (userRowCount(current, category, subcategory) < 25 || required.has(normalizeKey(key))) {
                  return [...current, newRow(key)];
                }
                return current;
              })} />
            {rows.map((row, index) => (
              <div key={index} className="char-row">
                <input
                  type="text"
                  placeholder="Характеристика (например, материал)"
                  aria-label={`Характеристика ${index + 1}: название`}
                  value={row.key}
                  onChange={(event) => updateRow(index, { key: event.target.value })}
                />
                <input
                  type="text"
                  placeholder={characteristicField(category, subcategory, row.key)?.label ?? "Значение (например, 400)"}
                  aria-label={`Характеристика ${index + 1}: ${characteristicField(category, subcategory, row.key)?.label ?? "значение"}`}
                  inputMode={characteristicField(category, subcategory, row.key)?.type !== "text" && characteristicField(category, subcategory, row.key) ? "decimal" : "text"}
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
              disabled={userRowCount(rows, category, subcategory) >= 25}
              onClick={() => setRows((current) => userRowCount(current, category, subcategory) < 25 ? [...current, newRow()] : current)}
            >
              + Добавить характеристику ({userRowCount(rows, category, subcategory)}/25 сверх системных и обязательных)
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
              step="any"
              value={price}
              onChange={(event) => setPrice(event.target.value)}
              placeholder="Например, 11.2"
              required
            />
          </div>
          <div className="field">
            <label>Цены по объёму <span className="opt">необязательно, до 10 ступеней</span></label>
            {tiers.map((tier, index) => (
              <div className="char-row" key={index}>
                <input type="number" min="0.000001" step="any" value={tier.min_units} aria-label="Объём ступени"
                  onChange={(event) => setTiers((current) => current.map((item, i) => i === index ? {...item, min_units: Number(event.target.value)} : item))} />
                <input type="number" min="0.000000000001" step="any" value={tier.unit_price_rub} aria-label="Цена ступени"
                  onChange={(event) => setTiers((current) => current.map((item, i) => i === index ? {...item, unit_price_rub: String(event.target.value)} : item))} />
                <span className="company-meta">{formatRub(previewLineAmount(tier.unit_price_rub, tier.min_units))} за партию</span>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setTiers((current) => current.filter((_, i) => i !== index))}>Удалить</button>
              </div>
            ))}
            <button type="button" className="btn btn-secondary btn-sm" disabled={tiers.length >= 10}
              onClick={() => setTiers((current) => [...current, {min_units: Number(moq) || 1, unit_price_rub: String(price) || 1}])}>
              + Добавить ценовую ступень
            </button>
          </div>
          <div className="field">
            <label>Источники данных карточки <span className="opt">необязательно, до 10: прайс, паспорт, замер</span></label>
            {sources.map((item, index) => (
              <div className="char-row" key={index}>
                <input type="text" placeholder="Название источника" aria-label={`Источник ${index + 1}: название`}
                  value={item.label} maxLength={120}
                  onChange={(event) => setSources((current) => current.map((entry, i) => i === index ? { ...entry, label: event.target.value } : entry))} />
                <input type="text" placeholder="Ссылка: прайс-2026-10, паспорт" aria-label={`Источник ${index + 1}: ссылка`}
                  value={item.reference} maxLength={300}
                  onChange={(event) => setSources((current) => current.map((entry, i) => i === index ? { ...entry, reference: event.target.value } : entry))} />
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setSources((current) => current.filter((_, i) => i !== index))}>Удалить</button>
              </div>
            ))}
            <button type="button" className="btn btn-secondary btn-sm" disabled={sources.length >= 10}
              onClick={() => setSources((current) => [...current, { label: "", reference: "" }])}>
              + Добавить источник
            </button>
          </div>
          <div className="field">
            <label htmlFor="product_image">Фото товара <span className="opt">PNG, JPG или WebP, до 8 МБ</span></label>
            <input id="product_image" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setImage(event.target.files?.[0] ?? null)} />
          </div>
          <div className="field">
            <label htmlFor="product_moq">
              Минимальное количество единиц заказа<span className="req">*</span>
            </label>
            <input
              id="product_moq"
              type="number"
              step="any"
              min="0.000001"
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
              step="1"
              value={leadTime}
              onChange={(event) => setLeadTime(event.target.value)}
              placeholder="Например, 9"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="product_stock">
              Остаток в единицах заказа<span className="opt">для поставки со склада; пусто — под заказ</span>
            </label>
            <input
              id="product_stock"
              type="number"
              step="any"
              min="0"
              value={stock}
              onChange={(event) => setStock(event.target.value)}
              placeholder="Например, 4000"
            />
          </div>
          <PhysicalQuantityReview kind="product" values={{ characteristics: Object.fromEntries(rows.filter(row => row.key.trim()).map(row => [row.key.trim(), row.value])), moq_units: moq, stock_units: stock || null, price_rub: price, price_tiers: tiers }} approved={quantityApproved} onApproval={setQuantityApproved} />
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={creating}>
              {creating ? "Сохраняем..." : editingId ? "Сохранить изменения" : "Создать товар"}
            </button>
            {editingId && <button type="button" className="btn btn-secondary" onClick={() => { setEditingId(null); setEditingRevision(1); setSources([]); }}>Отменить</button>}
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
                    <div className="company-item__name">{product.is_published ? <Link href={`/catalog/${product.id}`}>{product.name}</Link> : <>{product.name} <span className="company-meta">(черновик — только здесь)</span></>}</div>
                    <div className="company-meta">
                      {product.category} / {product.subcategory ?? "Без подкатегории"} · {formatRub(product.price_rub, 12)} / {itemUnit(product.characteristics)} · МОЗ{" "}
                      {formatUnits(product.moq_units, itemUnit(product.characteristics))} · {product.lead_time_days} дн.
                    </div>
                    <div className="company-meta">{formatCharacteristics(product.characteristics, product.category_profile)}</div>
                    {company?.membership?.is_admin && <ProfileRevisionPanel key={`${product.id}:${JSON.stringify(product.category_profile)}`} kind="products" id={product.id} draft={!product.is_published} onAdopted={async () => { const token = getToken(); if (token && companyId) setProducts(await marketplace.getCompanyProducts(token, companyId)); }} />}
                    {company?.membership?.is_admin && ["упак","упаковка","рулон","бухта","комплект","мешок"].includes(itemUnit(product.characteristics)) && <PackagingConversionPanel key={`${product.id}:pack:${JSON.stringify(product.category_profile)}:${JSON.stringify(product.quantity_conversion)}`} product={product} onSaved={async()=>{const token=getToken();if(token && companyId)setProducts(await marketplace.getCompanyProducts(token,companyId));}} />}
                    {product.price_tiers.map((tier) => <div className="company-meta" key={tier.min_units}>
                      От {formatUnits(tier.min_units, itemUnit(product.characteristics))}: {formatRub(tier.unit_price_rub, 12)} / {itemUnit(product.characteristics)} · {formatRub(lineAmount(tier.unit_price_rub, tier.min_units))} за партию
                    </div>)}
                  </div>
                  <span className={`badge ${product.is_published ? "badge-verified" : "badge-draft"}`}>
                    {product.is_published ? "Опубликован" : "Не опубликован"}
                  </span>
                </div>
                <div className="actions">
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => beginEdit(product)}>Редактировать</button>
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
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={duplicatingId === product.id}
                    title="Создать черновик-копию без публикации"
                    onClick={() => void handleDuplicate(product)}
                  >
                    {duplicatingId === product.id ? "..." : "Дублировать как черновик"}
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
