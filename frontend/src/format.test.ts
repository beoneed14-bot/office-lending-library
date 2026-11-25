import { describe, expect, it } from 'vitest';
import { availability, days, dueText } from './format';

describe('сроки', () => {
  const now = new Date('2026-11-21T10:00:00Z');
  it('просрочка в днях, склонение', () => {
    expect(dueText('2026-11-17T09:00:00Z', now)).toEqual({ text: 'просрочено на 4 дня', overdue: true });
    expect(dueText('2026-11-21T09:59:00Z', now)).toEqual({ text: 'просрочено на 1 день', overdue: true });
    expect([1, 2, 5, 11, 21, 22, 25].map(days)).toEqual(['1 день', '2 дня', '5 дней', '11 дней', '21 день', '22 дня', '25 дней']);
  });
  it('впереди: сегодня, завтра, дата', () => {
    expect(dueText('2026-11-21T20:00:00Z', now).text).toMatch(/^(сегодня последний день|вернуть завтра)/);
    expect(dueText('2026-12-05T12:00:00Z', now).text).toBe('вернуть до 5 декабря');
  });
  it('наличие', () => {
    expect(availability(2, 1, null)).toBe('в наличии 1 из 2');
    expect(availability(1, 1, null)).toBe('в наличии');
    expect(availability(1, 0, '2026-12-05T12:00:00Z')).toBe('нет в наличии · ближайший возврат 5 декабря');
    expect(availability(0, 0, null)).toBe('нет экземпляров');
  });
});
