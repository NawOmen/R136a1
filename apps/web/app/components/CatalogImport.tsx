"use client";
import { useEffect, useRef, useState } from "react";
import { getToken } from "../lib/api";
import { formatCharacteristics, formatRub, itemUnit, marketplace, Product } from "../lib/marketplace";

type Preview = Awaited<ReturnType<typeof marketplace.importCatalog>>;
function template() {
  const body = "Название;Категория;Подкатегория;Цена;Минимум;Срок;Остаток;Характеристика: unit;Характеристика: материал\r\nОфисный стол;Товары для бизнеса;Мебель;7900;5;10;40;шт;ЛДСП\r\n";
  const url = URL.createObjectURL(new Blob(["\ufeff", body], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a"); link.href = url; link.download = "porukam-catalog-template.csv"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export default function CatalogImport({ companyId, onImported }: { companyId: string; onImported: (products: Product[]) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const key = useRef(""); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function run(commit: boolean) {
    const token = getToken(); if (!file || !token || busy || (commit && (!approved || !preview))) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await marketplace.importCatalog(token, companyId, file, commit ? { hash: preview!.content_hash, requestKey: key.current } : undefined);
      if (!alive.current) return;
      setPreview(result);
      if (commit) {
        setMessage(`Создано товаров: ${result.created_ids.length}. Проверьте карточки и документы перед публикацией.`);
        setApproved(false); setFile(null);
        const products = await marketplace.getCompanyProducts(token, companyId);
        if (alive.current) onImported(products);
      }
    } catch (reason) { if (alive.current) setError(reason instanceof Error ? reason.message : "Не удалось загрузить таблицу."); }
    finally { if (alive.current) setBusy(false); }
  }
  return <section className="card">
    <h2>Импорт товаров из таблицы</h2>
    <p className="hint">До 500 товаров, CSV UTF-8 до 2 МБ, разделитель — точка с запятой. Новые товары сохраняются черновиками; существующие карточки не заменяются.</p>
    <button type="button" className="btn btn-secondary" onClick={template}>Скачать шаблон</button>
    <div className="field"><label htmlFor="catalog-import-file">Таблица товаров</label><input id="catalog-import-file" type="file" accept=".csv,text/csv" disabled={busy} onChange={event => {
      setFile(event.target.files?.[0] ?? null); setPreview(null); setApproved(false); setMessage(""); setError(""); key.current = crypto.randomUUID();
    }} /></div>
    <button className="btn btn-secondary" type="button" disabled={!file || busy} onClick={() => void run(false)}>{busy ? "Обрабатываем…" : "Проверить таблицу"}</button>
    {error && <p className="alert alert-error" role="alert">{error}</p>}
    {message && <p className="alert alert-success" role="status">{message}</p>}
    {preview && <>
      {preview.errors.length > 0 && <div role="alert" className="alert alert-error"><p>Исправьте строки и загрузите файл повторно:</p><ul>{preview.errors.map(item => <li key={item.line}>Строка {item.line}: {item.message}</li>)}</ul></div>}
      <p>Корректных строк: {preview.rows.length}. Ошибок: {preview.errors.length}.</p>
      <div style={{ overflowX: "auto" }}><table><thead><tr><th>Строка</th><th>Товар / характеристики</th><th>Категория</th><th>Цена</th><th>Минимум</th><th>Остаток</th><th>Срок, дней</th></tr></thead><tbody>{preview.rows.map(({ line, product }) => <tr key={line}><td>{line}</td><td>{product.name}<br/>{formatCharacteristics(product.characteristics)}</td><td>{product.category} / {product.subcategory}</td><td>{formatRub(product.price_rub)} / {itemUnit(product.characteristics)}</td><td>{product.moq_units}</td><td>{product.stock_units ?? "Не указан"}</td><td>{product.lead_time_days}</td></tr>)}</tbody></table></div>
      {file && !preview.errors.length && preview.rows.length > 0 && <><label><input type="checkbox" checked={approved} disabled={busy} onChange={event => setApproved(event.target.checked)} /> Проверил строки и подтверждаю создание товаров на этих условиях</label><button className="btn btn-primary" type="button" disabled={!approved || busy} onClick={() => void run(true)}>Создать товары</button></>}
    </>}
  </section>;
}
