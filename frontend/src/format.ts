// Даты и сроки для интерфейса. Сервер отдаёт ISO в UTC, показываем в часовом поясе браузера.

const DAY = 86_400_000;

export function shortDate(iso: string): string {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' }).format(new Date(iso));
}

export function dateTime(iso: string): string {
  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(iso));
}

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

export const days = (n: number) => `${n} ${plural(n, 'день', 'дня', 'дней')}`;

/** «вернуть до 5 декабря», «сегодня последний день», «просрочено на 4 дня». Сравнение по календарным дням. */
export function dueText(dueIso: string, now = new Date()): { text: string; overdue: boolean } {
  const due = new Date(dueIso);
  if (due.getTime() < now.getTime()) {
    const d = Math.max(1, Math.floor((now.getTime() - due.getTime()) / DAY));
    return { text: `просрочено на ${days(d)}`, overdue: true };
  }
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const left = Math.round((startOf(due) - startOf(now)) / DAY);
  if (left === 0) return { text: 'сегодня последний день', overdue: false };
  if (left === 1) return { text: `вернуть завтра, ${shortDate(dueIso)}`, overdue: false };
  return { text: `вернуть до ${shortDate(dueIso)}`, overdue: false };
}

export function availability(copies: number, available: number, nextDue: string | null): string {
  if (!copies) return 'нет экземпляров';
  if (available) return copies === 1 ? 'в наличии' : `в наличии ${available} из ${copies}`;
  return nextDue ? `нет в наличии · ближайший возврат ${shortDate(nextDue)}` : 'нет в наличии';
}
