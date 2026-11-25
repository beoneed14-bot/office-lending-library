import { expect, test } from '@playwright/test';
import { loginAs } from './helpers';

// Замер раунда 4. Перед запуском: docker compose exec -T app python -m app.synthetic 20000
// (вещи по 2 экземпляра сверх демо, каждая третья выдана, часть просрочена).
test('большой каталог: ответ API, отклик поиска, «Показать ещё»', async ({ page }) => {
  await loginAs(page, 'curator');
  const total = await page.request.get('/api/items?limit=1').then((r) => r.json()).then((j) => j.total as number);
  test.skip(total < 1000, 'нет синтетических данных: python -m app.synthetic 20000');
  const time = async (url: string) => {
    const out: number[] = [];
    for (let i = 0; i < 15; i++) {
      const t0 = Date.now();
      const r = await page.request.get(url);
      expect(r.ok()).toBeTruthy();
      out.push(Date.now() - t0);
    }
    out.sort((a, b) => a - b);
    return { median: out[7], p90: out[13] };
  };
  const all = await time('/api/items?limit=50');
  const search = await time('/api/items?q=%D1%81%D0%B8%D0%BD%D1%82%D0%B5%D1%82%D0%B8%D1%87%D0%B5%D1%81%D0%BA%D0%B8%D0%B9%2001&limit=50');
  const avail = await time('/api/items?category=book&available=true&limit=50');
  const overdue = await time('/api/loans?status=overdue');
  // Отклик интерфейса: ввод в поиск → новый результат на экране (с задержкой ввода 250 мс).
  await page.goto('/#catalog');
  await expect(page.getByTestId('found')).toHaveText(`Найдено: ${total}, показаны 100`);
  // Следующая страница дописывается, фокус переходит на первую новую строку.
  const tm = Date.now();
  await page.getByRole('button', { name: 'Показать ещё 100' }).click();
  await expect(page.getByTestId('found')).toHaveText(`Найдено: ${total}, показаны 200`);
  await expect(page.getByTestId('item').nth(100).getByRole('link')).toBeFocused();
  const more = Date.now() - tm;
  const t0 = Date.now();
  await page.getByLabel('Поиск по названию и автору').fill('синтетический 00042');
  await expect(page.getByTestId('found')).toHaveText('Найдено: 1');
  const ui = Date.now() - t0;
  console.log('PERF204', JSON.stringify({ total, all, search, avail, overdue, ui, more }));
  expect(ui).toBeLessThan(3000);
});
