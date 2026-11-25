import { expect, test } from '@playwright/test';
import { copy, loginAs, newUser, openItem, resetDemo } from './helpers';

test.beforeEach(async ({ page }) => resetDemo(page));

test('приёмка ТЗ: два сотрудника одновременно берут один экземпляр — выдан одному; после возврата берёт второй; история обеих', async ({ page, browser }) => {
  const anna = await newUser(browser, 'anna');
  const boris = await newUser(browser, 'boris');
  await openItem(anna, 'Свинтус');
  await openItem(boris, 'Свинтус');
  await Promise.all([anna.getByRole('button', { name: 'Взять И-203 на 7 дней' }).click(), boris.getByRole('button', { name: 'Взять И-203 на 7 дней' }).click()]);
  // Оба ответа пришли: у одного сообщение о выдаче, у другого — конфликт.
  const outcome = async (p: typeof anna) => ((await p.getByTestId('conflict').count()) ? 'conflict' : (await p.getByTestId('notice').textContent())?.includes('выдан вам') ? 'won' : 'pending');
  await expect.poll(async () => [await outcome(anna), await outcome(boris)].sort().join(',')).toBe('conflict,won');
  const [winner, loser] = (await outcome(anna)) === 'won' ? [anna, boris] : [boris, anna];
  await expect(winner.getByTestId('notice')).toContainText('«Свинтус» выдан вам');
  await expect(loser.getByTestId('conflict')).toHaveText('Этот экземпляр уже выдан другому сотруднику. Карточка обновлена.');
  await expect(copy(loser, 'И-203')).toContainText('выдан');
  await expect(copy(loser, 'И-203').getByRole('button', { name: /^Взять/ })).toHaveCount(0);

  // Победитель возвращает через «Мои выдачи», второй забирает.
  await winner.goto('/#mine');
  await winner.getByRole('button', { name: 'Вернуть «Свинтус» И-203' }).click();
  await expect(winner.getByTestId('notice')).toHaveText('«Свинтус» возвращён');
  await openItem(loser, 'Свинтус');
  await loser.getByRole('button', { name: 'Взять И-203 на 7 дней' }).click();
  await expect(loser.getByTestId('notice')).toContainText('«Свинтус» выдан вам');

  // Журнал куратора: выдача, возврат, выдача — история обеих операций.
  await loginAs(page, 'curator');
  await page.goto('/#journal');
  const rows = page.locator('[data-testid="event"]').filter({ hasText: 'И-203' });
  await expect(rows).toHaveCount(3);
  await expect(rows.locator('td:nth-child(3)')).toHaveText(['выдача', 'возврат', 'выдача']);
  await anna.context().close();
  await boris.context().close();
});

test('каталог: поиск по автору без учёта регистра, категория и «только в наличии»', async ({ page }) => {
  await loginAs(page, 'vera');
  await page.getByLabel('Поиск по названию и автору').fill('МАККОННЕЛЛ');
  await expect(page.getByTestId('item')).toHaveCount(1);
  await expect(page.getByTestId('item')).toContainText('Совершенный код');
  await expect(page.getByTestId('item')).toContainText('нет в наличии · ближайший возврат');
  await page.getByLabel('Поиск по названию и автору').fill('');
  await page.getByLabel('Категория').selectOption({ label: 'Игры' });
  await expect(page.getByTestId('found')).toHaveText('Найдено: 4');
  await page.getByLabel('Только в наличии').check();
  await expect(page.getByTestId('found')).toHaveText('Найдено: 3');
  await expect(page.locator('[data-testid="item"][data-title="Каркассон"]')).toHaveCount(0);
  await page.getByLabel('Поиск по названию и автору').fill('нет такого');
  await expect(page.getByText('Ничего не нашлось')).toBeVisible();
});

test('куратор: просрочки, возврат за сотрудника, новая вещь и экземпляр, списание', async ({ page }) => {
  await loginAs(page, 'curator');
  await page.getByRole('link', { name: 'Просрочки' }).click();
  const od = page.getByRole('region', { name: 'Просроченные выдачи' }).or(page.locator('section').filter({ has: page.getByRole('heading', { name: 'Просроченные выдачи' }) }));
  await expect(od.getByTestId('loan')).toHaveCount(1);
  await expect(od.getByTestId('loan')).toContainText('Анна Петрова');
  await expect(od.getByTestId('loan')).toContainText('просрочено на 4 дня');
  await od.getByRole('button', { name: 'Вернуть «Совершенный код» К-003' }).click();
  await expect(page.getByTestId('notice')).toHaveText('«Совершенный код» (К-003) принят от Анна Петрова');
  await expect(page.getByText('Просрочек нет.')).toBeVisible();

  await page.getByRole('link', { name: 'Каталог' }).click();
  await page.getByLabel('Название').fill('Мифический человеко-месяц');
  await page.getByLabel('Автор или характеристики').fill('Фредерик Брукс');
  await page.getByRole('button', { name: 'Добавить', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Мифический человеко-месяц', level: 2 })).toBeVisible();
  await page.getByLabel('Инвентарный номер').fill('к-006');
  await page.getByLabel('Где лежит').fill('Шкаф у кухни');
  await page.getByRole('button', { name: 'Добавить экземпляр' }).click();
  await expect(copy(page, 'К-006')).toContainText('свободен');
  await page.getByLabel('Инвентарный номер').fill('К-006');
  await page.getByRole('button', { name: 'Добавить экземпляр' }).click();
  await expect(page.getByText('Инвентарный номер К-006 уже занят')).toBeVisible();
  await copy(page, 'К-006').getByRole('button', { name: 'Списать' }).click();
  await expect(copy(page, 'К-006')).toContainText('списан');
  await expect(page.getByTestId('availability')).toHaveText('нет экземпляров');
});

test('сотрудник: нет вкладок куратора, своя выдача видна в «Мои выдачи», чужой заёмщик скрыт', async ({ page }) => {
  await loginAs(page, 'boris');
  await expect(page.getByRole('link', { name: 'Просрочки' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Журнал' })).toHaveCount(0);
  await openItem(page, 'Совершенный код');
  await expect(copy(page, 'К-003')).toContainText('выдан · просрочено на 4 дня');
  await expect(copy(page, 'К-003')).not.toContainText('Анна');
  await openItem(page, 'Переходник USB-C → HDMI');
  await expect(copy(page, 'П-101')).toContainText('у вас');
  await page.getByRole('link', { name: 'Мои выдачи' }).click();
  await expect(page.getByTestId('loan')).toHaveCount(1);
  await expect(page.getByTestId('loan')).toContainText('Переходник USB-C → HDMI');
});
