import { expect, type Browser, type Page } from '@playwright/test';

export const PASS: Record<string, string> = { curator: 'curator-demo', anna: 'employee-demo', boris: 'employee-demo', vera: 'employee-demo' };

/** Сброс демо к исходному виду через API (демо-режим, от имени куратора). */
export async function resetDemo(page: Page): Promise<void> {
  const r = await page.request.post('/api/auth/login', { data: { username: 'curator', password: PASS.curator } });
  expect(r.ok()).toBeTruthy();
  expect((await page.request.post('/api/demo/reset')).ok()).toBeTruthy();
  await page.request.post('/api/auth/logout');
}

export async function loginAs(page: Page, username: string): Promise<void> {
  await page.goto('/');
  // Сначала дождаться, что приложение решило, вошли мы или нет: isVisible() не ждёт, и при медленной
  // проверке сессии helper искал поле «Логин» на уже открытом рабочем экране.
  const out = page.getByRole('button', { name: 'Выйти' });
  await expect(out.or(page.getByLabel('Логин'))).toBeVisible();
  if (await out.isVisible()) await out.click();
  await page.getByLabel('Логин').fill(username);
  await page.getByLabel('Пароль').fill(PASS[username]!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByTestId('whoami')).toBeVisible();
}

export async function newUser(browser: Browser, username: string): Promise<Page> {
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  await loginAs(p, username);
  return p;
}

export async function openItem(page: Page, title: string): Promise<void> {
  await page.goto('/#catalog');
  await page.getByLabel('Поиск по названию и автору').fill(title);
  await page.getByRole('link', { name: new RegExp(`^${title}`) }).click();
  await expect(page.getByRole('heading', { name: title, level: 2 })).toBeVisible();
}

export const copy = (page: Page, code: string) => page.locator(`[data-testid="copy"][data-code="${code}"]`);
