import { expect, test } from '@playwright/test';
import { loginAs, newUser, openItem, resetDemo } from './helpers';

test.beforeEach(async ({ page }) => resetDemo(page));

test('повторный возврат из устаревшей вкладки не дублирует запись в журнале', async ({ page, browser }) => {
  const a1 = await newUser(browser, 'boris');
  const a2 = await a1.context().newPage();
  await a1.goto('/#mine');
  await a2.goto('/#mine');
  await a1.getByRole('button', { name: /^Вернуть «Переходник USB-C → HDMI»/ }).click();
  await expect(a1.getByTestId('notice')).toHaveText('«Переходник USB-C → HDMI» возвращён');
  await a2.getByRole('button', { name: /^Вернуть «Переходник USB-C → HDMI»/ }).click();
  await expect(a2.getByTestId('notice')).toHaveText('Эта вещь уже была возвращена');
  await loginAs(page, 'curator');
  await page.goto('/#journal');
  await expect(page.locator('[data-testid="event"][data-kind="return"]')).toHaveCount(1);
  await a1.context().close();
});

test('сессия потеряна: экран входа с объяснением, после входа работа продолжается', async ({ page, context }) => {
  await loginAs(page, 'vera');
  await context.clearCookies();
  await openItem(page, 'Кодовые имена').catch(() => undefined);
  await expect(page.getByText('Сессия закончилась, войдите снова')).toBeVisible();
  await page.getByLabel('Логин').fill('vera');
  await page.getByLabel('Пароль').fill('employee-demo');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByTestId('whoami')).toContainText('Вера Ким');
});

test('сервер недоступен: понятное сообщение вместо пустого экрана', async ({ page }) => {
  await loginAs(page, 'anna');
  await page.route('**/api/items?*', (r) => r.abort());
  await page.getByLabel('Поиск по названию и автору').fill('код');
  await expect(page.getByRole('alert')).toHaveText('Сервер недоступен. Проверьте, что контейнер запущен, и повторите.');
});
