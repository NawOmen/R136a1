"use client";

// Деталь потребности: характеристики, файлы, список предложений.
// Покупатель может выбрать предложение (POST /offers/{id}/select) —
// создаётся сделка, потребность переходит в статус matched.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import {
  ApiError,
  Deal,
  DEAL_STATUS_LABELS,
  formatCharacteristics,
  formatRub,
  formatUnits,
  marketplace,
  Need,
  NEED_STATUS_LABELS,
  NEED_VISIBILITY_LABELS,
  Offer,
  OFFER_STATUS_LABELS,
} from "../../lib/marketplace";
import { useMe } from "../../lib/useMe";

export default function NeedDetailPage() {
  const params = useParams();
  const needId = typeof params.id === "string" ? params.id : "";
  const me = useMe();

  const [need, setNeed] = useState<Need | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [deal, setDeal] = useState<Deal | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectingId, setSelectingId] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token || !needId) return;
    let cancelled = false;
    Promise.all([marketplace.getNeed(token, needId), marketplace.getOffers(token, needId)])
      .then(([needData, offersData]) => {
        if (cancelled) return;
        setNeed(needData);
        setOffers(offersData);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(err instanceof ApiError ? err.message : "Не удалось загрузить потребность.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [needId]);

  async function handleSelect(offer: Offer) {
    const token = getToken();
    if (!token || !need) return;
    if (
      !window.confirm(
        "Выбрать это предложение и заключить сделку? Остальные предложения будут отклонены.",
      )
    ) {
      return;
    }
    setSelectingId(offer.id);
    setError(null);
    try {
      const created = await marketplace.selectOffer(token, offer.id);
      setDeal(created);
      const [needData, offersData] = await Promise.all([
        marketplace.getNeed(token, need.id),
        marketplace.getOffers(token, need.id),
      ]);
      setNeed(needData);
      setOffers(offersData);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось выбрать предложение.");
    } finally {
      setSelectingId(null);
    }
  }

  async function handleDownload(fileId: string, fileName: string) {
    const token = getToken();
    if (!token) return;
    setDownloadingId(fileId);
    setError(null);
    try {
      const blob = await marketplace.downloadNeedFile(token, fileId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = fileName;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось скачать файл.");
    } finally {
      setDownloadingId(null);
    }
  }

  async function handlePublish() {
    const token = getToken();
    if (!token || !need) return;
    if (!window.confirm("Опубликовать потребность для производителей?")) return;
    setPublishing(true);
    setError(null);
    try {
      setNeed(await marketplace.publishNeed(token, need.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось опубликовать потребность.");
    } finally {
      setPublishing(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (notFound || !need) {
    return (
      <div>
        <h1 className="page-title">Потребность не найдена</h1>
        <Link href="/needs" className="btn btn-secondary">
          Мои потребности
        </Link>
      </div>
    );
  }

  const buyerCompany = me.companies.find((company) => company.id === need.company_id);
  const isBuyer = buyerCompany?.membership?.can_buy === true;

  return (
    <div>
      <div className="company-row">
        <h1 className="page-title">{need.category}</h1>
        <div className="actions">
          <span className={`badge badge-${need.status}`}>{NEED_STATUS_LABELS[need.status]}</span>
          <span className={`badge badge-${need.visibility}`}>{NEED_VISIBILITY_LABELS[need.visibility]}</span>
          <Link href="/needs" className="btn btn-secondary btn-sm">
            Мои потребности
          </Link>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {isBuyer && need.status === "draft" && (
        <section className="card">
          <h2>Черновик потребности</h2>
          {buyerCompany?.verification_status === "verified" ? (
            <div className="actions">
              <button
                type="button"
                className="btn btn-success"
                disabled={publishing}
                onClick={() => void handlePublish()}
              >
                {publishing ? "Публикуем..." : "Опубликовать"}
              </button>
            </div>
          ) : (
            <p className="hint mode-hint">
              Черновик сохранён. Публикация станет доступна после проверки компании.
            </p>
          )}
        </section>
      )}

      {deal && (
        <section className="card">
          <div className="company-row">
            <h2>Сделка заключена</h2>
            <span className="badge badge-created">{DEAL_STATUS_LABELS[deal.status]}</span>
          </div>
          <p className="hint mode-hint">
            Объём: {formatUnits(deal.units)} · Сумма: {formatRub(deal.total_price_rub)}
          </p>
        </section>
      )}

      <section className="card">
        <h2>Параметры</h2>
        <dl className="company-details">
          <div>
            <dt>Характеристики</dt>
            <dd>{formatCharacteristics(need.characteristics)}</dd>
          </div>
          <div>
            <dt>Объём</dt>
            <dd>{formatUnits(need.volume_units)}</dd>
          </div>
          <div>
            <dt>Бюджет</dt>
            <dd>{formatRub(need.budget_rub)}</dd>
          </div>
          <div>
            <dt>Срок выполнения</dt>
            <dd>{need.deadline_date}</dd>
          </div>
          <div>
            <dt>Видимость</dt>
            <dd>{NEED_VISIBILITY_LABELS[need.visibility]}</dd>
          </div>
          <div>
            <dt>Статус</dt>
            <dd>{NEED_STATUS_LABELS[need.status]}</dd>
          </div>
        </dl>

        <h2 style={{ marginTop: 8 }}>Файлы</h2>
        {need.files.length === 0 ? (
          <p className="hint">Файлов нет.</p>
        ) : (
          <ul className="company-list">
            {need.files.map((file) => (
              <li key={file.id} className="company-item">
                <span>
                  <span className="company-item__name">{file.file_name}</span>
                  <span className="company-meta">{file.content_type}</span>
                </span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={downloadingId === file.id}
                  onClick={() => void handleDownload(file.id, file.file_name)}
                >
                  {downloadingId === file.id ? "Скачиваем..." : "Скачать"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>Предложения ({offers.length})</h2>
        {offers.length === 0 ? (
          <p className="hint mode-hint">Предложений пока нет.</p>
        ) : (
          <ul className="company-list">
            {offers.map((offer) => (
              <li key={offer.id} className="card">
                <div className="company-row">
                  <div>
                    <div className="company-item__name">
                      Предложение #{offer.id.slice(0, 8)}
                    </div>
                    <div className="company-meta">
                      Цена: {formatRub(offer.price_rub)} · Объём: {formatUnits(offer.available_units)} ·
                      Срок: {offer.lead_time_days} дн.
                    </div>
                  </div>
                  <span className={`badge badge-${offer.status}`}>
                    {OFFER_STATUS_LABELS[offer.status]}
                  </span>
                </div>
                {isBuyer && need.status === "open_for_offers" && offer.status === "sent" && (
                  <div className="actions">
                    <button
                      type="button"
                      className="btn btn-success btn-sm"
                      disabled={selectingId === offer.id}
                      onClick={() => void handleSelect(offer)}
                    >
                      {selectingId === offer.id ? "Заключаем сделку..." : "Выбрать предложение"}
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
