import { request } from './api-core';

export type Category = 'book' | 'adapter' | 'game';
export const CATEGORY: Record<Category, string> = { book: 'Книги', adapter: 'Переходники', game: 'Игры' };

export interface ItemRow {
  id: number;
  title: string;
  category: Category;
  subtitle: string;
  loan_days: number;
  copies: number;
  available: number;
  next_due: string | null;
}

export interface CopyRow {
  id: number;
  code: string;
  location: string;
  status: 'available' | 'on_loan' | 'retired';
  due_at: string | null;
  overdue: boolean;
  mine: boolean;
  loan_id: number | null;
  borrower: string | null;
}

export interface ItemCard {
  item: { id: number; title: string; category: Category; subtitle: string; description: string; loan_days: number; copies: number; available: number };
  copies: CopyRow[];
}

export interface Loan {
  id: number;
  copy_id: number;
  code: string;
  item_id: number;
  title: string;
  category: Category;
  borrower: string;
  issued_at: string;
  due_at: string;
  returned_at: string | null;
  status: 'active' | 'overdue' | 'returned';
}

export interface EventRow {
  id: number;
  at: string;
  actor: string;
  kind: string;
  text: string;
  title: string | null;
  code: string | null;
  details: string;
}

export const api = {
  items: (p: { q?: string; category?: string; available?: boolean; limit?: number; offset?: number }) => {
    const s = new URLSearchParams();
    if (p.q) s.set('q', p.q);
    if (p.category) s.set('category', p.category);
    if (p.available) s.set('available', 'true');
    s.set('limit', String(p.limit ?? 50));
    if (p.offset) s.set('offset', String(p.offset));
    return request<{ total: number; items: ItemRow[] }>('GET', `/api/items?${s}`);
  },
  item: (id: number) => request<ItemCard>('GET', `/api/items/${id}`),
  createItem: (b: { title: string; category: Category; subtitle: string; description: string; loan_days: number }) => request<ItemCard>('POST', '/api/items', b),
  patchItem: (id: number, b: Partial<{ title: string; subtitle: string; description: string; loan_days: number }>) => request<ItemCard>('PATCH', `/api/items/${id}`, b),
  addCopy: (id: number, code: string, location: string) => request<ItemCard>('POST', `/api/items/${id}/copies`, { code, location }),
  retireCopy: (copyId: number, retired: boolean) => request<ItemCard>('PATCH', `/api/copies/${copyId}`, { retired }),
  borrow: (copyId: number) => request<{ loan: Loan; created: boolean }>('POST', '/api/loans', { copy_id: copyId }),
  giveBack: (loanId: number) => request<{ loan: Loan; changed: boolean }>('POST', `/api/loans/${loanId}/return`),
  loans: (status: 'active' | 'overdue' | 'returned' | 'all', mine = false) => request<{ loans: Loan[] }>('GET', `/api/loans?status=${status}${mine ? '&mine=true' : ''}`),
  events: () => request<{ events: EventRow[] }>('GET', '/api/events?limit=100'),
};
