import { test, expect, type Page } from "@playwright/test";

const buyerId="10000000-0000-4000-8000-000000000001",sellerId="10000000-0000-4000-8000-000000000002",needId="10000000-0000-4000-8000-000000000003",requestId="10000000-0000-4000-8000-000000000004",fileId="10000000-0000-4000-8000-000000000005";
const sellerName="ООО «Синтетическая упаковка»";
const buyer={id:buyerId,display_name:"ООО «Синтетический покупатель»",full_name:"ООО «Синтетический покупатель»",country:"RU",legal_form:"ООО",verification_status:"verified",membership:{can_buy:true,can_sell:false,is_admin:true}};
const seller={...buyer,id:sellerId,display_name:sellerName,full_name:sellerName,membership:{can_buy:false,can_sell:true,is_admin:true}};
const need={id:needId,company_id:buyerId,category:"Упаковка и тара",subcategory:"Бумажные стаканы",status:"open_for_offers",visibility:"open_anonymized",revision:1,volume_units:100,budget_rub:"5000.00",deadline_date:"2026-11-20",valid_until:"2026-11-19",delivery_address_id:null,characteristics:{unit:"шт",material:"бумага"},files:[],requirements_evidence:null};
const draftText=`Здравствуйте, ${sellerName}! Просим КП на 100 бумажных стаканов. Укажите цену в рублях, НДС и срок поставки.`;

async function prepare(page: Page, options: {empty?:boolean; draftFailure?:boolean; extractionFailure?:boolean; sendFailure?:boolean}={}) {
  let row={id:requestId,need_id:needId,need_revision:1,buyer_company_id:buyerId,seller_company_id:sellerId,buyer_name:buyer.display_name,seller_name:sellerName,specification:{category:need.category,subcategory:need.subcategory,characteristics:need.characteristics,quantity:100,unit:"шт",deadline_date:need.deadline_date},status:"sent",revision:1,quoted_price_rub:null as string|null,price_basis:"unknown",lead_time_days:null as number|null,delivery_date:null as string|null,note:"",sent_at:"2026-10-26T01:00:00Z",updated_at:"2026-10-26T01:00:00Z"};
  let rows=options.empty?[]:[row]; const messages: unknown[]=[]; let files: unknown[]=[]; let sendAttempts=0;
  const updates: Record<string,unknown>[]=[];const sends: Record<string,unknown>[]=[];
  page.on("pageerror",error=>{throw error;});
  await page.addInitScript(()=>localStorage.setItem("token","synthetic-supplier-ui"));
  await page.route("**/api/**",route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname;
    let json:unknown=[];
    if(path.endsWith("/auth/me"))json={user:{id:"synthetic-user",first_name:"Тест",last_name:"Покупатель",account_status:"active"},companies:[buyer,seller]};
    else if(path.endsWith("/next-step"))json={title:"Потребности",description:"",href:"/needs"};
    else if(path.endsWith(`/needs/${needId}`))json=need;
    else if(path.endsWith("/needs/mine"))json=[need];
    else if(path.endsWith("/suppliers"))json=[{company_id:sellerId,company_name:sellerName,specialization:[need.category],relevant:true,products:["Бумажный стакан"]}];
    else if(path.endsWith("/specification.csv"))return route.fulfill({contentType:"text/csv",headers:{"Content-Disposition":"attachment; filename=spec.csv"},body:"Категория;Количество\nУпаковка;100"});
    else if(path.endsWith("/supplier-requests")&&req.method()==="POST"){row={...row,status:"draft",sent_at:null as unknown as string};rows=[row];json=row;}
    else if(path.endsWith("/supplier-requests"))json=rows;
    else if(path.endsWith(`/supplier-requests/${requestId}`)&&req.method()==="PATCH"){
      const value=req.postDataJSON();updates.push(value);row={...row,...value,revision:row.revision+1};rows=[row];json=row;
    }
    else if(path.endsWith("/messages")&&req.method()==="POST"){
      const value=req.postDataJSON();sends.push(value);sendAttempts++;
      if(options.sendFailure&&sendAttempts===1)return route.fulfill({status:503,json:{detail:"Отправка временно недоступна. Повторите попытку."}});
      const message={id:`synthetic-message-${sendAttempts}`,author_company_id:value.company_id,message:value.message,created_at:"2026-10-26T02:00:00Z"};messages.push(message);row={...row,status:value.company_id===sellerId?"replied":"sent",revision:row.revision+1};rows=[row];json=message;
    }
    else if(path.endsWith("/messages"))json=messages;
    else if(path.endsWith("/files")&&req.method()==="POST"){const file={id:fileId,file_name:"Ответ поставщика.txt",content_type:"text/plain",content_hash:"synthetic-hash",created_at:"2026-10-26T02:00:00Z"};files=[file];json=file;}
    else if(path.endsWith("/files"))json=files;
    else if(path.endsWith("/draft")){
      if(options.draftFailure)return route.fulfill({status:503,json:{detail:"Локальный ИИ недоступен. Напишите вручную или повторите попытку."}});
      json={text:draftText,request_revision:row.revision,warnings:["ИИ подготовил ответ без коммерческих обязательств."]};
    }
    else if(path.endsWith("/extract-reply")){
      if(options.extractionFailure)return route.fulfill({status:503,json:{detail:"Файл сохранён. Разбор недоступен, укажите цену и срок вручную."}});
      json={price_rub:"1234.567891231",price_basis:"total",price_evidence:"Сумма запроса: 1234,567891231 руб.",lead_time_days:5,lead_time_evidence:"Срок 5 дней",delivery_date:null,date_evidence:"",request_revision:row.revision,file_id:fileId,content_hash:"synthetic-hash",warnings:["Проверьте значения по исходному файлу."]};
    }
    return route.fulfill({json});
  });
  return {updates,sends};
}

