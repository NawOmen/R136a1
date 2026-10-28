"use client";
import { DateInput } from "../components/DateInput";
import { canonicalCharacteristicKey } from "../lib/categoryProfiles";
import { russianMessage } from "../lib/russianMessages";
import { russianLabel, fieldName } from "../lib/presentation";
import { useEffect, useState } from "react";
import CategoryPassportDetails from "../components/CategoryPassportDetails";
import { api, getToken } from "../lib/api";
import { EditableCategoryProfile, EditorRegistry, marketplace, PendingDocument } from "../lib/marketplace";

type Draft = { profile: EditableCategoryProfile; units: string; acceptance: string; reason: string };
export default function EditorPage() {
  const [registry, setRegistry] = useState<EditorRegistry | null>(null);
  const [documents, setDocuments] = useState<PendingDocument[]>([]);
  const [selected, setSelected] = useState("");
  const [documentStatus, setDocumentStatus] = useState<"unverified"|"verified"|"rejected">("unverified");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [preview, setPreview] = useState<EditorRegistry | null>(null);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [reload, setReload] = useState(0);
  const [docInputs, setDocInputs] = useState<Record<string, {category: string; subcategory: string; until: string; confirms: string; note: string}>>({});
  useEffect(() => {
    let cancelled = false; const token = getToken();
    if (!token) { setError("Войдите в аккаунт редактора."); setLoaded(true); return; }
    setDocumentsLoading(true);
    Promise.all([api.me(token), marketplace.getEditorRegistry(token), marketplace.getEditorDocuments(token,documentStatus)])
      .then(([me, data, docs]) => {
        if (cancelled) return;
        if (!me.user.is_category_editor && !me.user.is_marketplace_admin) throw new Error("Требуются полномочия редактора.");
        setRegistry(data); setDocuments(docs); setError(null);
      }).catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? russianMessage(err.message) : "Не удалось загрузить кабинет."); })
      .finally(() => { if (!cancelled) {setLoaded(true); setDocumentsLoading(false);} });
    return () => { cancelled = true; };
  }, [reload,documentStatus]);
  const leaves = registry?.registry.groups.flatMap(group => group.leaves.map(leaf => ({ ...leaf, group: group.label }))) ?? [];
  function select(id: string) {
    const leaf = leaves.find(item => item.id === id); setSelected(id); setPreview(null); setApproved(false);
    if (!leaf) { setDraft(null); return; }
    const profile = structuredClone(leaf.technical_profile);
    setDraft({ profile, units: ((profile.passport.units as {allowed: string[]}).allowed).join(", "),
      acceptance: ((profile.passport.acceptance as {checks: string[]}).checks).join("\n"), reason: "" });
  }
  function change(next: Draft) { setDraft(next); setPreview(null); setApproved(false); }
  function updateCondition(index:number,condition:{field:string;values:string[];required:string[]}|null){
    if(!draft)return;
    const identification=draft.profile.passport.identification as {required_when?:{field:string;values:string[];required:string[]}[]};
    const conditions=identification.required_when ?? [];
    const next=index<0 && condition?[...conditions,condition]:conditions.flatMap((value,i)=>i===index?(condition?[condition]:[]):[value]);
    change({...draft,profile:{...draft.profile,passport:{...draft.profile.passport,identification:{...identification,required_when:next}}}});
  }
  function publication() {
    if (!draft || !registry) throw new Error("Выберите категорию.");
    const profile = structuredClone(draft.profile);
    profile.passport.units = { ...(profile.passport.units as object), allowed: draft.units.split(",").map(item => item.trim()).filter(Boolean) };
    profile.passport.acceptance = { ...(profile.passport.acceptance as object), checks: draft.acceptance.split("\n").map(item => item.trim()).filter(Boolean) };
    profile.passport.identification = { ...(profile.passport.identification as object), required: profile.required_for_product, optional: profile.fields.filter(key => !profile.required_for_product.includes(key)) };
    profile.passport.compatibility = { ...(profile.passport.compatibility as object), hard_fields: profile.required_for_product };
    return { category_id: selected, technical_profile: profile, expected_registry_hash: registry.registry_hash, reason: draft.reason, approved };
  }
  async function review(publish: boolean) {
    const token = getToken(); if (!token || busy) return;
    setBusy(true); setError(null);
    try {
      const next = await marketplace.reviewCategoryRules(token, publication(), publish);
      if (publish) { setRegistry(next); setPreview(null); setApproved(false); setDraft(null); setSelected(""); setNotice("Новая версия правил опубликована."); }
      else setPreview(next);
    } catch (err) { setError(err instanceof Error ? russianMessage(err.message) : "Не удалось сохранить правила."); }
    finally { setBusy(false); }
  }
  function documentValues(doc: PendingDocument) {
    return docInputs[doc.id] ?? {category:doc.scope_category ?? "",subcategory:doc.scope_subcategory ?? "",until:doc.valid_until ?? "",confirms:Object.entries(doc.confirms ?? {}).map(([key,values])=>fieldName(key)+": "+values.join(" | ")).join("\n"),note:doc.verification_note ?? ""};
  }
  async function documentDecision(doc: PendingDocument, verified: boolean) {
    const token = getToken(); if (!token || busy) return;
    const values = documentValues(doc);
    if (!values.note.trim()) { setError("Укажите причину решения по документу."); return; }
    setBusy(true); setError(null);
    try {
      const confirms: Record<string, string[]> = {};
      for (const line of (verified ? values.confirms : "").split("\n").filter(line => line.trim())) {
        const separator = line.indexOf(":");
        if (separator < 1) throw new Error("Подтверждения: название поля и значения через двоеточие; варианты разделяйте символом |.");
        const key = canonicalCharacteristicKey(line.slice(0,separator).trim(), values.category, values.subcategory);
        if (Object.hasOwn(confirms,key)) throw new Error("Подтверждаемые поля не должны повторяться.");
        confirms[key] = line.slice(separator+1).split("|").map(value => value.trim()).filter(Boolean);
      }
      await marketplace.verifyDocument(token, doc.id, { decision: verified ? "verified" : "rejected", scope_category: verified ? values.category : null,
        scope_subcategory: verified ? values.subcategory || null : null, valid_until: verified ? values.until || null : null, confirms: verified ? confirms : null, note: values.note });
      setNotice(verified ? "Применимость документа подтверждена." : "Решение по документу сохранено.");
      setDocuments(await marketplace.getEditorDocuments(token,documentStatus));
    } catch (err) { setError(err instanceof Error ? russianMessage(err.message) : "Не удалось проверить документ."); }
    finally { setBusy(false); }
  }
  async function download(doc: PendingDocument) {
    const token = getToken(); if (!token || busy) return;
    setBusy(true); setError(null);
    try {
      const blob = await marketplace.downloadEditorDocument(token, doc.id); const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = doc.name; link.click(); URL.revokeObjectURL(url);
    } catch (err) { setError(err instanceof Error ? russianMessage(err.message) : "Не удалось получить документ."); }
    finally { setBusy(false); }
  }
  if (!loaded) return <p role="status" className="hint">Загрузка кабинета…</p>;
  return <div><h1 className="page-title">Кабинет редактора</h1>
    {error && <div role="alert" className="alert alert-error">{error}<button type="button" disabled={busy} onClick={() => setReload(value => value+1)}>Обновить</button></div>}
    {notice && <p className="alert alert-success" role="status">{notice}</p>}
    {registry && <>
      <section className="card"><h2>Правила категорий</h2><p className="hint">Публикуется новая версия. Сохранённые спецификации и прежние обязательства не переписываются. Медицинское назначение остаётся заблокированным. Публикация технического профиля не отменяет обязательный допуск и не подтверждает юридическую применимость регламента к товару.</p>
        <label htmlFor="editor-category">Категория</label><select id="editor-category" disabled={busy} value={selected} onChange={event => select(event.target.value)}><option value="">Выберите категорию</option>{leaves.map(leaf => <option key={leaf.id} value={leaf.id} disabled={leaf.admission_state === "unsupported"}>{leaf.group} / {leaf.label}</option>)}</select>
        {draft && <fieldset disabled={busy}>
          <h3>Свойства категории</h3>{Object.entries(registry.registry.characteristic_fields).map(([key,field])=><label key={key}><input type="checkbox" checked={draft.profile.fields.includes(key)} onChange={event=>change({...draft,profile:{...draft.profile,fields:event.target.checked?[...draft.profile.fields,key]:draft.profile.fields.filter(item=>item!==key),required_for_product:event.target.checked?draft.profile.required_for_product:draft.profile.required_for_product.filter(item=>item!==key)}})} />{field.label}</label>)}
          <h3>Обязательные свойства</h3>{draft.profile.fields.map(key => <label key={key}><input type="checkbox" checked={draft.profile.required_for_product.includes(key)} onChange={event => change({ ...draft, profile: { ...draft.profile, required_for_product: event.target.checked ? [...draft.profile.required_for_product,key] : draft.profile.required_for_product.filter(item => item !== key) } })} />{registry.registry.characteristic_fields[key]?.label ?? russianLabel(key)}</label>)}
          <details><summary>Зависимости обязательных свойств</summary>
            {((draft.profile.passport.identification as {required_when?:{field:string;values:string[];required:string[]}[]}).required_when ?? []).map((condition,index)=><fieldset key={index}>
              <label>Если свойство<select value={condition.field} onChange={event=>updateCondition(index,{...condition,field:event.target.value})}>{draft.profile.fields.map(key=><option key={key} value={key}>{registry.registry.characteristic_fields[key]?.label ?? russianLabel(key)}</option>)}</select></label>
              <label>Принимает одно из значений, через |<input value={condition.values.join(" | ")} onChange={event=>updateCondition(index,{...condition,values:event.target.value.split("|").map(value=>value.trim())})} /></label>
              <p>Тогда обязательны:</p>{draft.profile.fields.map(key=><label key={key}><input type="checkbox" checked={condition.required.includes(key)} onChange={event=>updateCondition(index,{...condition,required:event.target.checked?[...condition.required,key]:condition.required.filter(value=>value!==key)})} />{registry.registry.characteristic_fields[key]?.label ?? russianLabel(key)}</label>)}
              <button type="button" onClick={()=>updateCondition(index,null)}>Удалить зависимость</button>
            </fieldset>)}
            <button type="button" onClick={()=>updateCondition(-1,{field:draft.profile.fields[0],values:[],required:[]})}>Добавить зависимость</button>
          </details>
          <label>Единицы заказа, через запятую<input value={draft.units} onChange={event => change({...draft,units:event.target.value})} /></label>
          <label htmlFor="editor-acceptance">Проверки при приёмке, по одной в строке</label><textarea id="editor-acceptance" value={draft.acceptance} onChange={event => change({...draft,acceptance:event.target.value})} />
          <label>Процесс производителя<input value={String((draft.profile.passport.producer as {process:string}).process)} onChange={event=>change({...draft,profile:{...draft.profile,passport:{...draft.profile.passport,producer:{...(draft.profile.passport.producer as object),process:event.target.value}}}})} /></label>
          <label htmlFor="editor-regulations">Правила, применимость которых нужно проверить, по одному в строке</label><textarea id="editor-regulations" value={((draft.profile.passport.documents as {regulatory_candidates:string[]}).regulatory_candidates).join("\n")} onChange={event=>change({...draft,profile:{...draft.profile,passport:{...draft.profile.passport,documents:{...(draft.profile.passport.documents as object),regulatory_candidates:event.target.value.split("\n").map(value=>value.trim()).filter(Boolean)}}}})} />
          <label htmlFor="editor-policy">Порядок обновления правил</label><textarea id="editor-policy" value={String(draft.profile.passport.update_policy)} onChange={event=>change({...draft,profile:{...draft.profile,passport:{...draft.profile.passport,update_policy:event.target.value}}})} />
          <label htmlFor="editor-reason">Основание изменений</label><textarea id="editor-reason" required minLength={5} maxLength={1000} value={draft.reason} onChange={event => change({...draft,reason:event.target.value})} />
          <details><summary>Паспорт и источники</summary><CategoryPassportDetails passport={draft.profile.passport} fields={registry.registry.characteristic_fields} /></details>
          <button type="button" className="btn btn-secondary" onClick={() => void review(false)}>Проверить изменения</button>
          {preview && <><p role="status">Проверка структуры пройдена. Будет опубликована новая версия: {preview.registry.registry_version}.</p><label><input type="checkbox" checked={approved} onChange={event => setApproved(event.target.checked)} /> Изменения и их предметное основание проверены</label><button type="button" className="btn btn-primary" disabled={!approved} onClick={() => void review(true)}>Опубликовать новую версию</button></>}
        </fieldset>}
      </section>
      <section className="card"><h2>Проверка документов</h2><label htmlFor="editor-document-status">Состояние</label><select id="editor-document-status" value={documentStatus} disabled={busy} onChange={event=>{setDocuments([]);setDocumentStatus(event.target.value as typeof documentStatus);}}><option value="unverified">Ожидают проверки</option><option value="verified">Подтверждены — пересмотр и отзыв</option><option value="rejected">Отклонены</option></select>{documentsLoading ? <p role="status">Загружаем документы…</p> : !documents.length && <p className="hint">В выбранном состоянии документов нет.</p>}
        {documents.map(doc => { const values=documentValues(doc);
          const update=(patch:Partial<typeof values>) => setDocInputs(previous => ({...previous,[doc.id]:{...values,...patch}}));
          return <fieldset key={doc.id} disabled={busy}><h3>{doc.name}</h3><p>{doc.company_display_name ?? "Компания"} · {russianLabel(doc.document_type, "Документ")}</p><button type="button" onClick={() => void download(doc)}>Скачать для проверки</button>
            <label htmlFor={`doc-category-${doc.id}`}>Раздел</label><select id={`doc-category-${doc.id}`} value={values.category} onChange={event => update({category:event.target.value,subcategory:""})}><option value="">Выберите раздел</option>{registry.registry.groups.map(group => <option key={group.label}>{group.label}</option>)}</select>
            <label htmlFor={`doc-subcategory-${doc.id}`}>Подкатегория</label><select id={`doc-subcategory-${doc.id}`} value={values.subcategory} onChange={event => update({subcategory:event.target.value})}><option value="">Весь раздел — только при подтверждённой применимости</option>{registry.registry.groups.find(group => group.label===values.category)?.leaves.map(leaf => <option key={leaf.id}>{leaf.label}</option>)}</select>
            <label>Действителен до<DateInput value={values.until} onValueChange={event => update({until:event})} /></label>
            <label htmlFor={`doc-confirms-${doc.id}`}>Подтверждённые характеристики</label><textarea id={`doc-confirms-${doc.id}`} placeholder={"Материал: сталь | латунь\nДлина, мм: 40"} value={values.confirms} onChange={event => update({confirms:event.target.value})} />
            <label htmlFor={`doc-note-${doc.id}`}>Заключение</label><textarea id={`doc-note-${doc.id}`} maxLength={500} value={values.note} onChange={event => update({note:event.target.value})} />
            <button type="button" className="btn btn-primary" onClick={() => void documentDecision(doc,true)}>Применимость проверена — подтвердить</button><button type="button" className="btn btn-secondary" onClick={() => void documentDecision(doc,false)}>{doc.verification_status === "verified" ? "Отозвать с причиной" : "Отклонить с причиной"}</button>
          </fieldset>; })}
      </section>
    </>}
  </div>;
}
