import { test, expect } from 'playwright/test';
import manifest from '../src/features/vehicle-images/vehiclePhotos.json' with { type: 'json' };

const fixture='/visual-tests/fixture/';
test.beforeEach(async({context})=>{
  await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    // No local backend, remote API, telemetry, or external image fetch is allowed.
    return url.origin==='http://127.0.0.1:14221' ? route.continue() : route.abort('blockedbyclient');
  });
});
for (const width of [320,1440]) {
  test(`cards and accessible details at ${width}px`, async ({page},testInfo)=>{
    await page.setViewportSize({width,height:900});
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    await page.goto(fixture);
    const card=page.locator('[data-catalog-id="2"]');
    await card.scrollIntoViewIfNeeded();
    await expect(card.locator('img')).toHaveJSProperty('complete',true);
    expect(await card.locator('img').evaluate(el=>el.naturalWidth)).toBeGreaterThan(0);
    const selected=await card.locator('img').evaluate(el=>new URL(el.currentSrc).pathname);
    expect(manifest.photos.prisma.variants.map(image=>image.src)).toContain(selected);
    expect(await card.locator('img').evaluate(el=>getComputedStyle(el).objectFit)).toBe('contain');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await card.screenshot({path:testInfo.outputPath(`card-${width}.png`)});
    await page.screenshot({path:testInfo.outputPath(`catalog-${width}.png`)});
    await card.getByRole('button',{name:'Detalhes',exact:true}).click();
    const dialog=page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.vehicle-photo')).toHaveAttribute('data-photo-group','prisma');
    await expect(dialog.getByRole('link',{name:'Fonte',exact:true})).toHaveAttribute('href',manifest.photos.prisma.sourcePage);
    await expect(dialog.getByRole('link',{name:manifest.photos.prisma.license,exact:true})).toHaveAttribute('href',manifest.photos.prisma.licenseUrl);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath(`details-${width}.png`)});
    const close=dialog.getByRole('button',{name:'Fechar',exact:true});
    await expect(close).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(dialog.getByRole('link',{name:manifest.photos.prisma.license,exact:true})).toBeFocused();
    await page.keyboard.press('Tab'); await expect(close).toBeFocused();
    await page.keyboard.press('Escape'); await expect(dialog).not.toBeVisible();
    await expect(card.getByRole('button',{name:'Detalhes',exact:true})).toBeFocused();
    const city=page.locator('[data-catalog-id="14"]');
    await city.scrollIntoViewIfNeeded();
    await expect(city.getByText(manifest.photos.city.correspondenceNote,{exact:true})).toBeVisible();
    await expect(city.locator('img')).toHaveJSProperty('complete',true);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await city.screenshot({path:testInfo.outputPath(`city-illustrative-${width}.png`)});
    expect(errors).toEqual([]);
  });
}
test('all sixty catalog records render their specific admitted photo, never a coverage fallback',async({page})=>{
  await page.goto(fixture);
  expect(manifest.vehicles).toHaveLength(60);
  expect(Object.keys(manifest.photos)).toHaveLength(53);
  for (const row of manifest.vehicles) {
    const card=page.locator(`[data-catalog-id="${row.catalogId}"]`);
    const photo=manifest.photos[row.imageGroup];
    expect(photo,row.label).toBeTruthy();
    await card.scrollIntoViewIfNeeded();
    await expect(card.locator('.vehicle-photo')).toHaveAttribute('data-photo-group',photo?row.imageGroup:'unavailable');
    if (photo) {
      const img=card.locator('img'); await expect(img).toBeVisible();
      await expect(img).toHaveJSProperty('complete',true);
      expect(await img.evaluate(el=>el.naturalWidth)).toBeGreaterThan(0);
      expect(await img.getAttribute('src')).toBe(photo.variants[1].src);
      await expect(img).toHaveAttribute('alt',new RegExp(photo.model.replace(/[.*+?^$()|[\]\\]/g,'\\$&')));
      await expect(card.getByText('Foto ilustrativa do modelo.',{exact:false})).toBeVisible();
    } else {
      await expect(card.locator('img')).toHaveCount(0);
      await expect(card.getByRole('img',{name:`Foto indisponível: ${row.label}`})).toBeVisible();
    }
  }
});
test('HTTP static bytes and decoded dimensions match every admitted derivative',async({page})=>{
  await page.goto(fixture);
  for(const photo of Object.values(manifest.photos)) for(const image of photo.variants) {
    const actual=await page.evaluate(async(src)=>{
      const response=await fetch(src); const bytes=await response.arrayBuffer();
      const bitmap=await createImageBitmap(new Blob([bytes],{type:'image/webp'}));
      const result={status:response.status,bytes:bytes.byteLength,width:bitmap.width,height:bitmap.height,
        sha256:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('')};
      bitmap.close(); return result;
    },image.src);
    expect(actual).toEqual({status:200,bytes:image.bytes,width:image.width,height:image.height,sha256:image.sha256});
  }
});
test('failed image reserves the same frame and changing vehicle restores the correct photo',async({page})=>{
  await page.route('**/assets/vehicle-photos/prisma-*.webp',route=>route.abort('failed'));
  await page.goto(fixture);
  const frame=page.getByTestId('switch-photo');
  await expect(frame.locator('img')).toHaveCount(0);
  const size=await frame.locator('.vehicle-photo__frame').boundingBox();
  await expect(frame.getByRole('img',{name:/Foto indisponível/})).toBeVisible();
  await page.getByRole('button',{name:'Mostrar Cobalt',exact:true}).click();
  await expect(frame.locator('img')).toHaveJSProperty('complete',true);
  expect(await frame.locator('img').evaluate(el=>el.naturalWidth)).toBeGreaterThan(0);
  const restored=await frame.locator('.vehicle-photo__frame').boundingBox();
  expect(restored.width).toBe(size.width); expect(restored.height).toBe(size.height);
  await expect(frame.locator('.vehicle-photo')).toHaveAttribute('data-photo-group','cobalt');
});
for (const width of [320,1440]) test(`real App comparison with isolated local HTTP fixtures at ${width}px`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:900});
  const writes=[];
  await page.route('**/sigra-api/**',async(route)=>{
    if(route.request().method()!=='GET') { writes.push(route.request().method()); return route.abort(); }
    const path=new URL(route.request().url()).pathname;
    const body=path.endsWith('/auth/session')?{user:null}:
      path.endsWith('/recommendations/metadata')?{candidate_source:'operational',profiles:{}}:
      path.endsWith('/vehicles')?[
        {id:2,brand:'Chevrolet',model:'Prisma LT',year:2018,price:54000,fuel_efficiency_km_l:12.9,annual_maintenance_cost:2700,reliability_score:79},
        {id:3,brand:'Chevrolet',model:'Cobalt LTZ',year:2018,price:61000,fuel_efficiency_km_l:11.2,annual_maintenance_cost:3200,reliability_score:78},
      ]:[];
    await route.fulfill({json:body});
  });
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  const menu=page.getByRole('button',{name:'Menu',exact:true});
  if(await menu.isVisible()) await menu.click();
  await page.getByRole('button',{name:'Comparar',exact:true}).click();
  await page.getByRole('checkbox',{name:'Chevrolet Prisma LT'}).check();
  await page.getByRole('checkbox',{name:'Chevrolet Cobalt LTZ'}).check();
  const table=page.getByRole('table');
  await expect(table.locator('.vehicle-photo--comparison')).toHaveCount(2);
  await expect(table.locator('[data-photo-group="prisma"] img')).toHaveJSProperty('complete',true);
  await expect(table.locator('[data-photo-group="cobalt"] img')).toHaveJSProperty('complete',true);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`comparison-${width}.png`)});
  expect(writes).toEqual([]);expect(errors).toEqual([]);
});
