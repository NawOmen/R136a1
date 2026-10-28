"use client";
import { useState } from "react";
import { getToken } from "../lib/api";
import { marketplaceFetchBlob } from "../lib/marketplace";
import { saveDownload } from "../lib/supplierWorkflow";
import { russianMessage } from "../lib/russianMessages";

export default function OrderExport({ id, companyId, specification = false }: { id: string; companyId: string; specification?: boolean }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function download(format: "xml" | "csv") {
    const token = getToken(); if (!token || busy) return;
    setBusy(true); setError("");
    try {
      const path = specification ? `/api/v3/needs/${id}/specification.csv?company_id=${companyId}` : `/api/v3/deals/${id}/export-1c?company_id=${companyId}&format=${format}`;
      saveDownload(await marketplaceFetchBlob(path, token), `porukam-${specification ? "specification" : "order"}-${id}.${format}`);
    } catch (e) { setError(e instanceof Error ? russianMessage(e.message) : "Не удалось сформировать файл. Повторите попытку."); }
    finally { setBusy(false); }
  }
  return <div className="order-export"><div className="actions"><button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void download(specification ? "csv" : "xml")}>{busy ? "Готовим файл…" : specification ? "Скачать спецификацию" : "Экспорт в 1С"}</button>{!specification && <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => void download("csv")}>Точный CSV заказа</button>}</div>{error && <p role="alert" className="alert alert-error">{error}</p>}{!specification && <details className="hint"><summary>Как загрузить в 1С</summary><p>XML CommerceML 2.10 предназначен для загрузки заказа покупателя в «1С:Управление торговлей» поставщика через настроенный файловый обмен с сайтом. Сопоставьте организацию, контрагентов, номенклатуру, единицы и НДС. Отключите автоматическое проведение и проверьте заказ перед записью.</p><p>Для своей закупочной базы или цены точнее копейки используйте CSV и сопоставление колонок в загрузке табличной части. Повторная выгрузка сохраняет идентификатор заказа.</p></details>}</div>;
}
