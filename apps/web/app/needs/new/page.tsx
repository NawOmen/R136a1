"use client";
import { AddressDialog } from "../../components/AddressDialog";
import { CharacteristicValue } from "../../components/CharacteristicValue";
import { categoryProfile } from "../../lib/categoryProfiles";
import { DateInput } from "../../components/DateInput";

// Создание потребности (POST /needs). Форма покупателя: компания (can_buy),
// категория, характеристики (пары «ключ/значение»), объём, бюджет, срок,
// адрес доставки, видимость, файлы.

import { canonicalCharacteristicKey } from "../../lib/categoryProfiles";
import { russianMessage } from "../../lib/russianMessages";
import { displayValue, fieldName } from "../../lib/presentation";
import { Icon } from "../../components/Icon";
import { FilePicker } from "../../components/FilePicker";
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
} from "../../lib/agents";
import {
  ApiError as MarketplaceError,
  DeliveryAddress,
  marketplace,
  NeedVisibility,
  PRODUCT_CATEGORIES,
  PRODUCT_CATEGORY_TREE,
} from "../../lib/marketplace";
import { useCompanySelector } from "../../lib/useMe";
import CharacteristicSuggestions from "../../components/CharacteristicSuggestions";
import { countUserCharacteristics, resolveAgentCategory } from "../../lib/categoryProfiles";

interface CharacteristicRow {
  key: string;
  value: string;
}

/** Trim only insignificant fractional zeros, keeping the exact decimal value. */
function editableFact(value: FactValue): string {
  if (Array.isArray(value)) return value.map(item => editableFact(item)).join(", ");
  const text = String(value);
  return /^-?\d+\.\d+$/.test(text) ? text.replace(/(\.\d*?[1-9])0+$|\.0+$/, "$1") : text;
}

function newRow(key = "", value = ""): CharacteristicRow {
  return { key, value };
}

