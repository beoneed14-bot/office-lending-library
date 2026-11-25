import { expect, test } from '@playwright/test';
import { loginAs, resetDemo } from './helpers';

test.beforeEach(async ({ page }) => resetDemo(page));

test('с клавиатуры: поиск, карточка, взять, фокус на заголовке, вернуть из «Мои выдачи»', async ({ page }) => {
  await loginAs(page, 'vera');
  await page.getByLabel('Поиск по названию и автору').focus();
  await page.keyboard.type('чистый');
  await expect(page.getByTestId('item')).toHaveCount(1);
  await page.getByRole('link', { name: /^Чистый код/ }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Чистый код', level: 2 })).toBeFocused();
  await page.getByRole('button', { name: 'Взять К-001 на 14 дней' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('notice')).toContainText('«Чистый код» выдан вам');
  await page.getByRole('link', { name: 'Мои выдачи' }).focus();
  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: 'Вернуть «Чистый код» К-001' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('notice')).toHaveText('«Чистый код» возвращён');
});

for (const width of [360, 320]) {
  test(`узкий экран ${width} px: без горизонтальной прокрутки`, async ({ page }) => {
    await page.setViewportSize({ width, height: 740 });
    await loginAs(page, 'curator');
    for (const hash of ['#catalog', '#overdue', '#journal', '#mine']) {
      await page.goto(`/${hash}`);
      await page.waitForTimeout(300);
      expect(await page.evaluate(() => document.documentElement.scrollWidth), hash).toBeLessThanOrEqual(width);
    }
    await page.goto('/#catalog');
    await page.getByRole('link', { name: /^Переходник USB-C → HDMI/ }).click();
    await expect(page.getByRole('heading', { name: 'Переходник USB-C → HDMI', level: 2 })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

test('поля подписаны, кнопки и вкладки не меньше 40 px', async ({ page }) => {
  await loginAs(page, 'curator');
  for (const hash of ['#catalog', '#overdue', '#journal', '#mine']) {
    await page.goto(`/${hash}`);
    await page.waitForTimeout(300);
    const r = await page.evaluate(() => ({
      unlabeled: [...document.querySelectorAll('input, select, textarea')]
        .filter((el) => (el as HTMLElement).offsetParent)
        .filter((el) => !(el as HTMLInputElement).labels?.length && !el.getAttribute('aria-label'))
        .map((el) => el.outerHTML.slice(0, 80)),
      small: [...document.querySelectorAll('button, .tab')]
        .filter((b) => (b as HTMLElement).offsetParent)
        .map((b) => ({ t: b.textContent?.slice(0, 20), h: Math.round(b.getBoundingClientRect().height) }))
        .filter((b) => b.h < 40),
    }));
    expect(r, hash).toEqual({ unlabeled: [], small: [] });
  }
});
