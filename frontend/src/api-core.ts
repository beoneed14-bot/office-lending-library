/** Общий клиент API. Сессия — HttpOnly-cookie на том же адресе, поэтому токен в коде не хранится. */

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: string;
}

export interface DemoUser {
  username: string;
  display_name: string;
  role: string;
  password: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly data: Record<string, unknown> = {},
    readonly fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

const FIELD_MESSAGES: Record<string, string> = {
  string_too_short: 'Поле не заполнено',
  string_too_long: 'Слишком длинно',
  greater_than_equal: 'Слишком маленькое значение',
  less_than_equal: 'Слишком большое значение',
  int_parsing: 'Нужно целое число',
  too_long: 'Слишком много значений',
  missing: 'Поле не заполнено',
};

export async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network', 'Сервер недоступен. Проверьте, что контейнер запущен, и повторите.');
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const d = (data ?? {}) as Record<string, unknown>;
    // Сессия истекла или cookie удалены: приложение показывает вход (кроме самой попытки входа и проверки /me).
    if (res.status === 401 && url !== '/api/auth/login' && url !== '/api/me') window.dispatchEvent(new CustomEvent('auth-lost'));
    if (res.status === 422 && Array.isArray(d.detail)) {
      const fields: Record<string, string> = {};
      for (const e of d.detail as Array<{ loc: Array<string | number>; msg: string; type: string }>) {
        const f = e.loc.filter((x): x is string => typeof x === 'string' && x !== 'body' && x !== 'query').pop() ?? '';
        fields[f] = FIELD_MESSAGES[e.type] ?? e.msg.replace(/^Value error, /, '');
      }
      throw new ApiError(422, 'validation', 'Проверьте выделенные поля', d, fields);
    }
    const field = typeof d.field === 'string' ? d.field : undefined;
    const message = typeof d.message === 'string' ? d.message : `Ошибка ${res.status}`;
    throw new ApiError(res.status, typeof d.code === 'string' ? d.code : 'error', message, d, field ? { [field]: message } : {});
  }
  return data as T;
}

export const authApi = {
  me: () => request<{ user: User }>('GET', '/api/me'),
  login: (username: string, password: string) => request<{ user: User }>('POST', '/api/auth/login', { username, password }),
  logout: () => request<{ ok: boolean }>('POST', '/api/auth/logout'),
  demoUsers: () => request<{ users: DemoUser[] }>('GET', '/api/demo/users'),
};
