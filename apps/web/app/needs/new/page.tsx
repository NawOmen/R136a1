"use client";

// Создание потребности (POST /needs). Форма покупателя: компания (can_buy),
// категория, характеристики (пары «ключ/значение»), объём, бюджет, срок,
// адрес доставки (+ добавление адреса через prompt), видимость, файлы.

import { canonicalCharacteristicKey } from "../../lib/categoryProfiles";
import { russianMessage } from "../../lib/russianMessages";
import { russianLabel, displayValue, fieldName, systemText } from "../../lib/presentation";
import RequirementSource from "../../components/RequirementSource";
import { draftFiles } from "../../lib/draftFiles";

import PhysicalQuantityReview from "../../components/PhysicalQuantityReview";
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
  PRODUCT_CATEGORY_TREE,
} from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";
import CharacteristicSuggestions from "../../components/CharacteristicSuggestions";
import { characteristicField, countUserCharacteristics, requiredCharacteristicKeys, resolveAgentCategory } from "../../lib/categoryProfiles";
import { CapabilityDescription } from "../../components/CapabilityDescription";
import { ValidatedFields } from "../../components/ValidatedFields";

interface CharacteristicRow {
  key: string;
  value: string;
}

function newRow(key = "", value = ""): CharacteristicRow {
  return { key, value };
}