async function openCard(page:Page){await page.goto(`/needs/${needId}`);await page.locator('.supplier-card__open').first().click();return page.getByRole('region',{name:'Работа с поставщиком'});}

test('supplier RFQ is addressed, editable and never sent by generation',async({page})=>{
  const state=await prepare(page,{empty:true});await page.goto(`/needs/${needId}`);
  await page.getByLabel('Получатель запроса').selectOption(sellerId);await page.getByRole('button',{name:'Подготовить запрос',exact:true}).click();
  const workspace=page.getByRole('region',{name:'Работа с поставщиком'});
  await workspace.getByRole('button',{name:'Подготовить запрос с ИИ'}).click();
  const input=workspace.getByLabel('Запрос коммерческого предложения');await expect(input).toHaveValue(draftText);expect(state.sends).toHaveLength(0);
  await input.fill(draftText+' Уточните упаковку.');await workspace.getByRole('button',{name:'Отправить поставщику',exact:true}).click();
  await expect(workspace.getByText('Сообщение отправлено.',{exact:true})).toBeVisible();expect(state.sends).toHaveLength(1);expect(state.sends[0].human_approved).toBe(true);
});

test('board can be moved with keyboard without creating a deal',async({page})=>{
  const state=await prepare(page);await page.goto(`/needs/${needId}`);
  await page.getByLabel(`Этап: ${sellerName}`).selectOption('selected');
  await expect(page.getByRole('region',{name:'Выбрано',exact:true}).locator('.supplier-card')).toHaveCount(1);
  expect(state.updates.at(-1)?.status).toBe('selected');expect(state.updates.at(-1)?.expected_revision).toBe(1);
});

test('supplier reply extraction fills review fields and keeps exact price until confirmed',async({page})=>{
  const state=await prepare(page);const workspace=await openCard(page);
  await workspace.getByLabel('Файл ответа поставщика').setInputFiles({name:'Ответ.txt',mimeType:'text/plain',buffer:Buffer.from('Сумма запроса: 1234,567891231 руб. Срок 5 дней.')});
  const price=workspace.getByLabel('Цена из ответа, ₽');await expect(price).toHaveValue('1234.567891231');expect(state.updates).toHaveLength(0);
  await expect(workspace.getByText('Сумма запроса: 1234,567891231 руб.',{exact:true})).toBeVisible();
  await workspace.getByRole('button',{name:'Проверено, сохранить ответ'}).click();await expect(workspace.getByText('Ответ сохранён. Условия сделки не изменены.',{exact:true})).toBeVisible();
  expect(state.updates.at(-1)?.quoted_price_rub).toBe('1234.567891231');expect(state.updates.at(-1)?.price_basis).toBe('total');expect(state.updates.at(-1)?.status).toBe('replied');
});

test('AI failure keeps message and failed send retries with the same key',async({page})=>{
  const state=await prepare(page,{draftFailure:true,sendFailure:true});const workspace=await openCard(page);const input=workspace.getByLabel('Ваше сообщение');
  await input.fill('Уточните, пожалуйста, срок поставки.');await workspace.getByRole('button',{name:'Помочь с ответом'}).click();
  await expect(workspace.getByRole('alert')).toContainText('Локальный ИИ недоступен');await expect(input).toHaveValue('Уточните, пожалуйста, срок поставки.');
  await workspace.getByRole('button',{name:'Отправить поставщику',exact:true}).click();await expect(workspace.getByRole('alert')).toContainText('Отправка временно недоступна');await expect(input).toHaveValue('Уточните, пожалуйста, срок поставки.');
  await workspace.getByRole('button',{name:'Отправить поставщику',exact:true}).click();await expect(input).toHaveValue('');expect(state.sends).toHaveLength(2);expect(state.sends[0].request_key).toBe(state.sends[1].request_key);
});