export default function NewNeedPage() {
  const manualRef = useRef<HTMLElement>(null);
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
  ]);
  const [volumeUnits, setVolumeUnits] = useState("");
  const [budgetRub, setBudgetRub] = useState("");
  const [deadlineDate, setDeadlineDate] = useState("");
  const [deliveryAddressId, setDeliveryAddressId] = useState("");
  const [visibility, setVisibility] = useState<NeedVisibility>("open_anonymized");
  const [files, setFiles] = useState<File[]>([]);
  const [requestDescription, setRequestDescription] = useState("");
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [addressOpen, setAddressOpen] = useState(false);
  const [characteristicsOpen, setCharacteristicsOpen] = useState(false);
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
  const fileRestoreFailed = useRef(false);
  const draftKey = user && companyId ? `porukam:need-draft:${user.id}:${companyId}` : "";
  const draftReady = Boolean(draftKey && loadedDraftKey === draftKey && loadedFilesKey === draftKey);

  activeScope.current = draftKey;

  useEffect(() => {
    if (!draftKey) return;
    let cancelled = false;
    const generation = ++analysisGeneration.current;
    setLoadedFilesKey(""); fileRestoreFailed.current = false;
    setAnalyzing(false); setSubmitting(false); setTranscribing(false); setRecording(false);
    void draftFiles(draftKey).then(saved => { if (!cancelled) { setFiles(saved); setLoadedFilesKey(draftKey); } })
      .catch(() => { if (!cancelled) { fileRestoreFailed.current = true; setLoadedFilesKey(draftKey); setDraftNotice("Не удалось восстановить файлы в браузере. Выберите их повторно."); } });
    setAgentRun(null); setAnswers({}); setFiles([]); setSavedNeed(null); setManualExpanded(false);
    setRequestDescription(""); setRows([newRow("unit", "шт")]); setCategory(PRODUCT_CATEGORIES[0]); setSubcategory("");
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
          setManualExpanded(value.step ? value.step === "review" : Boolean(value.volume || value.savedNeed));
          setVolumeUnits(String(value.volume ?? "")); setBudgetRub(String(value.budget ?? ""));
          setDeadlineDate(String(value.deadline ?? "")); setDeliveryAddressId(String(value.address ?? ""));
          if (value.visibility === "open_anonymized" || value.visibility === "selected_producers" || value.visibility === "closed") setVisibility(value.visibility);
          if (value.savedNeed?.id && Array.isArray(value.savedNeed.uploaded)) setSavedNeed({ ...value.savedNeed, expectedFiles: value.savedNeed.expectedFiles ?? [] });
          if (typeof value.creationKey === "string") creationKey.current = value.creationKey;
          if (value.answers && typeof value.answers === "object") setAnswers(value.answers);
          if (value.agentRunId) { const token = getToken(); if (token) void agents.getRun(token, value.agentRunId).then(run => { if (!cancelled && analysisGeneration.current === generation) { setAgentRun(run); if (!run.result.can_confirm && run.state !== "confirmed_by_user") setManualExpanded(false); else if (!value.volume && !value.savedNeed && run.result.can_confirm) fillAgentResult(run); } }).catch(() => { if (!cancelled) setDraftNotice("Анализ не удалось восстановить. Ввод сохранён, повторите анализ или заполните карточку вручную."); }); }
          setDraftNotice(value.fileCount ? "Текст и поля восстановлены. Файлы восстанавливаются из локального хранилища браузера." : "Текст и поля восстановлены из этой вкладки.");
        }
      }
    } catch { setDraftNotice("Автосохранение браузера недоступно. Не закрывайте вкладку до сохранения потребности."); }
    setLoadedDraftKey(draftKey);
    return () => { cancelled = true; };
  }, [draftKey]);

  useEffect(() => {
    if (!draftKey || loadedDraftKey !== draftKey) return;
    try { sessionStorage.setItem(draftKey, JSON.stringify({ version: 1, step: manualExpanded ? "review" : "description", description: requestDescription, category, subcategory, rows, volume: volumeUnits, budget: budgetRub, deadline: deadlineDate, address: deliveryAddressId, visibility, fileCount: files.length, savedNeed, creationKey: creationKey.current, agentRunId: agentRun?.id, answers })); }
    catch { setDraftNotice("Не удалось сохранить поля в браузере. Не закрывайте вкладку до сохранения потребности."); }
  }, [draftKey, loadedDraftKey, manualExpanded, requestDescription, category, subcategory, rows, volumeUnits, budgetRub, deadlineDate, deliveryAddressId, visibility, files.length, savedNeed, agentRun, answers]);

  useEffect(() => {
    if (!draftKey || loadedFilesKey !== draftKey || (fileRestoreFailed.current && !files.length)) return;
    fileRestoreFailed.current = false;
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
    let stream: MediaStream | undefined;
    try {
      const scope = draftKey;
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recordingStream = stream;
      if (activeScope.current !== scope) { stream.getTracks().forEach(track => track.stop()); return; }
      const chunks: Blob[] = [];
      const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find(type => MediaRecorder.isTypeSupported(type));
      const recorder = mimeType ? new MediaRecorder(recordingStream, { mimeType }) : new MediaRecorder(recordingStream);
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        recordingStream.getTracks().forEach((track) => track.stop());
        if (recorderRef.current === recorder) recorderRef.current = null;
        if (activeScope.current !== scope) return;
        setRecording(false);
        if (!chunks.length) { setError("Запись пуста. Повторите запись или приложите аудиофайл."); return; }
        const type = recorder.mimeType || chunks[0].type || mimeType || "audio/webm";
        const media = type.split(";")[0].trim().toLowerCase();
        const extension = media === "audio/mp4" || media === "video/mp4" ? "m4a" : media === "audio/ogg" ? "ogg" : "webm";
        const file = new File(chunks, `голосовой-запрос.${extension}`, { type });
        setTranscribing(true);
        setFiles(current => [...current, file]);
        void agents.transcribe(token, file).then((text) => { if (activeScope.current === scope) { setRequestDescription((current) => [current.trim(), text].filter(Boolean).join(" ")); setAgentRun(null); } }).catch((err: Error) => { if (activeScope.current === scope) setError(`${err.message}. Аудиофайл сохранён в материалах; можно повторить анализ.`); }).finally(() => { if (activeScope.current === scope) setTranscribing(false); });
      };
      recorder.onerror = () => {
        recordingStream.getTracks().forEach(track => track.stop());
        if (activeScope.current === scope) { setRecording(false); setError("Не удалось записать звук. Повторите запись или приложите аудиофайл."); }
      };
      recorderRef.current = recorder; recorder.start(); setRecording(true); setError(null);
    } catch { stream?.getTracks().forEach(track => track.stop()); setError("Не удалось получить доступ к микрофону. Разрешите доступ или загрузите аудиофайл."); }
  }

  async function handleAddAddress(value: { address: string; city: string; region: string }): Promise<boolean> {
    const scope = draftKey;
    const token = getToken();
    if (!token || !company) return false;
    setBusyAddress(true); setError(null);
    try {
      const added = await marketplace.createAddress(token, company.id, { ...value, is_default: addresses.length === 0 });
      if (activeScope.current !== scope) return false;
      setAddresses(current => [...current, added]); setDeliveryAddressId(added.id);
      return true;
    } catch (err) {
      if (activeScope.current === scope) setError(err instanceof MarketplaceError ? russianMessage(err.message) : "Не удалось добавить адрес.");
      return false;
    } finally { if (activeScope.current === scope) setBusyAddress(false); }
  }

  function validate(): string | null {
    if (agentRun && agentRun.state !== "confirmed_by_user" && !agentRun.result.can_confirm) return "Разрешите конфликты и подтвердите требования анализа или явно выберите ручное заполнение.";
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
    if (requestDescription.trim().length < 3 && files.length === 0) {
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
        requestDescription.trim().length >= 3 ? requestDescription.trim() : "Подготовьте закупку по приложенным материалам.",
        files,
        "local",
        company?.id,
        creationKey.current,
        false,
      );
      if (activeScope.current !== scope) return;
      setAgentRun(run);
      setAnswers({});
      if (run.result.can_confirm) fillAgentResult(run);
    } catch (err) {
      if (activeScope.current !== scope) return;
      const modelFailed = err instanceof MarketplaceError && (err.status === 503 || /Qwen|JSON/i.test(err.message));
      setError(modelFailed ? "Модель ИИ не работает. Заполните карточку ниже вручную или повторите анализ." : `${err instanceof Error ? russianMessage(err.message) : "Не удалось разобрать материалы."} Заполните карточку ниже вручную или повторите анализ.`);
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
      if (clarified.result.can_confirm) fillAgentResult(clarified);
    } catch (err) {
      if (activeScope.current !== scope) return;
      setError(err instanceof MarketplaceError ? russianMessage(err.message) : "Не удалось сохранить уточнения.");
    } finally {
      if (activeScope.current === scope) setAnalyzing(false);
    }
  }

  function openManual() {
    const opener = document.activeElement;
    setManualExpanded(true);
    requestAnimationFrame(() => {
      // Do not steal focus if the user has already moved into a field.
      if (document.activeElement !== opener && document.activeElement !== document.body) return;
      manualRef.current?.scrollIntoView({ block: "start", behavior: "auto" });
      manualRef.current?.querySelector<HTMLElement>("h2")?.focus();
    });
  }

  function fillAgentResult(run: AgentRun) {
    const result = run.result;
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
    if (values.has("quantity_units")) setVolumeUnits(editableFact(values.get("quantity_units")!));
    if (values.has("budget_rub")) setBudgetRub(editableFact(values.get("budget_rub")!));
    if (values.has("lead_time_days")) {
      const days = Number(values.get("lead_time_days"));
      if (Number.isFinite(days) && days > 0) {
        const deadline = new Date();
        deadline.setDate(deadline.getDate() + days);
        setDeadlineDate(new Date(deadline.getTime() - deadline.getTimezoneOffset() * 60000).toISOString().slice(0, 10));
      }
    }
    const excluded = new Set(["quantity_units", "budget_rub", "lead_time_days", "delivery_city"]);
    const extractedRows = result.properties
      .filter((property) => property.value !== null && !excluded.has(property.key))
      .map((property) =>
        newRow(
          property.key,
          editableFact(property.value!),
        ),
      );
    if (extractedRows.length > 0) setRows(extractedRows.some(row => row.key === "unit") ? extractedRows : [newRow("unit", "шт"), ...extractedRows]);
    setError(null);
    openManual();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!manualExpanded || submitting) return;
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

    const makePayload = (reviewedRun: AgentRun | null) => ({
      agent_run_id: reviewedRun?.id,
      agent_run_revision: reviewedRun?.revision,
      quantity_conversion_approved: quantityApproved,
      company_id: company.id, category, subcategory, characteristics,
      volume_units: Number(volumeUnits), budget_rub: String(budgetRub),
      deadline_date: deadlineDate, delivery_address_id: deliveryAddressId, visibility,
    });
    if (savedNeed && savedNeed.payload !== JSON.stringify(makePayload(agentRun))) {
      setError("Потребность уже сохранена. Откройте её карточку, чтобы внести изменения.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      let reviewedRun = agentRun;
      if (reviewedRun && reviewedRun.state !== "confirmed_by_user") {
        reviewedRun = await agents.confirm(token, reviewedRun.id, reviewedRun.revision);
        if (activeScope.current !== scope) return;
        setAgentRun(reviewedRun);
      }
      const payload = makePayload(reviewedRun);
      const fingerprint = JSON.stringify(payload);
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
            В личный кабинет
          </Link>
        </div>
      </div>
    );
  }

  return <div className="need-create-page need-workflow">
    <header className="need-workflow__header"><div><h1 className="page-title">Создание потребности</h1><p className="subtitle">{manualExpanded ? "Проверьте детали перед отправкой производителям." : "Опишите задачу или приложите файл — ИИ заполнит детали закупки."}</p></div><Link className="btn btn-secondary btn-sm" href="/needs">Мои потребности</Link></header>
    <ol className="need-steps" aria-label="Этапы закупки"><li aria-current={!manualExpanded ? "step" : undefined}><span>1</span>Описание</li><li aria-current={manualExpanded ? "step" : undefined}><span>2</span>Проверка и публикация</li></ol>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {draftNotice && <p className="hint" role="status">{draftNotice.startsWith("Текст и поля восстановлены") ? "Черновик восстановлен" : draftNotice}</p>}
    {savedNeed && <p className="alert alert-warning">Потребность сохранена. <Link href={`/needs/${savedNeed.id}`}>Открыть карточку</Link>. Повторная отправка продолжит загрузку файлов.</p>}
    {!draftReady && <p className="hint" role="status">Загружаем черновик…</p>}
    {addressOpen && <AddressDialog companyId={companyId} key={draftKey} addresses={addresses} busy={busyAddress} onSave={handleAddAddress} onClose={() => setAddressOpen(false)} />}
    <form className="card need-create-form" onSubmit={handleSubmit} aria-busy={analyzing || submitting || !draftReady}>
      <fieldset className="form-fieldset" disabled={!draftReady || submitting}>
        {available.length > 1 ? <div className="field need-company"><label htmlFor="company_id">Компания</label><select id="company_id" value={companyId} disabled={analyzing || recording || transcribing} onChange={event => { setCompanyId(event.target.value); setAgentRun(null); setAnswers({}); }}>{available.map(item => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></div> : <p className="need-company-name"><Icon name="building" size={17} />{company?.display_name}</p>}
        {company?.verification_status !== "verified" && <p className="hint">До проверки компании закупка сохранится черновиком.</p>}
        {!manualExpanded && <section className="need-brief" aria-labelledby="materials-heading">
          <h2 id="materials-heading">Что нужно купить?</h2>
          <div className="field"><label className="visually-hidden" htmlFor="request_description">Что требуется купить</label><textarea id="request_description" disabled={analyzing} maxLength={20000} rows={5} value={requestDescription} onChange={event => { analysisGeneration.current += 1; setRequestDescription(event.target.value); setAgentRun(null); setAnswers({}); }} placeholder="Например: 5 000 бумажных стаканов по 350 мл с нашим логотипом. Доставка в Новосибирск до 15 ноября, бюджет 60 000 ₽." /></div>
          <div className="need-attachments"><FilePicker id="need_files" disabled={analyzing || loadedFilesKey !== draftKey} multiple accept="image/*,application/pdf,audio/*,text/plain,text/markdown" onChange={event => { analysisGeneration.current += 1; setFiles(Array.from(event.target.files ?? [])); setAgentRun(null); setAnswers({}); }} status={files.length ? `Выбрано файлов: ${files.length}` : "Фото, PDF, текст или аудио"} /><button type="button" className={recording ? "btn btn-danger btn-sm" : "btn btn-secondary btn-sm"} disabled={transcribing || analyzing || loadedFilesKey !== draftKey} onClick={() => void toggleRecording()}><Icon name="mic" size={17} />{transcribing ? "Распознаём…" : recording ? "Остановить запись" : "Продиктовать запрос"}</button></div>
          {files.length > 0 && <p className="hint need-file-list">{files.map(file => file.name).join(" · ")}</p>}
          <div className="need-brief__actions"><button type="button" className="btn btn-primary" disabled={analyzing || recording || transcribing || loadedFilesKey !== draftKey} onClick={() => void handleAnalyze()}>{analyzing ? "Заполняем детали…" : "Заполнить с ИИ"}<Icon name="arrow" size={18} /></button><button type="button" className="btn btn-secondary" disabled={analyzing || recording || transcribing} onClick={() => { setAgentRun(null); setAnswers({}); openManual(); }}>Заполнить вручную</button></div>
          {agentRun && !agentRun.result.can_confirm && <section className="need-clarifications" aria-labelledby="clarification-heading"><h3 id="clarification-heading">Уточним детали</h3>
            {Array.from(new Set(agentRun.result.warnings)).map(warning => <p className="hint" key={warning}>{warning}</p>)}
            {agentRun.result.questions.map(question => <div className="field" key={question.key}><label htmlFor={`answer_${question.key}`}>{question.question}</label>{question.options.length ? <select id={`answer_${question.key}`} value={answers[question.key] ?? ""} onChange={event => setAnswers(current => ({ ...current, [question.key]: event.target.value }))}><option value="">Выберите ответ</option>{question.options.map((option,index) => <option key={index} value={String(option)}>{displayValue(option)}</option>)}</select> : <input id={`answer_${question.key}`} value={answers[question.key] ?? ""} onChange={event => setAnswers(current => ({ ...current, [question.key]: event.target.value }))} />}</div>)}
            {agentRun.result.questions.length > 0 && <button type="button" className="btn btn-primary" disabled={analyzing} onClick={() => void handleClarify()}>{analyzing ? "Уточняем…" : "Продолжить"}<Icon name="arrow" size={18} /></button>}
          </section>}
        </section>}
        {!!agentRun?.result.omitted_source_hashes?.length && <p className="hint" role="status">По вашему решению непрочитанные материалы не будут приложены: {agentRun.result.unreadable_sources?.filter(source => agentRun.result.omitted_source_hashes?.includes(source.content_hash)).map(source => source.name).join(", ")}.</p>}
        {manualExpanded && <section ref={manualRef} className="need-review" aria-labelledby="need-review-heading"><div className="company-row"><h2 id="need-review-heading" tabIndex={-1}>Детали закупки</h2><button type="button" className="btn btn-secondary btn-sm" onClick={() => setManualExpanded(false)}>Изменить описание</button></div>
          <div className="need-form-grid"><div className="field"><label htmlFor="category">Категория</label><select id="category" value={category} onChange={event => { setCategory(event.target.value); setSubcategory(""); }}>{PRODUCT_CATEGORIES.map(item => <option key={item}>{item}</option>)}</select></div><div className="field"><label htmlFor="subcategory">Вид товара</label><select id="subcategory" required value={subcategory} onChange={event => { const next = event.target.value; setSubcategory(next); setRows(current => { const required = categoryProfile(category,next)?.required_for_product ?? []; const existing = new Set(current.map(row => row.key)); return [...current,...required.filter(key => !existing.has(key)).map(key => newRow(key))]; }); }}><option value="">Выберите вид товара</option>{PRODUCT_CATEGORY_TREE[category].map(item => <option key={item}>{item}</option>)}</select></div></div>
          <div className="need-properties">{rows.map((row,index) => <div key={index} className="need-property"><div className="field"><label htmlFor={`property-name-${index}`} className="visually-hidden">Название характеристики {index+1}</label><input id={`property-name-${index}`} aria-label={`Характеристика ${index+1}: название`} placeholder="Название характеристики" required value={fieldName(row.key)} onChange={event => updateRow(index,{ key:canonicalCharacteristicKey(event.target.value) })} /></div><CharacteristicValue category={category} subcategory={subcategory} fieldKey={row.key} value={row.value} label={`Характеристика ${index+1}: значение`} onChange={value => updateRow(index,{value})} /><button type="button" className="icon-button" aria-label={`Удалить характеристику ${index+1}`} onClick={() => setRows(current => current.filter((_,i)=>i!==index))}><Icon name="close" size={16} /></button></div>)}
            {characteristicsOpen && <div className="characteristic-picker"><CharacteristicSuggestions category={category} subcategory={subcategory} keys={rows.map(row=>row.key)} compact onAdd={key=>{setRows(current=>[...current,newRow(key)]);setCharacteristicsOpen(false);}} /></div>}
            <button type="button" className="btn btn-secondary btn-sm" disabled={countUserCharacteristics(rows,category,subcategory)>=25} onClick={()=>setCharacteristicsOpen(value=>!value)}>+ Добавить характеристику</button>
          </div>
          <div className="need-form-grid need-commercial"><div className="field"><label htmlFor="volume_units">Количество</label><input id="volume_units" type="number" min="0.01" step="0.01" value={volumeUnits} onChange={event=>setVolumeUnits(event.target.value)} required placeholder="Сколько нужно" /></div><div className="field"><label htmlFor="budget_rub">Бюджет, ₽</label><input id="budget_rub" type="number" min="0.01" step="0.01" value={budgetRub} onChange={event=>setBudgetRub(event.target.value)} required placeholder="Общая сумма" /></div><div className="field"><label htmlFor="deadline_date">Получить до</label><DateInput id="deadline_date" min={new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10)} value={deadlineDate} onValueChange={setDeadlineDate} required /></div><div className="field"><label htmlFor="delivery_address_id">Адрес доставки</label><div className="need-address"><select id="delivery_address_id" required value={deliveryAddressId} onChange={event=>setDeliveryAddressId(event.target.value)}><option value="">Выберите адрес</option>{addresses.map(item=><option key={item.id} value={item.id}>{item.city}, {item.address}</option>)}</select><button type="button" className="btn btn-secondary btn-sm" disabled={busyAddress} onClick={()=>setAddressOpen(true)}>+ Добавить адрес</button></div></div></div>
          {visibility!=="open_anonymized" && <p className="alert alert-warning">У сохранённого запроса ограничена видимость. <button type="button" className="btn btn-secondary btn-sm" onClick={()=>setVisibility("open_anonymized")}>Открыть подбор производителям</button></p>}
          <PhysicalQuantityReview kind="need" values={{characteristics:Object.fromEntries(rows.filter(row=>row.key.trim()).map(row=>[row.key.trim(),row.value])),volume_units:volumeUnits}} approved={quantityApproved} onApproval={setQuantityApproved} compact />
          <footer className="need-review__footer"><p className="hint">Производители увидят требования без реквизитов компании.</p><div className="actions"><button type="submit" className="btn btn-primary" disabled={submitting || !company}>{submitting ? "Отправляем…" : company?.verification_status==="verified" ? "Подтвердить и опубликовать" : "Сохранить черновик"}<Icon name="arrow" size={18} /></button><Link href="/needs" className="btn btn-secondary">Отмена</Link></div></footer>
        </section>}
      </fieldset>
    </form>
  </div>;
}
