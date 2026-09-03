"use client";

// Создание потребности (POST /needs). Форма покупателя: компания (can_buy),
// категория, характеристики (пары «ключ/значение»), объём, бюджет, срок,
// адрес доставки (+ добавление адреса через prompt), видимость, файлы.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import { getToken } from "../../lib/api";
import {
  AgentRun,
  agents,
  FactValue,
  PROPERTY_STATUS_LABELS,
} from "../../lib/agents";
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
  const [requestDescription, setRequestDescription] = useState("");
  const [analysisRoute, setAnalysisRoute] = useState<"local" | "complex_auto">("local");
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyAddress, setBusyAddress] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);

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

  async function toggleRecording() {
    if (recording) { recorderRef.current?.stop(); return; }
    const token = getToken(); if (!token) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Запись с микрофона недоступна. Приложите готовый аудиофайл ниже."); return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: BlobPart[] = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop()); setRecording(false); setTranscribing(true);
        const file = new File([new Blob(chunks, { type: recorder.mimeType || "audio/webm" })], "голосовой-запрос.webm", { type: recorder.mimeType || "audio/webm" });
        void agents.transcribe(token, file).then((text) => setRequestDescription((current) => [current.trim(), text].filter(Boolean).join(" "))).catch((err: Error) => setError(err.message)).finally(() => setTranscribing(false));
      };
      recorderRef.current = recorder; recorder.start(); setRecording(true); setError(null);
    } catch { setError("Не удалось получить доступ к микрофону. Разрешите доступ или загрузите аудиофайл."); }
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

  async function handleAnalyze() {
    const token = getToken();
    if (!token) return;
    if (requestDescription.trim().length < 3) {
      setError("Опишите потребность хотя бы одним предложением.");
      return;
    }
    setAnalyzing(true);
    setError(null);
    try {
      const run = await agents.analyze(
        token,
        requestDescription.trim(),
        files,
        analysisRoute,
        company?.id,
      );
      setAgentRun(run);
      setAnswers({});
    } catch (err) {
      setError(err instanceof MarketplaceError ? err.message : "Не удалось разобрать материалы.");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleClarify() {
    const token = getToken();
    if (!token || !agentRun) return;
    const missing = agentRun.result.questions.some((question) => !answers[question.key]?.trim());
    if (missing) {
      setError("Ответьте на все показанные вопросы.");
      return;
    }
    const parsed: Record<string, FactValue> = {};
    for (const question of agentRun.result.questions) {
      const raw = answers[question.key].trim();
      const selectedOption = question.options.find((option) => String(option) === raw);
      parsed[question.key] = selectedOption ?? raw;
    }
    setAnalyzing(true);
    setError(null);
    try {
      setAgentRun(await agents.clarify(token, agentRun.id, parsed));
      setAnswers({});
    } catch (err) {
      setError(err instanceof MarketplaceError ? err.message : "Не удалось сохранить уточнения.");
    } finally {
      setAnalyzing(false);
    }
  }

  async function applyAgentResult() {
    const token = getToken();
    if (!token || !agentRun?.result.can_confirm) return;
    setAnalyzing(true);
    setError(null);
    let confirmedRun: AgentRun;
    try {
      confirmedRun = await agents.confirm(token, agentRun.id);
      setAgentRun(confirmedRun);
    } catch (err) {
      setError(err instanceof MarketplaceError ? err.message : "Не удалось подтвердить требования.");
      setAnalyzing(false);
      return;
    }
    const result = confirmedRun.result;
    const values = new Map(
      result.properties
        .filter((property) => property.value !== null)
        .map((property) => [property.key, property.value] as const),
    );
    const detectedCategory = PRODUCT_CATEGORIES.find(
      (item) => item === result.category || result.category.toLowerCase().includes(item),
    );
    setCategory(detectedCategory ?? "прочее");
    if (values.has("quantity_units")) setVolumeUnits(String(values.get("quantity_units")));
    if (values.has("budget_rub")) setBudgetRub(String(values.get("budget_rub")));
    if (values.has("lead_time_days")) {
      const days = Number(values.get("lead_time_days"));
      if (Number.isFinite(days) && days > 0) {
        const deadline = new Date();
        deadline.setDate(deadline.getDate() + days);
        setDeadlineDate(deadline.toISOString().slice(0, 10));
      }
    }
    const excluded = new Set(["quantity_units", "budget_rub", "lead_time_days", "delivery_city"]);
    const extractedRows = result.properties
      .filter((property) => property.value !== null && !excluded.has(property.key))
      .map((property) =>
        newRow(
          property.key,
          Array.isArray(property.value) ? property.value.join(", ") : String(property.value),
        ),
      );
    if (extractedRows.length > 0) setRows(extractedRows);
    setError(null);
    setAnalyzing(false);
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
      // Сначала сохраняем черновик и файлы; только затем публикуем целиком.
      for (const file of files) {
        await marketplace.uploadNeedFile(token, need.id, file);
      }
      if (company.verification_status === "verified") {
        await marketplace.publishNeed(token, need.id);
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
            Компания ещё не проверена — потребность сохранится как черновик, а опубликовать её можно
            будет после подтверждения компании.
          </p>
        )}

        <section className="agent-panel" aria-labelledby="materials-heading">
          <h2 id="materials-heading">Помощник по подготовке требований</h2>
          <p className="hint">
            Опишите задачу обычными словами и приложите материалы. Система покажет источники,
            предположения и противоречия; карточка изменится только после вашего подтверждения.
          </p>
          <div className="field">
            <label htmlFor="request_description">Что требуется купить</label>
            <textarea
              id="request_description"
              rows={4}
              value={requestDescription}
              onChange={(event) => setRequestDescription(event.target.value)}
              placeholder="Например: нужны 5000 крафтовых стаканов 400 мл с логотипом, доставка в Москву..."
            />
            <div className="voice-row"><button type="button" className={recording ? "btn btn-danger btn-sm" : "btn btn-secondary btn-sm"} disabled={transcribing} onClick={() => void toggleRecording()}>{transcribing ? "Распознаём…" : recording ? "Остановить запись" : "🎙 Продиктовать запрос"}</button><span className="hint">Речь распознаётся локально и подставляется в текст. В локальной сети микрофону может потребоваться HTTPS.</span></div>
          </div>
          <div className="field">
            <label htmlFor="need_files">
              Материалы<span className="opt">фото, PDF, текст или голосовое сообщение</span>
            </label>
            <input
              id="need_files"
              type="file"
              multiple
              accept="image/*,application/pdf,audio/*,text/plain,text/markdown"
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
            {files.length > 0 && (
              <p className="hint mode-hint">
                Выбрано файлов: {files.length} · {files.map((file) => file.name).join(", ")}
              </p>
            )}
          </div>
          <div className="field">
            <label htmlFor="analysis_route">Режим проверки</label>
            <select
              id="analysis_route"
              value={analysisRoute}
              onChange={(event) =>
                setAnalysisRoute(event.target.value as "local" | "complex_auto")
              }
            >
              <option value="local">Только локальная обработка</option>
              <option value="complex_auto">Углублённая проверка после обезличивания</option>
            </select>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            disabled={analyzing}
            onClick={() => void handleAnalyze()}
          >
            {analyzing ? "Разбираю материалы..." : "Разобрать материалы"}
          </button>

          {agentRun && (
            <div className="agent-result">
              <h3>Восстановленные требования</h3>
              <p>{agentRun.result.summary}</p>
              {agentRun.result.warnings.map((warning) => (
                <div key={warning} className="alert alert-error">{warning}</div>
              ))}
              <ul className="evidence-list">
                {agentRun.result.properties.map((property) => (
                  <li key={property.key}>
                    <div className="company-row">
                      <strong>{property.label}</strong>
                      <span className={`badge evidence-${property.status}`}>
                        {PROPERTY_STATUS_LABELS[property.status]}
                      </span>
                    </div>
                    <div>{property.value === null ? "—" : String(property.value)}</div>
                    {property.sources.length > 0 && (
                      <details>
                        <summary>Откуда взята характеристика?</summary>
                        {property.sources.map((source, index) => (
                          <p key={`${source.source_id}-${index}`} className="hint">
                            {source.source_name} · уверенность {Math.round(source.confidence * 100)}%
                            {source.excerpt ? ` · ${source.excerpt}` : ""}
                          </p>
                        ))}
                      </details>
                    )}
                  </li>
                ))}
              </ul>

              {agentRun.result.questions.length > 0 && (
                <div className="clarification-box">
                  <h3>Нужно уточнение</h3>
                  {agentRun.result.questions.map((question) => (
                    <div className="field" key={question.key}>
                      <label htmlFor={`answer_${question.key}`}>{question.question}</label>
                      {question.options.length > 0 ? (
                        <select
                          id={`answer_${question.key}`}
                          value={answers[question.key] ?? ""}
                          onChange={(event) =>
                            setAnswers((current) => ({ ...current, [question.key]: event.target.value }))
                          }
                        >
                          <option value="">— выберите —</option>
                          {question.options.map((option, index) => (
                            <option key={index} value={String(option)}>{String(option)}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          id={`answer_${question.key}`}
                          value={answers[question.key] ?? ""}
                          onChange={(event) =>
                            setAnswers((current) => ({ ...current, [question.key]: event.target.value }))
                          }
                        />
                      )}
                    </div>
                  ))}
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={analyzing}
                    onClick={() => void handleClarify()}
                  >
                    Сохранить ответы
                  </button>
                </div>
              )}

              {agentRun.result.matches.length > 0 && (
                <div>
                <h3>Почему подошёл этот производитель</h3>
                  <ul className="company-list">
                    {agentRun.result.matches.map((match) => (
                      <li key={match.company_id} className="company-item">
                        <strong>{match.company_name}</strong>
                        <span className="match-score">{match.score}/100</span>
                        <ul className="match-reasons">{match.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {agentRun.result.can_confirm && agentRun.state !== "confirmed_by_user" && (
                <button
                  type="button"
                  className="btn btn-success"
                  disabled={analyzing}
                  onClick={() => void applyAgentResult()}
                >
                  Перенести подтверждённые данные в карточку
                </button>
              )}
              {agentRun.state === "confirmed_by_user" && (
                <p className="hint mode-hint">Подтверждённые данные перенесены в форму ниже.</p>
              )}
              <details>
                <summary>Журнал обработки</summary>
                {agentRun.tool_calls.map((call) => (
                  <p key={call.id} className="hint">
                    {call.status === "success" ? "Выполнено" : "Ошибка"}: {call.tool_name} — {call.output_summary}
                  </p>
                ))}
              </details>
            </div>
          )}
        </section>

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

        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={submitting || !company}>
            {submitting
              ? "Сохраняем..."
              : company?.verification_status === "verified"
                ? "Создать и опубликовать"
                : "Сохранить черновик"}
          </button>
          <Link href="/needs" className="btn btn-secondary">
            Отмена
          </Link>
        </div>
      </form>
    </div>
  );
}