export default function NewNeedPage() {
  const manualRef = useRef<HTMLDetailsElement>(null);
  const [manualExpanded, setManualExpanded] = useState(false);
  const [quantityApproved, setQuantityApproved] = useState(false);
  const router = useRouter();
  const {
    loading,
    user,
    error: meError,
    available,
    company,
    companyId,
    setCompanyId,
  } = useCompanySelector("can_buy");

  const [addresses, setAddresses] = useState<DeliveryAddress[]>([]);
  const [category, setCategory] = useState(PRODUCT_CATEGORIES[0]);
  const [subcategory, setSubcategory] = useState("");
  const [rows, setRows] = useState<CharacteristicRow[]>([
    newRow("unit", "шт"),
    newRow(),
  ]);
  const [volumeUnits, setVolumeUnits] = useState("");
  const [budgetRub, setBudgetRub] = useState("");
  const [deadlineDate, setDeadlineDate] = useState("");
  const [deliveryAddressId, setDeliveryAddressId] = useState("");
  const [visibility, setVisibility] = useState<NeedVisibility>("open_anonymized");
  const [files, setFiles] = useState<File[]>([]);
  const [requestDescription, setRequestDescription] = useState("");
  const [analysisRoute, setAnalysisRoute] = useState<"local" | "complex_auto">("local");
  const [externalContextAllowed, setExternalContextAllowed] = useState(false);
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [trial, setTrial] = useState<{ enabled: boolean; limit: number; used: number; remaining: number | null } | null>(null);
  const [trialError, setTrialError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [busyAddress, setBusyAddress] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);

  const [loadedDraftKey, setLoadedDraftKey] = useState("");
  const [draftNotice, setDraftNotice] = useState("");
  const [savedNeed, setSavedNeed] = useState<{ id: string; payload: string; uploaded: string[]; expectedFiles: string[] } | null>(null);
  const creationKey = useRef("");
  const activeScope = useRef("");
  const analysisGeneration = useRef(0);
  const [loadedFilesKey, setLoadedFilesKey] = useState("");
  const draftKey = user && companyId ? `porukam:need-draft:${user.id}:${companyId}` : "";

  activeScope.current = draftKey;

  useEffect(() => {
    if (!draftKey) return;
    let cancelled = false;
    const generation = ++analysisGeneration.current;
    setLoadedFilesKey("");
    setAnalyzing(false); setSubmitting(false); setTranscribing(false); setRecording(false);
    void draftFiles(draftKey).then(saved => { if (!cancelled) { setFiles(saved); setLoadedFilesKey(draftKey); } })
      .catch(() => { if (!cancelled) { setLoadedFilesKey(draftKey); setDraftNotice("Не удалось восстановить файлы в браузере. Выберите их повторно."); } });
    setAgentRun(null); setAnswers({}); setFiles([]); setSavedNeed(null); setManualExpanded(false);
    setRequestDescription(""); setRows([newRow("unit", "шт"), newRow()]); setCategory(PRODUCT_CATEGORIES[0]); setSubcategory("");
    setVolumeUnits(""); setBudgetRub(""); setDeadlineDate(""); setDeliveryAddressId("");
    setVisibility("open_anonymized"); setDraftNotice(""); creationKey.current = crypto.randomUUID();
    try {
      const raw = sessionStorage.getItem(draftKey);
      if (raw) {
        const value = JSON.parse(raw);
        if (value.version === 1) {
          setRequestDescription(typeof value.description === "string" ? value.description : "");
          if (PRODUCT_CATEGORIES.includes(value.category)) {
            setCategory(value.category);
            if (PRODUCT_CATEGORY_TREE[value.category].includes(value.subcategory)) setSubcategory(value.subcategory);
          }
          if (Array.isArray(value.rows) && value.rows.length <= 100 && value.rows.every((r: CharacteristicRow) => typeof r.key === "string" && typeof r.value === "string")) setRows(value.rows);
          setManualExpanded(Boolean(value.volume || value.savedNeed));
          setVolumeUnits(String(value.volume ?? "")); setBudgetRub(String(value.budget ?? ""));
          setDeadlineDate(String(value.deadline ?? "")); setDeliveryAddressId(String(value.address ?? ""));
          if (value.visibility === "open_anonymized" || value.visibility === "selected_producers" || value.visibility === "closed") setVisibility(value.visibility);
          if (value.savedNeed?.id && Array.isArray(value.savedNeed.uploaded)) setSavedNeed({ ...value.savedNeed, expectedFiles: value.savedNeed.expectedFiles ?? [] });
          if (typeof value.creationKey === "string") creationKey.current = value.creationKey;
          if (value.answers && typeof value.answers === "object") setAnswers(value.answers);
          if (value.agentRunId) { const token = getToken(); if (token) void agents.getRun(token, value.agentRunId).then(run => { if (!cancelled && analysisGeneration.current === generation) setAgentRun(run); }).catch(() => { if (!cancelled) setDraftNotice("Анализ не удалось восстановить. Ввод сохранён, повторите анализ или заполните карточку вручную."); }); }
          setDraftNotice(value.fileCount ? "Текст и поля восстановлены. Файлы восстанавливаются из локального хранилища браузера." : "Текст и поля восстановлены из этой вкладки.");
        }
      }
    } catch { setDraftNotice("Автосохранение браузера недоступно. Не закрывайте вкладку до сохранения потребности."); }
    setLoadedDraftKey(draftKey);
    return () => { cancelled = true; };
  }, [draftKey]);

  useEffect(() => {
    if (!draftKey || loadedDraftKey !== draftKey) return;
    try { sessionStorage.setItem(draftKey, JSON.stringify({ version: 1, description: requestDescription, category, subcategory, rows, volume: volumeUnits, budget: budgetRub, deadline: deadlineDate, address: deliveryAddressId, visibility, fileCount: files.length, savedNeed, creationKey: creationKey.current, agentRunId: agentRun?.id, answers })); }
    catch { setDraftNotice("Не удалось сохранить поля в браузере. Не закрывайте вкладку до сохранения потребности."); }
  }, [draftKey, loadedDraftKey, requestDescription, category, subcategory, rows, volumeUnits, budgetRub, deadlineDate, deliveryAddressId, visibility, files.length, savedNeed, agentRun, answers]);

  useEffect(() => {
    if (!draftKey || loadedFilesKey !== draftKey) return;
    void draftFiles(draftKey, files).catch(() => { if (activeScope.current === draftKey) setDraftNotice("Файлы не сохранены: недостаточно места в браузере. Не закрывайте вкладку или выберите файлы повторно."); });
  }, [draftKey, loadedFilesKey, files]);

  useEffect(() => () => {
    activeScope.current = "";
    if (recorderRef.current) { recorderRef.current.onstop = null; recorderRef.current.stream.getTracks().forEach(track => track.stop()); }
  }, []);

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
          setError(err instanceof MarketplaceError ? russianMessage(err.message) : "Не удалось загрузить адреса доставки.");
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
      const scope = draftKey;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (activeScope.current !== scope) { stream.getTracks().forEach(track => track.stop()); return; }
      const chunks: BlobPart[] = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop()); setRecording(false); setTranscribing(true);
        const file = new File([new Blob(chunks, { type: recorder.mimeType || "audio/webm" })], "голосовой-запрос.webm", { type: recorder.mimeType || "audio/webm" });
        if (activeScope.current !== scope) return;
        setFiles(current => [...current, file]);
        void agents.transcribe(token, file).then((text) => { if (activeScope.current === scope) { setRequestDescription((current) => [current.trim(), text].filter(Boolean).join(" ")); setAgentRun(null); } }).catch((err: Error) => { if (activeScope.current === scope) setError(`${err.message}. Аудиофайл сохранён в материалах; можно повторить анализ.`); }).finally(() => { if (activeScope.current === scope) setTranscribing(false); });
      };
      recorderRef.current = recorder; recorder.start(); setRecording(true); setError(null);
    } catch { setError("Не удалось получить доступ к микрофону. Разрешите доступ или загрузите аудиофайл."); }
  }

  async function handleAddAddress() {
    const scope = draftKey;
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
      if (activeScope.current !== scope) return;
      setAddresses(updated);
      const added = updated.find((item) => item.address === address.trim());
      setDeliveryAddressId(added?.id ?? updated[0]?.id ?? "");
    } catch (err) {
      setError(err instanceof MarketplaceError ? russianMessage(err.message) : "Не удалось добавить адрес.");
    } finally {
      if (activeScope.current === scope) setBusyAddress(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    const token = getToken();
    if (!token) return;
    setTrial(null); setTrialError(null);
    agents.trial(token).then((value) => { if (!cancelled) { setTrial(value); setTrialError(null); } })
      .catch((err: unknown) => { if (!cancelled) setTrialError(err instanceof Error ? russianMessage(err.message) : "Не удалось проверить пробный доступ."); });
    return () => { cancelled = true; };
  }, [user?.id, analyzing]);

  function validate(): string | null {
    if (agentRun && agentRun.state !== "confirmed_by_user") return "Разрешите конфликты и подтвердите требования анализа или явно выберите ручное заполнение.";
    if (!PRODUCT_CATEGORY_TREE[category]?.includes(subcategory)) return "Выберите подкатегорию товара для проверки требований.";
    if (rows.length < 1 || countUserCharacteristics(rows, category, subcategory) > 25) {
      return "Можно добавить до 25 пользовательских характеристик сверх системных и обязательных.";
    }
    if (rows.some((row) => !row.key.trim() || !row.value.trim())) {
      return "Заполните ключ и значение каждой характеристики.";
    }
    const volume = Number(volumeUnits);
    if (!volumeUnits || !Number.isFinite(volume) || volume <= 0) {
      return "Укажите положительный физический объём или целое количество единиц.";
    }
    if (new Set(rows.map((row) => row.key.trim())).size !== rows.length) return "Названия характеристик не должны повторяться.";
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
    const scope = draftKey;
    setAnalyzing(true);
    setError(null);
    try {
      analysisGeneration.current += 1;
      setAgentRun(null);
      const run = await agents.analyze(
        token,
        requestDescription.trim(),
        files,
        analysisRoute,
        company?.id,
        creationKey.current,
        analysisRoute === "complex_auto" && externalContextAllowed,
      );
      if (activeScope.current !== scope) return;
      setAgentRun(run);
      setAnswers({});
    } catch (err) {
      if (activeScope.current !== scope) return;
      setError(`${err instanceof MarketplaceError ? russianMessage(err.message) : "Не удалось разобрать материалы."} Текст и введённые поля сохранены в этой вкладке. Заполните карточку ниже вручную или повторите анализ.`);
    } finally {
      if (activeScope.current === scope) setAnalyzing(false);
    }
  }

  async function handleClarify() {
    const scope = draftKey;
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
      const clarified = await agents.clarify(token, agentRun.id, parsed, agentRun.revision);
      if (activeScope.current !== scope) return;
      setAgentRun(clarified);
      setAnswers({});
    } catch (err) {
      if (activeScope.current !== scope) return;
      setError(err instanceof MarketplaceError ? russianMessage(err.message) : "Не удалось сохранить уточнения.");
    } finally {
      if (activeScope.current === scope) setAnalyzing(false);
    }
  }

  function openManual() {
    setManualExpanded(true);
    requestAnimationFrame(() => {
      manualRef.current?.scrollIntoView({ block: "start", behavior: "auto" });
      manualRef.current?.querySelector("summary")?.focus();
    });
  }

  async function applyAgentResult() {
    const scope = draftKey;
    const token = getToken();
    if (!token || !agentRun?.result.can_confirm) return;
    setAnalyzing(true);
    setError(null);
    let confirmedRun: AgentRun;
    try {
      confirmedRun = await agents.confirm(token, agentRun.id, agentRun.revision);
      if (activeScope.current !== scope) return;
      setAgentRun(confirmedRun);
    } catch (err) {
      if (activeScope.current !== scope) return;
      setError(err instanceof MarketplaceError ? russianMessage(err.message) : "Не удалось подтвердить требования.");
      setAnalyzing(false);
      return;
    }
    const result = confirmedRun.result;
    const values = new Map(
      result.properties
        .filter((property) => property.value !== null)
        .map((property) => [property.key, property.value] as const),
    );
    const detected = resolveAgentCategory(result.category, String(values.get("product_type") ?? ""));
    if (detected) {
      setCategory(detected.category);
      setSubcategory(detected.subcategory);
    } else {
      // Preserve the buyer's selection; unknown model text is not a decision.
      setDraftNotice("ИИ не определил категорию из каталога. Выберите её самостоятельно; введённые поля сохранены.");
    }
    if (values.has("delivery_city")) {
      const city = String(values.get("delivery_city")).trim().toLocaleLowerCase("ru");
      const matchingAddresses = addresses.filter(address => address.city.trim().toLocaleLowerCase("ru") === city);
      // Only an existing unique address can be suggested; city alone is not a street.
      setDeliveryAddressId(matchingAddresses.length === 1 ? matchingAddresses[0].id : "");
      if (matchingAddresses.length !== 1) setDraftNotice("Проверьте адрес доставки: город распознан, но точный адрес нужно выбрать или добавить.");
    }
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
    openManual();
    setAnalyzing(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const scope = draftKey;
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
      const payload = {
        agent_run_id: agentRun?.state === "confirmed_by_user" ? agentRun.id : undefined,
        agent_run_revision: agentRun?.state === "confirmed_by_user" ? agentRun.revision : undefined,
        quantity_conversion_approved: quantityApproved,
        company_id: company.id,
        category,
        subcategory,
        characteristics,
        volume_units: Number(volumeUnits),
        budget_rub: String(budgetRub),
        deadline_date: deadlineDate,
        delivery_address_id: deliveryAddressId,
        visibility,
      };
      const fingerprint = JSON.stringify(payload);
      if (savedNeed && savedNeed.payload !== fingerprint) {
        setError("Черновик уже создан. Откройте его по ссылке ниже: повторная отправка изменённых полей не должна создать второй заказ.");
        return;
      }
      const omittedHashes = new Set(agentRun?.result.omitted_source_hashes ?? []);
      const acceptedFiles: File[] = [];
      for (const file of files) {
        const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
        const hash = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
        if (!omittedHashes.has(hash)) acceptedFiles.push(file);
      }
      if (activeScope.current !== scope) return;
      const selectedFiles = acceptedFiles.map(file => `${file.name}:${file.size}:${file.lastModified}`);
      if (savedNeed?.expectedFiles.some(signature => !savedNeed.uploaded.includes(signature) && !selectedFiles.includes(signature))) {
        setError("Для продолжения выберите ещё не загруженные файлы повторно. Публикация без исходных вложений остановлена.");
        return;
      }
      const need = savedNeed ? await marketplace.getNeed(token, savedNeed.id) : await marketplace.createNeed(token, { ...payload, request_key: creationKey.current });
      if (activeScope.current !== scope) return;
      let progress = savedNeed ?? { id: need.id, payload: fingerprint, uploaded: [], expectedFiles: selectedFiles };
      setSavedNeed(progress);
      // Retry resumes the same draft. Already uploaded files are not sent twice.
      for (const file of acceptedFiles) {
        const signature = `${file.name}:${file.size}:${file.lastModified}`;
        if (progress.uploaded.includes(signature)) continue;
        await marketplace.uploadNeedFile(token, need.id, file);
        if (activeScope.current !== scope) return;
        progress = { ...progress, uploaded: [...progress.uploaded, signature] };
        setSavedNeed(progress);
      }
      if (company.verification_status === "verified" && need.status === "draft") {
        await marketplace.publishNeed(token, need.id);
      }
      await draftFiles(draftKey, null).catch(() => {});
      try { sessionStorage.removeItem(draftKey); } catch { /* Storage can be disabled. */ }
      if (activeScope.current !== scope) return;
      router.push(`/needs/${need.id}`);
    } catch (err) {
      if (activeScope.current !== scope) return;
      setError(err instanceof MarketplaceError ? russianMessage(err.message) : "Не удалось создать потребность.");
    } finally {
      if (activeScope.current === scope) setSubmitting(false);
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
        Опишите закупку. ИИ заполнит карточку, а вы проверите её перед отправкой.
      </p>

      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <p className="hint">1. Опишите → 2. Проверьте → 3. Отправьте. Ввод сохраняется в этой вкладке.</p>
      {draftNotice && <p className="hint" role="status">{draftNotice}</p>}
      {savedNeed && <p className="alert alert-warning">Черновик уже создан. <Link href={`/needs/${savedNeed.id}`}>Открыть сохранённую потребность</Link>. Повторная отправка продолжит загрузку в этот черновик.</p>}

      <form className="card" onSubmit={handleSubmit}>
        {available.length > 1 ? (
          <div className="field">
            <label htmlFor="company_id">
              Компания<span className="req">*</span>
            </label>
            <select id="company_id" value={companyId} disabled={analyzing || submitting || recording || transcribing} onChange={(event) => { setCompanyId(event.target.value); setAgentRun(null); setAnswers({}); }}>
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
          <h2 id="materials-heading">1. Опишите закупку</h2>
          <p className="hint">
            Опишите задачу обычными словами и приложите материалы. Система покажет источники,
            предположения и противоречия; карточка изменится только после вашего подтверждения.
          </p>
          <div className="field">
            <label htmlFor="request_description">Что требуется купить</label>
            <textarea
              id="request_description"
              disabled={analyzing}
              rows={4}
              value={requestDescription}
              onChange={(event) => { analysisGeneration.current += 1; setRequestDescription(event.target.value); setAgentRun(null); setAnswers({}); }}
              placeholder="Например: нужны 30 рабочих столов из дерева, доставка в Москву..."
            />
            <div className="voice-row"><button type="button" className={recording ? "btn btn-danger btn-sm" : "btn btn-secondary btn-sm"} disabled={transcribing || analyzing || submitting || loadedFilesKey !== draftKey} onClick={() => void toggleRecording()}>{transcribing ? "Распознаём…" : recording ? "Остановить запись" : "🎙 Продиктовать запрос"}</button><span className="hint">Речь распознаётся локально и подставляется в текст. В локальной сети микрофону может потребоваться HTTPS.</span></div>
          </div>
          <div className="field">
            <label htmlFor="need_files">
              Материалы<span className="opt">фото, PDF, текст или голосовое сообщение</span>
            </label>
            <input
              id="need_files"
              disabled={analyzing || submitting || loadedFilesKey !== draftKey}
              type="file"
              multiple
              accept="image/*,application/pdf,audio/*,text/plain,text/markdown"
              onChange={(event) => { analysisGeneration.current += 1; setFiles(Array.from(event.target.files ?? [])); setAgentRun(null); setAnswers({}); }}
            />
            {!!agentRun?.result.omitted_source_hashes?.length && (
              <p className="hint" role="status">По вашему решению непрочитанные материалы не будут приложены к потребности: {agentRun.result.unreadable_sources?.filter(source => agentRun.result.omitted_source_hashes?.includes(source.content_hash)).map(source => source.name).join(", ")}. Остальные материалы сохранятся.</p>
            )}
            {files.length > 0 && (
              <p className="hint mode-hint">
                Восстановленные или выбранные файлы: {files.length} · {files.map((file) => file.name).join(", ")}
              </p>
            )}
          </div>
          <div className="field">
            <label htmlFor="analysis_route">Режим проверки</label>
            <select
              id="analysis_route"
              value={analysisRoute}
              onChange={(event) =>
                { setAnalysisRoute(event.target.value as "local" | "complex_auto"); setExternalContextAllowed(false); }
              }
            >
              <option value="local">Только локальная обработка</option>
              <option value="complex_auto">Внешняя проверка полноты источников</option>
            </select>
          </div>
          {analysisRoute === "complex_auto" && (
            <label className="hint">
              <input type="checkbox" checked={externalContextAllowed} disabled={analyzing}
                onChange={(event) => setExternalContextAllowed(event.target.checked)} />
              Разрешаю передать внешней модели DeepSeek только четыре счётчика: количество источников,
              фактов, фактов с низкой уверенностью и повторяющихся характеристик.
              Файлы, текст, названия компаний и значения характеристик остаются локально.
            </label>
          )}
          <button
            type="button"
            className="btn btn-primary"
            disabled={analyzing || submitting || loadedFilesKey !== draftKey}
            onClick={() => void handleAnalyze()}
          >
            {analyzing ? "Разбираю материалы..." : "Разобрать материалы"}
          </button>

          {trial && <p className="hint" role="status">{trial.enabled ? `Пробные сценарии: ${trial.used} из ${trial.limit} использовано, ${trial.remaining} осталось.` : "Лимит пробных сценариев отключён настройкой платформы."}</p>}
          {trialError && <p className="hint">{trialError}</p>}
          <details className="workflow-details"><summary>Лимит и сохранение данных</summary><p className="hint">Ручное создание бесплатно. Доступны два пробных разбора, если лимит включён. Повтор и уточнение не расходуют новый сценарий. Ввод хранится в этой вкладке отдельно для компании.</p></details>
          <button type="button" className="btn btn-secondary btn-sm" onClick={openManual}>Заполнить вручную</button>

          {agentRun && (
            <div className="agent-result">
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => { analysisGeneration.current += 1; setAgentRun(null); setAnswers({}); openManual(); }}>Продолжить заполнение вручную</button>
              <p className="hint">Версия требований: {agentRun.revision}. Предположения и источники нужно проверить перед переносом в карточку.</p>
              <h3>2. Проверьте результат</h3>
              <p>{agentRun.result.summary}</p>
              <h3>Восстановленные требования</h3>
              {agentRun.result.warnings.map((warning) => (
                <div key={warning} className="alert alert-error">{warning}</div>
              ))}
              <ul className="evidence-list">
                {agentRun.result.properties.map((property) => (
                  <li key={property.key}>
                    <div className="company-row">
                      <strong>{/[а-яё]/i.test(property.label) ? property.label : russianLabel(property.key, "Дополнительная характеристика")}</strong>
                      <span className={`badge evidence-${property.status}`}>
                        {PROPERTY_STATUS_LABELS[property.status] ?? "Требуется проверка"}
                      </span>
                    </div>
                    <div>{property.value === null ? "—" : displayValue(property.value)}</div>
                    {property.sources.length > 0 && (
                      <details>
                        <summary>Откуда взята характеристика?</summary>
                        {property.sources.map((source, index) => (
                          <RequirementSource key={`${agentRun.id}:${source.source_id}:${index}:${source.active}`} runId={agentRun.id} source={source}
                            onInvalidate={() => {
                              const token = getToken(); if (!token || !window.confirm("Удалить источник и отменить связанные подтверждения?")) return;
                              const scope = draftKey;
                              void agents.invalidateSource(token, agentRun.id, source.source_id, agentRun.revision).then(run => { if (activeScope.current === scope) setAgentRun(run); }).catch(reason => { if (activeScope.current === scope) setError(reason instanceof Error ? russianMessage(reason.message) : "Не удалось удалить источник"); });
                            }} />
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
                            <option key={index} value={String(option)}>{displayValue(option)}</option>
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
                <h3>Кандидаты и справочные предложения</h3>
                  <ul className="company-list">
                    {agentRun.result.matches.map((match) => (
                      <li key={match.company_id} className="company-item buyer-candidate">
                        <Link href={`/producers/${match.company_id}`}>{match.company_name}</Link>
                        <span className="match-score">Совпадение: {match.score}/100, не вероятность выполнения</span>
                        <ul className="match-reasons">{match.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                        {match.cautions?.map((note) => <p className="alert alert-error" key={note}>{note}</p>)}
                        {match.details && <details><summary>Возможности и ограничения</summary><CapabilityDescription details={match.details} /></details>}
                        {!!match.catalog?.length && <div className="comparison-scroll"><table className="buyer-comparison"><caption>Данные карточек — без доставки и дополнительных работ</caption><thead><tr><th>Товар</th><th>₽ за единицу</th><th>Минимум единиц</th><th>Срок, дней</th><th>Стоимость товара, ₽</th></tr></thead><tbody>{match.catalog.map((item) => <tr key={item.product_id}>
                          <td><Link href={`/catalog/${item.product_id}`}>{item.name}</Link><p className="hint">{item.note}</p></td><td>{item.unit_price_rub}</td><td>{item.moq_units}</td><td>{item.lead_time_days}</td><td>{item.total_rub ?? "Нужно уточнение"}</td>
                        </tr>)}</tbody></table></div>}
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
                    {call.status === "success" ? "Выполнено" : "Ошибка"}: {russianLabel(call.tool_name, "Обработка материалов")} — {systemText(call.output_summary)}
                  </p>
                ))}
              </details>
            </div>
          )}
        </section>

        <details className="workflow-details" ref={manualRef} open={manualExpanded} onToggle={event => setManualExpanded(event.currentTarget.open)}>
        <summary>3. Карточка запроса — проверьте и отправьте</summary>
        <ValidatedFields>
        <div className="field">
          <label htmlFor="category">
            Категория<span className="req">*</span>
          </label>
          <select id="category" value={category} onChange={(event) => { setCategory(event.target.value); setSubcategory(""); }}>
            {PRODUCT_CATEGORIES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="subcategory">Подкатегория<span className="req">*</span></label>
          <select id="subcategory" required value={subcategory} onChange={(event) => setSubcategory(event.target.value)}>
            <option value="">Выберите вид товара</option>
            {PRODUCT_CATEGORY_TREE[category].map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <p className="hint">Определяет требования к товару. Общая категория сохраняется для подбора мощностей.</p>
        </div>

        <div className="field">
          <label>
            Характеристики<span className="req">*</span>
          </label>
          <CharacteristicSuggestions category={category} subcategory={subcategory} keys={rows.map((row) => row.key)}
            onAdd={(key) => setRows((current) => {
              const empty = current.findIndex(row => !row.key.trim() && !row.value.trim());
              if (empty >= 0) return current.map((row, index) => index === empty ? newRow(key) : row);
              const required = requiredCharacteristicKeys(category, subcategory);
              if (countUserCharacteristics(current, category, subcategory) < 25 || required.has(key.trim().toLowerCase().replaceAll("ё", "е"))) return [...current, newRow(key)];
              return current;
            })} />
          {rows.map((row, index) => (
            <div key={index} className="char-row">
              <input
                type="text"
                placeholder="Характеристика (например, материал)"
                aria-label={`Характеристика ${index + 1}: название`}
                required
                value={fieldName(row.key)}
                onChange={(event) => updateRow(index, { key: canonicalCharacteristicKey(event.target.value) })}
              />
              <input
                type="text"
                placeholder={characteristicField(category, subcategory, row.key)?.label ?? "Значение (например, дерево)"}
                inputMode={characteristicField(category, subcategory, row.key)?.type !== "text" && characteristicField(category, subcategory, row.key) ? "decimal" : "text"}
                aria-label={`Характеристика ${index + 1}: значение`}
                required
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
            disabled={countUserCharacteristics(rows, category, subcategory) >= 25}
            onClick={() => setRows((current) => [...current, newRow()])}
          >
            + Добавить характеристику
          </button>
        </div>

        <div className="field">
          <label htmlFor="volume_units">
            Количество единиц заказа<span className="req">*</span>
          </label>
          <input
            id="volume_units"
            type="number"
            step="any"
            min="0.000001"
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
            min="0.01"
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
            min={new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 10)}
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
          <PhysicalQuantityReview kind="need" values={{ characteristics: Object.fromEntries(rows.filter(row => row.key.trim()).map(row => [row.key.trim(), row.value])), volume_units: volumeUnits }} approved={quantityApproved} onApproval={setQuantityApproved} />
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
        </ValidatedFields>
        </details>
      </form>
    </div>
  );
}
