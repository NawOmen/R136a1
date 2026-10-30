import { expect, test, type Page } from "@playwright/test";

const id="20000000-0000-4000-8000-000000000001";
const companyId="20000000-0000-4000-8000-000000000002";
const need={id,company_id:companyId,category:"Строительство",subcategory:"Крепёж",status:"open_for_offers",visibility:"open_anonymized",revision:1,volume_units:20000,budget_rub:"100000",deadline_date:"2026-11-20",valid_until:"2026-11-19",characteristics:{unit:"шт"},delivery_address_id:null};

async function prepare(page: Page) {
  const writes: unknown[]=[];
  page.on("pageerror",error=>{throw error;});
  await page.addInitScript(()=>localStorage.setItem("token","synthetic-needs-controls"));
  await page.route("**/api/**",route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.endsWith("/auth/me"))return route.fulfill({json:{user:{id:"20000000-0000-4000-8000-000000000003",first_name:"Покупатель",last_name:"Тестовый",email:"buyer@example.test",account_status:"active"},companies:[{id:companyId,display_name:"Синтетическая компания",full_name:"Синтетическая компания",country:"RU",legal_form:"ООО",verification_status:"verified",membership:{can_buy:true,can_sell:false,is_admin:true}}]}});
    if(path.endsWith("/needs/mine"))return route.fulfill({json:[need]});
    if(path.endsWith("/edit-preview"))return route.fulfill({json:{editable:true,requires_confirmation:true,impact_hash:"synthetic-impact",changes:{deadline_date:{before:"2026-11-20",after:"2026-11-21"}}}});
    if(path.endsWith(`/needs/${id}`)&&route.request().method()==="PUT"){
      writes.push(route.request().postDataJSON());return route.fulfill({json:{...need,visibility:"closed",revision:2}});
    }
    return route.fulfill({json:[]});
  });
  await page.goto("/needs");
  return writes;
}

test("hiding a need requires human approval after preview and cancellation never writes",async({page})=>{
  const writes=await prepare(page);
  page.once("dialog",dialog=>dialog.dismiss());
  await page.getByRole("button",{name:"Скрыть из публикации",exact:true}).click();
  await expect(page.getByRole("button",{name:"Скрыть из публикации",exact:true})).toBeEnabled();
  expect(writes).toHaveLength(0);
  page.once("dialog",dialog=>dialog.accept());
  await page.getByRole("button",{name:"Скрыть из публикации",exact:true}).click();
  await expect(page.getByRole("button",{name:"Вернуть в публикацию",exact:true})).toBeVisible();
  expect(writes).toEqual([expect.objectContaining({impact_hash:"synthetic-impact",expected_revision:1,visibility:"closed"})]);
});

test("edit preview shows readable Russian dates",async({page})=>{
  await prepare(page);
  await page.getByRole("button",{name:"Изменить",exact:true}).click();
  await page.getByLabel("Получить до",{exact:true}).fill("21.11.26");
  await page.getByRole("button",{name:"Проверить изменения",exact:true}).click();
  await expect(page.getByRole("dialog")).toContainText("было — 20.11.26; станет — 21.11.26");
});


test('an error inside the edit dialog receives focus even when the page already has an error',async({page})=>{
 await prepare(page);let calls=0;
 await page.route('**/edit-preview',route=>route.fulfill({status:409,json:{detail:++calls===1?'Публикацию изменить нельзя':'Количество требует уточнения'}}));
 await page.getByRole('button',{name:'Скрыть из публикации',exact:true}).click();
 await expect(page.locator('main > .page-surface .alert-error').first()).toContainText('Публикацию изменить нельзя');
 await page.getByRole('button',{name:'Изменить',exact:true}).click();
 const dialog=page.getByRole('dialog');await dialog.getByLabel('Количество',{exact:true}).fill('30000');
 await dialog.getByRole('button',{name:'Проверить изменения',exact:true}).click();
 const error=dialog.getByRole('alert');await expect(error).toContainText('Количество требует уточнения');
 await expect(error).toBeFocused();
});
