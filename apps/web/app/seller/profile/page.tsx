"use client";

// Производственный профиль продавца (GET/PUT /companies/{id}/production-profile).

import { russianMessage } from "../../lib/russianMessages";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import { ApiError, marketplace, ProductionProfile } from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";

const EMPTY_PROFILE: ProductionProfile = {
  company_id: "",
  production_site_address: "",
  region: "",
  about: "",
};

export default function SellerProfilePage() {
  const {
    loading,
    error: meError,
    available,
    company,
    companyId,
    setCompanyId,
  } = useCompanySelector("can_sell");

  const [profile, setProfile] = useState<ProductionProfile>(EMPTY_PROFILE);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    setLoaded(false);
    setError(null);
    marketplace
      .getProductionProfile(token, companyId)
      .then((data) => {
        if (!cancelled) {
          setProfile({
            company_id: data.company_id,
            production_site_address: data.production_site_address ?? "",
            region: data.region ?? "",
            about: data.about ?? "",
          });
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          // Профиль ещё не заполнен
          setProfile({ ...EMPTY_PROFILE, company_id: companyId });
        } else {
          setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось загрузить профиль.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await marketplace.updateProductionProfile(token, company.id, {
        production_site_address: profile.production_site_address?.trim() ?? "",
        region: profile.region?.trim() ?? "",
        about: profile.about?.trim() ?? "",
      });
      if (photo) await marketplace.uploadProductionPhoto(token, company.id, photo);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? russianMessage(err.message) : "Не удалось сохранить профиль.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (meError) {
    return (
      <div>
        <h1 className="page-title">Производственный профиль</h1>
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
        <h1 className="page-title">Производственный профиль</h1>
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
        <h1 className="page-title">Производственный профиль</h1>
        <Link href="/dashboard" className="btn btn-secondary btn-sm">
          На главную
        </Link>
      </div>
      <p className="subtitle">Информация о производственной площадке для покупателей</p>

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

      {saved && <div className="alert alert-success">Профиль сохранён.</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {!loaded ? (
        <p className="hint">Загрузка профиля...</p>
      ) : (
        <form className="card" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="production-photo">Фотография производства<span className="opt">PNG, JPG или WebP до 8 МБ</span></label>
            <input id="production-photo" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setPhoto(event.target.files?.[0] ?? null)} />
            <p className="hint">Показывается на публичной странице производителя. Используйте только синтетическое или разрешённое изображение.</p>
          </div>
          <div className="field">
            <label htmlFor="production_site_address">
              Адрес производства<span className="req">*</span>
            </label>
            <input
              id="production_site_address"
              type="text"
              value={profile.production_site_address ?? ""}
              onChange={(event) =>
                setProfile({ ...profile, production_site_address: event.target.value })
              }
              required
            />
          </div>
          <div className="field">
            <label htmlFor="region">
              Регион<span className="req">*</span>
            </label>
            <input
              id="region"
              type="text"
              value={profile.region ?? ""}
              onChange={(event) => setProfile({ ...profile, region: event.target.value })}
              placeholder="Например, Свердловская область"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="about">
              О компании<span className="opt">необязательно</span>
            </label>
            <textarea
              id="about"
              value={profile.about ?? ""}
              onChange={(event) => setProfile({ ...profile, about: event.target.value })}
              placeholder="Коротко о производстве и возможностях"
            />
          </div>
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Сохраняем..." : "Сохранить профиль"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
