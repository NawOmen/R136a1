"use client";

// Создание потребности (POST /needs). Форма покупателя: компания (can_buy),
// категория, характеристики (пары «ключ/значение»), объём, бюджет, срок,
// адрес доставки (+ добавление адреса через prompt), видимость, файлы.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { getToken } from "../../lib/api";
import {
  ApiError as MarketplaceError,
  DeliveryAddress,
  marketplace,
  NEED_VISIBILITY_LABELS,
  NeedVisibility,
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

export default function NewNeedPage() {
  const router = useRouter();
  const {
    loading,
    error: meError,
    available,
    company,
    companyId,
    setCompanyId,
  } = useCompanySelector("can_buy");

  const [addresses, setAddresses] = useState<DeliveryAddress[]>([]);
  const [category, setCategory] = useState(PRODUCT_CATEGORIES[0]);
  const [rows, setRows] = useState<CharacteristicRow[]>([
    newRow("volume_ml", ""),
    newRow("coating", ""),
  ]);
  const [volumeUnits, setVolumeUnits] = useState("");
  const [budgetRub, setBudgetRub] = useState("");
  const [deadlineDate, setDeadlineDate] = useState("");
  const [deliveryAddressId, setDeliveryAddressId] = useState("");
  const [visibility, setVisibility] = useState<NeedVisibility>("open_anonymized");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyAddress, setBusyAddress] = useState(false);

  // Загрузка адресов выбранной компании
  useEffect(() => {
    const token = getToken();
    if (!token || !companyId) return;
    let cancelled = false;
    marketplace
      .getAddresses(token, companyId)
      .then((list) => {
        if (cancelled) return;
        setAddresses(list);
        const preferred = list.find((item) => item.is_default) ?? list[0];
        setDeliveryAddressId((current) => (list.some((item) => item.id === current) ? current : preferred?.id ?? ""));
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof MarketplaceError ? err.message : "Не удалось загрузить адреса доставки.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  function updateRow(index: number, patch: Partial<CharacteristicRow>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  async function handleAddAddress() {
    const token = getToken();
    if (!token || !company) return;
    const address = window.prompt("Введите адрес доставки (улица, дом):");
    if (!address || !address.trim()) return;
    const city = window.prompt("Введите город:") ?? "";
    const region = window.prompt("Введите регион (например, Свердловская область):") ?? "";
    if (address.trim().length < 5) {
      setError("Адрес слишком короткий — минимум 5 символов.");
      return;
    }
    if (city.trim().length < 2) {
      setError("Укажите город (минимум 2 символа).");
      return;
    }
    setBusyAddress(true);
    setError(null);
    try {
      await marketplace.createAddress(token, company.id, {
        address: address.trim(),
        city: city.trim(),
        region: region.trim() || "Россия",
        is_default: addresses.length === 0,
      });
      const updated = await marketplace.getAddresses(token, company.id);
      setAddresses(updated);
      const added = updated.find((item) => item.address === address.trim());
      setDeliveryAddressId(added?.id ?? updated[0]?.id ?? "");
    } catch (err) {
      setError(err instanceof MarketplaceError ? err.message : "Не удалось добавить адрес.");
    } finally {
      setBusyAddress(false);
    }
  }

  function validate(): string | null {
    if (rows.length < 2) {
      return "Добавьте минимум две характеристики: объём и покрытие.";
    }
    if (rows.some((row) => !row.key.trim() || !row.value.trim())) {
      return "Заполните ключ и значение каждой характеристики.";
    }
    const volume = Number(volumeUnits);
    if (!volumeUnits || Number.isNaN(volume) || volume <= 0) {
      return "Укажите объём (шт.).";
    }
    const budget = Number(budgetRub);
    if (!budgetRub || Number.isNaN(budget) || budget <= 0) {
      return "Укажите бюджет (₽).";
    }
    if (!deadlineDate) {
      return "Укажите срок выполнения.";
    }
    if (!deliveryAddressId) {
      return "Выберите или добавьте адрес доставки.";
    }
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getToken();
    if (!token || !company) return;

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    const characteristics: Record<string, unknown> = {};
    for (const row of rows) {
      characteristics[row.key.trim()] = row.value.trim();
    }

    setError(null);
    setSubmitting(true);
    try {
      const need = await marketplace.createNeed(token, {
        company_id: company.id,
        category,
        characteristics,
        volume_units: Number(volumeUnits),
        budget_rub: Number(budgetRub),
        deadline_date: deadlineDate,
        delivery_address_id: deliveryAddressId,
        visibility,
      });
      // Файлы загружаются после создания потребности
      for (const file of files) {
        await marketplace.uploadNeedFile(token, need.id, file);
      }
      router.push(`/needs/${need.id}`);
    } catch (err) {
      setError(err instanceof MarketplaceError ? err.message : "Не удалось создать потребность.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <p className="hint">Загрузка...</p>;

  if (meError) {
    return (
      <div>
        <h1 className="page-title">Создание потребности</h1>
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
        <h1 className="page-title">Создание потребности</h1>
        <div className="alert alert-error">
          У вас нет компании с правом «Покупаю». Создайте компанию и включите режим покупки.
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
        <h1 className="page-title">Создание потребности</h1>
        <Link href="/needs" className="btn btn-secondary btn-sm">
          Мои потребности
        </Link>
      </div>
      <p className="subtitle">
        Опишите, что нужно купить, — производители смогут предложить свои условия
      </p>

      {error && <div className="alert alert-error">{error}</div>}

      <form className="card" onSubmit={handleSubmit}>
        {available.length > 1 ? (
          <div className="field">
            <label htmlFor="company_id">
              Компания<span className="req">*</span>
            </label>
            <select id="company_id" value={companyId} onChange={(event) => setCompanyId(event.target.value)}>
              {available.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.display_name}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="field">
            <label>Компания<span className="req">*</span></label>
            <p className="hint">{company?.display_name}</p>
          </div>
        )}

        {company && company.verification_status !== "verified" && (
          <p className="hint mode-hint">
            Компания ещё не проверена — создание потребности может быть недоступно до подтверждения.
          </p>
        )}

        <div className="field">
          <label htmlFor="category">
            Категория<span className="req">*</span>
          </label>
          <select id="category" value={category} onChange={(event) => setCategory(event.target.value)}>
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
            <span className="opt">минимум объём и покрытие</span>
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
          <label htmlFor="volume_units">
            Объём, шт.<span className="req">*</span>
          </label>
          <input
            id="volume_units"
            type="number"
            min="1"
            value={volumeUnits}
            onChange={(event) => setVolumeUnits(event.target.value)}
            placeholder="Например, 120000"
            required
          />
        </div>

        <div className="field">
          <label htmlFor="budget_rub">
            Бюджет, ₽<span className="req">*</span>
          </label>
          <input
            id="budget_rub"
            type="number"
            min="0"
            step="0.01"
            value={budgetRub}
            onChange={(event) => setBudgetRub(event.target.value)}
            placeholder="Например, 1900000"
            required
          />
        </div>

        <div className="field">
          <label htmlFor="deadline_date">
            Срок выполнения<span className="req">*</span>
          </label>
          <input
            id="deadline_date"
            type="date"
            value={deadlineDate}
            onChange={(event) => setDeadlineDate(event.target.value)}
            required
          />
        </div>

        <div className="field">
          <label htmlFor="delivery_address_id">
            Адрес доставки<span className="req">*</span>
          </label>
          <div className="char-row">
            <select
              id="delivery_address_id"
              value={deliveryAddressId}
              onChange={(event) => setDeliveryAddressId(event.target.value)}
              required
            >
              <option value="">— выберите адрес —</option>
              {addresses.map((item) => (
                <option key={item.id} value={item.id}>
                  {[item.city, item.address, item.region].filter(Boolean).join(", ")}
                  {item.is_default ? " (основной)" : ""}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={busyAddress}
              onClick={() => void handleAddAddress()}
            >
              {busyAddress ? "Добавляем..." : "+ Добавить адрес"}
            </button>
          </div>
          {addresses.length === 0 && (
            <p className="hint mode-hint">Адресов пока нет — добавьте первый через кнопку выше.</p>
          )}
        </div>

        <div className="field">
          <label htmlFor="visibility">
            Видимость<span className="req">*</span>
          </label>
          <select
            id="visibility"
            value={visibility}
            onChange={(event) => setVisibility(event.target.value as NeedVisibility)}
          >
            {(Object.keys(NEED_VISIBILITY_LABELS) as NeedVisibility[]).map((item) => (
              <option key={item} value={item}>
                {NEED_VISIBILITY_LABELS[item]}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="need_files">
            Файлы (ТЗ, чертежи)<span className="opt">необязательно, можно несколько</span>
          </label>
          <input
            id="need_files"
            type="file"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
          {files.length > 0 && (
            <p className="hint mode-hint">
              Выбрано файлов: {files.length} · {files.map((file) => file.name).join(", ")}
            </p>
          )}
        </div>

        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={submitting || !company}>
            {submitting ? "Создаём..." : "Создать потребность"}
          </button>
          <Link href="/needs" className="btn btn-secondary">
            Отмена
          </Link>
        </div>
      </form>
    </div>
  );
}