test('failed extraction preserves uploaded file and manual quote entry',async({page})=>{
  await prepare(page,{extractionFailure:true});const workspace=await openCard(page);
  await workspace.getByLabel('Файл ответа поставщика').setInputFiles({name:'Ответ.txt',mimeType:'text/plain',buffer:Buffer.from('Тестовый ответ')});
  await expect(workspace.getByRole('alert')).toContainText('Файл сохранён');await expect(workspace.getByRole('button',{name:'Ответ поставщика.txt',exact:true})).toBeVisible();
  await workspace.getByLabel('Цена из ответа, ₽').fill('38,25');await expect(workspace.getByRole('button',{name:'Проверено, сохранить ответ'})).toBeEnabled();
});

test('seller can draft and send a reply and cannot see private buyer quote fields',async({page})=>{
  const state=await prepare(page);await page.goto('/seller/inquiries');const workspace=page.getByRole('region',{name:'Работа с поставщиком'});
  await workspace.getByRole('button',{name:'Помочь с ответом'}).click();await expect(workspace.getByLabel('Ваше сообщение')).toHaveValue(draftText);
  await expect(workspace.getByText('ИИ подготовил ответ без коммерческих обязательств.',{exact:true})).toBeVisible();
  await workspace.getByRole('button',{name:'Отправить покупателю',exact:true}).click();await expect(workspace.getByText('Сообщение отправлено.',{exact:true})).toBeVisible();expect(state.sends[0].company_id).toBe(sellerId);
  await expect(workspace.getByLabel('Цена из ответа, ₽')).toHaveCount(0);await expect(workspace.getByLabel('Файл ответа поставщика')).toHaveCount(0);
});

test('specification download and responsive light/dark board remain usable',async({page},testInfo)=>{
  await prepare(page);const workspace=await openCard(page);
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'Скачать спецификацию',exact:true}).click();expect((await download).suggestedFilename()).toContain('specification');
  for(const theme of ['light','dark']){
    await page.evaluate(t=>{document.documentElement.dataset.theme=t;},theme);
    await workspace.scrollIntoViewIfNeeded();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await expect(workspace.getByLabel('Ваше сообщение')).toBeVisible();
    if(['desktop-chromium','iphone-webkit'].includes(testInfo.project.name)){
      await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
      await workspace.screenshot({path:`output/procurement-qa/${testInfo.project.name}-${theme}.png`,style:".site-header,.skip-link{visibility:hidden!important}"});
      await page.locator(".supplier-board").screenshot({path:`output/procurement-qa/${testInfo.project.name}-${theme}-board.png`,style:".site-header,.skip-link{visibility:hidden!important}"});
    }
  }
});

test('desktop board drag moves a supplier card smoothly',async({page,isMobile})=>{
  test.skip(isMobile,'На touch используется доступный выбор этапа');
  await prepare(page);await page.goto(`/needs/${needId}`);
  await page.locator('.supplier-card').dragTo(page.getByRole('region',{name:'Получен ответ',exact:true}));
  await expect(page.getByRole('region',{name:'Получен ответ',exact:true}).locator('.supplier-card')).toHaveCount(1);
});


test('matched need keeps the next step to orders after reload', async ({page}, testInfo) => {
  await prepare(page);
  await page.route(url => url.pathname.startsWith("/api/") && url.pathname.endsWith(`/needs/${needId}`), route => route.fulfill({json:{...need,status:'matched'}}));
  await page.goto(`/needs/${needId}`);
  await expect(page.getByRole('heading',{name:'Предложение выбрано',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Перейти к заказам',exact:true})).toHaveAttribute('href','/deals');
  // Complete initial navigation/prefetch before testing persistence across reload.
  await page.waitForLoadState('networkidle');
  if (['desktop-chromium','iphone-webkit'].includes(testInfo.project.name)) await page.locator('section.card').filter({has:page.getByRole('heading',{name:'Предложение выбрано',exact:true})}).screenshot({path:`output/procurement-qa/final-next-step-${testInfo.project.name}.png`,style:'.site-header,.skip-link{visibility:hidden!important}'});
  await page.reload();
  await expect(page.getByRole('link',{name:'Перейти к заказам',exact:true})).toBeVisible();
});
