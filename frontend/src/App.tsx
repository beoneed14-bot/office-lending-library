import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, authApi, type User } from './api-core';
import { api, CATEGORY, type Category, type EventRow, type ItemCard, type ItemRow, type Loan } from './api';
import { availability, dateTime, days, dueText, shortDate } from './format';
import { Login } from './ui/Login';

type Route = { view: 'catalog' | 'mine' | 'overdue' | 'journal'; item: number | null };
const parse = (): Route => {
  const h = location.hash.slice(1);
  const m = /^item\/(\d+)$/.exec(h);
  if (m) return { view: 'catalog', item: Number(m[1]) };
  return { view: h === 'mine' || h === 'overdue' || h === 'journal' ? h : 'catalog', item: null };
};
const roleLabel = (r: string) => (r === 'curator' ? 'куратор' : 'сотрудник');

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [loginNotice, setLoginNotice] = useState<string | null>(null);
  const [route, setRoute] = useState<Route>(parse);

  useEffect(() => {
    authApi
      .me()
      .then((r) => setUser(r.user))
      .catch(() => undefined)
      .finally(() => setLoading(false));
    const lost = () => {
      setUser(null);
      setLoginNotice('Сессия закончилась, войдите снова');
    };
    const hash = () => setRoute(parse());
    window.addEventListener('auth-lost', lost);
    window.addEventListener('hashchange', hash);
    return () => {
      window.removeEventListener('auth-lost', lost);
      window.removeEventListener('hashchange', hash);
    };
  }, []);
  useEffect(() => {
    if (!notice) return;
    const t = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(t);
  }, [notice]);

  if (loading) return <p className="muted">Загрузка…</p>;
  if (!user) return <Login onLogin={(u) => (setUser(u), setLoginNotice(null))} notice={loginNotice} roleLabel={roleLabel} />;
  const curator = user.role === 'curator';
  const tabs: [Route['view'], string][] = [
    ['catalog', 'Каталог'],
    ['mine', 'Мои выдачи'],
    ...(curator ? ([['overdue', 'Просрочки'], ['journal', 'Журнал']] as [Route['view'], string][]) : []),
  ];

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="kicker">Библиотека вещей для офиса</p>
          <h1>{route.item ? 'Карточка вещи' : tabs.find((t) => t[0] === route.view)?.[1]}</h1>
        </div>
        <div className="whoami">
          <span data-testid="whoami">
            {user.display_name} · {roleLabel(user.role)}
          </span>
          <button type="button" className="btn btn--ghost" onClick={() => void authApi.logout().finally(() => setUser(null))}>
            Выйти
          </button>
        </div>
      </header>
      <nav className="tabs" aria-label="Разделы">
        {tabs.map(([v, label]) => (
          <a key={v} href={`#${v}`} className={`tab ${route.view === v && !route.item ? 'tab--on' : ''}`} aria-current={route.view === v && !route.item ? 'page' : undefined}>
            {label}
          </a>
        ))}
      </nav>
      <p className="notice-line" role="status" aria-live="polite" data-testid="notice">
        {notice ?? ''}
      </p>
      {route.item ? (
        <ItemView key={route.item} id={route.item} curator={curator} setNotice={setNotice} />
      ) : route.view === 'catalog' ? (
        <Catalog curator={curator} setNotice={setNotice} />
      ) : route.view === 'mine' ? (
        <MyLoans setNotice={setNotice} />
      ) : route.view === 'overdue' ? (
        <Overdue setNotice={setNotice} />
      ) : (
        <Journal />
      )}
    </div>
  );
}

function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: unknown) => alive && setError(e instanceof ApiError ? e.message : 'Не удалось загрузить'));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, reload: useCallback(() => setN((x) => x + 1), []) };
}

/* ---------------- Каталог ---------------- */

const PAGE = 100;

function Catalog({ curator, setNotice }: { curator: boolean; setNotice: (t: string) => void }) {
  const [q, setQ] = useState('');
  const [cat, setCat] = useState<Category | ''>('');
  const [avail, setAvail] = useState(false);
  const [dq, setDq] = useState('');
  useEffect(() => {
    const t = window.setTimeout(() => setDq(q.trim()), 250);
    return () => window.clearTimeout(t);
  }, [q]);
  const { data, error, reload } = useLoad(() => api.items({ q: dq, category: cat || undefined, available: avail, limit: PAGE }), [dq, cat, avail]);
  // «Показать ещё»: следующие страницы дописываются к первой. Новый запрос фильтров сбрасывает их.
  const [more, setMore] = useState<ItemRow[]>([]);
  const [moreBusy, setMoreBusy] = useState(false);
  const [moreErr, setMoreErr] = useState<string | null>(null);
  const focusFrom = useRef<number | null>(null);
  useEffect(() => {
    setMore([]);
    setMoreErr(null);
  }, [data]);
  const shown = data ? [...data.items, ...more] : [];
  useEffect(() => {
    const i = focusFrom.current;
    if (i === null) return;
    focusFrom.current = null;
    const links = document.querySelectorAll<HTMLAnchorElement>('[data-testid="item"] a');
    links[i]?.focus();
  }, [more]);
  async function loadMore() {
    if (!data || moreBusy) return;
    setMoreBusy(true);
    setMoreErr(null);
    try {
      const r = await api.items({ q: dq, category: cat || undefined, available: avail, limit: PAGE, offset: shown.length });
      focusFrom.current = shown.length;
      setMore((m) => [...m, ...r.items]);
    } catch (e) {
      setMoreErr(e instanceof ApiError ? e.message : 'Не удалось загрузить');
    } finally {
      setMoreBusy(false);
    }
  }
  return (
    <main>
      <div className="filters" role="search">
        <div className="field field--grow">
          <label htmlFor="q">Поиск по названию и автору</label>
          <input id="q" type="search" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
        </div>
        <div className="field">
          <label htmlFor="cat">Категория</label>
          <select id="cat" value={cat} onChange={(e) => setCat(e.target.value as Category | '')}>
            <option value="">все</option>
            {(Object.keys(CATEGORY) as Category[]).map((c) => (
              <option key={c} value={c}>
                {CATEGORY[c]}
              </option>
            ))}
          </select>
        </div>
        <label className="check">
          <input type="checkbox" checked={avail} onChange={(e) => setAvail(e.target.checked)} /> Только в наличии
        </label>
      </div>
      {error ? <p className="errors" role="alert">{error}</p> : null}
      {data ? (
        <>
          <p className="muted" data-testid="found" aria-live="polite">
            Найдено: {data.total}
            {data.total > shown.length ? `, показаны ${shown.length}` : ''}
          </p>
          {shown.length ? (
            <>
              <ul className="items">
                {shown.map((i) => (
                  <ItemLine key={i.id} i={i} />
                ))}
              </ul>
              {data.total > shown.length ? (
                <p>
                  <button type="button" className="btn" aria-disabled={moreBusy} onClick={() => void loadMore()}>
                    {moreBusy ? 'Загружаю…' : `Показать ещё ${Math.min(PAGE, data.total - shown.length)}`}
                  </button>
                  {moreErr ? <span className="errors" role="alert"> {moreErr}</span> : null}
                </p>
              ) : null}
            </>
          ) : (
            <p className="empty">Ничего не нашлось. Попробуйте другое слово или уберите фильтры.</p>
          )}
        </>
      ) : null}
      {curator ? <NewItem onCreated={(id) => (setNotice('Вещь добавлена в каталог'), reload(), (location.hash = `#item/${id}`))} /> : null}
    </main>
  );
}

function ItemLine({ i }: { i: ItemRow }) {
  return (
    <li className="item" data-testid="item" data-title={i.title}>
      <a href={`#item/${i.id}`} className="item__link">
        <span className="item__title">{i.title}</span>
        <span className="muted small">
          {CATEGORY[i.category]}
          {i.subtitle ? ` · ${i.subtitle}` : ''}
        </span>
      </a>
      <span className={`pill ${i.available ? '' : 'pill--warn'}`}>{availability(i.copies, i.available, i.next_due)}</span>
    </li>
  );
}

function NewItem({ onCreated }: { onCreated: (id: number) => void }) {
  const [f, setF] = useState({ title: '', category: 'book' as Category, subtitle: '', loan_days: '14' });
  const [errs, setErrs] = useState<Record<string, string>>({});
  return (
    <section className="panel" aria-labelledby="new-h">
      <h2 id="new-h">Новая вещь в каталоге</h2>
      <form
        className="row"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const r = await api.createItem({ title: f.title, category: f.category, subtitle: f.subtitle, description: '', loan_days: Number(f.loan_days) });
            setF({ ...f, title: '', subtitle: '' });
            setErrs({});
            onCreated(r.item.id);
          } catch (x) {
            setErrs(x instanceof ApiError ? { ...x.fields, _: x.message } : { _: 'Не удалось сохранить' });
          }
        }}
      >
        <div className="field field--grow">
          <label htmlFor="ni-title">Название</label>
          <input id="ni-title" value={f.title} maxLength={160} onChange={(e) => setF({ ...f, title: e.target.value })} aria-invalid={Boolean(errs.title)} />
          {errs.title ? <p className="error">{errs.title}</p> : null}
        </div>
        <div className="field">
          <label htmlFor="ni-cat">Категория</label>
          <select id="ni-cat" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value as Category })}>
            {(Object.keys(CATEGORY) as Category[]).map((c) => (
              <option key={c} value={c}>
                {CATEGORY[c]}
              </option>
            ))}
          </select>
        </div>
        <div className="field field--grow">
          <label htmlFor="ni-sub">Автор или характеристики</label>
          <input id="ni-sub" value={f.subtitle} maxLength={160} onChange={(e) => setF({ ...f, subtitle: e.target.value })} />
        </div>
        <div className="field field--num">
          <label htmlFor="ni-days">Дней</label>
          <input id="ni-days" inputMode="numeric" value={f.loan_days} maxLength={2} onChange={(e) => setF({ ...f, loan_days: e.target.value })} aria-invalid={Boolean(errs.loan_days)} />
          {errs.loan_days ? <p className="error">{errs.loan_days}</p> : null}
        </div>
        <button type="submit" className="btn btn--primary">
          Добавить
        </button>
      </form>
    </section>
  );
}

/* ---------------- Карточка вещи ---------------- */

function ItemView({ id, curator, setNotice }: { id: number; curator: boolean; setNotice: (t: string) => void }) {
  const [card, setCard] = useState<ItemCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const headRef = useRef<HTMLHeadingElement>(null);
  const load = useCallback(
    () =>
      api
        .item(id)
        .then((c) => (setCard(c), setError(null)))
        .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить')),
    [id],
  );
  useEffect(() => {
    void load();
  }, [load]);
  // Фокус на заголовок, когда карточка впервые отрисована (не раньше: до загрузки заголовка нет).
  const loaded = card !== null;
  useEffect(() => {
    if (loaded) headRef.current?.focus();
  }, [loaded]);

  const borrow = async (copyId: number) => {
    setBusy(copyId);
    setConflict(null);
    try {
      const r = await api.borrow(copyId);
      setNotice(`«${r.loan.title}» выдан вам: ${dueText(r.loan.due_at).text}`);
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Конфликт: сервер вернул свежую карточку — показываем её сразу.
        if (e.data.card) setCard(e.data.card as ItemCard);
        else await load();
        setConflict(`${e.message}. Карточка обновлена.`);
      } else setConflict(e instanceof ApiError ? e.message : 'Не удалось оформить выдачу');
    } finally {
      setBusy(null);
    }
  };
  const giveBack = async (loanId: number) => {
    setBusy(loanId);
    try {
      const r = await api.giveBack(loanId);
      setNotice(r.changed ? `«${r.loan.title}» возвращён` : 'Эта вещь уже была возвращена');
      await load();
    } finally {
      setBusy(null);
    }
  };

  if (error) return <p className="errors" role="alert">{error}</p>;
  if (!card) return <p className="muted">Загрузка…</p>;
  const it = card.item;
  return (
    <main>
      <a href="#catalog" className="btn btn--ghost">
        ← К каталогу
      </a>
      <section className="panel" aria-labelledby="item-h">
        <h2 id="item-h" ref={headRef} tabIndex={-1}>
          {it.title}
        </h2>
        <p className="muted">
          {CATEGORY[it.category]}
          {it.subtitle ? ` · ${it.subtitle}` : ''} · выдаётся на {days(it.loan_days)}
        </p>
        {it.description ? <p>{it.description}</p> : null}
        <p data-testid="availability">
          <span className={`pill ${it.available ? '' : 'pill--warn'}`}>{availability(it.copies, it.available, null)}</span>
        </p>
        {conflict ? (
          <p className="banner" role="alert" data-testid="conflict">
            {conflict}
          </p>
        ) : null}
        <ul className="copies">
          {card.copies.map((c) => {
            const due = c.due_at ? dueText(c.due_at) : null;
            return (
              <li key={c.id} className={`copy copy--${c.status}`} data-testid="copy" data-code={c.code}>
                <span className="copy__code">{c.code}</span>
                <span className="muted small">{c.location}</span>
                <span className="copy__state">
                  {c.status === 'available' ? 'свободен' : c.status === 'retired' ? 'списан' : c.mine ? `у вас · ${due?.text}` : `выдан${c.borrower ? `: ${c.borrower}` : ''} · ${due?.overdue ? due.text : `до ${shortDate(c.due_at!)}`}`}
                </span>
                <span className="copy__actions">
                  {c.status === 'available' ? (
                    <button type="button" className="btn btn--primary" disabled={busy !== null} onClick={() => void borrow(c.id)} aria-label={`Взять ${c.code} на ${days(it.loan_days)}`}>
                      Взять на {days(it.loan_days)}
                    </button>
                  ) : null}
                  {c.loan_id && (c.mine || curator) ? (
                    <button type="button" className="btn" disabled={busy !== null} onClick={() => void giveBack(c.loan_id!)} aria-label={`Вернуть ${c.code}`}>
                      Вернуть
                    </button>
                  ) : null}
                  {curator && c.status !== 'on_loan' ? (
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={() =>
                        void api
                          .retireCopy(c.id, c.status !== 'retired')
                          .then(setCard)
                          .catch((e: unknown) => setConflict(e instanceof ApiError ? e.message : 'Ошибка'))
                      }
                    >
                      {c.status === 'retired' ? 'Вернуть в фонд' : 'Списать'}
                    </button>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
        {curator ? <AddCopy itemId={it.id} onDone={(c) => (setCard(c), setNotice('Экземпляр добавлен'))} /> : null}
      </section>
    </main>
  );
}

function AddCopy({ itemId, onDone }: { itemId: number; onDone: (c: ItemCard) => void }) {
  const [code, setCode] = useState('');
  const [loc, setLoc] = useState('');
  const [err, setErr] = useState<string | null>(null);
  return (
    <form
      className="row"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          onDone(await api.addCopy(itemId, code, loc));
          setCode('');
          setErr(null);
        } catch (x) {
          setErr(x instanceof ApiError ? (x.fields.code ?? x.message) : 'Ошибка');
        }
      }}
    >
      <div className="field">
        <label htmlFor="nc-code">Инвентарный номер</label>
        <input id="nc-code" value={code} maxLength={20} onChange={(e) => setCode(e.target.value)} aria-invalid={Boolean(err)} aria-describedby={err ? 'nc-err' : undefined} />
      </div>
      <div className="field field--grow">
        <label htmlFor="nc-loc">Где лежит</label>
        <input id="nc-loc" value={loc} maxLength={120} onChange={(e) => setLoc(e.target.value)} />
      </div>
      <button type="submit" className="btn">
        Добавить экземпляр
      </button>
      {err ? (
        <p className="error" id="nc-err">
          {err}
        </p>
      ) : null}
    </form>
  );
}

/* ---------------- Выдачи ---------------- */

function LoanTable({ loans, onReturn, showBorrower }: { loans: Loan[]; onReturn?: (l: Loan) => void; showBorrower?: boolean }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Вещь</th>
            <th>Экземпляр</th>
            {showBorrower ? <th>Кто взял</th> : null}
            <th>Срок</th>
            {onReturn ? <th aria-label="Действие" /> : null}
          </tr>
        </thead>
        <tbody>
          {loans.map((l) => {
            const d = l.returned_at ? null : dueText(l.due_at);
            return (
              <tr key={l.id} data-testid="loan" data-code={l.code}>
                <td>
                  <a href={`#item/${l.item_id}`}>{l.title}</a>
                </td>
                <td>{l.code}</td>
                {showBorrower ? <td>{l.borrower}</td> : null}
                <td>{l.returned_at ? `возвращено ${dateTime(l.returned_at)}` : <span className={d?.overdue ? 'bad' : ''}>{d?.text}</span>}</td>
                {onReturn ? (
                  <td>
                    {!l.returned_at ? (
                      <button type="button" className="btn" onClick={() => onReturn(l)} aria-label={`Вернуть «${l.title}» ${l.code}`}>
                        Вернуть
                      </button>
                    ) : null}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MyLoans({ setNotice }: { setNotice: (t: string) => void }) {
  const active = useLoad(() => api.loans('active', true), []);
  const done = useLoad(() => api.loans('returned', true), []);
  const ret = async (l: Loan) => {
    const r = await api.giveBack(l.id);
    setNotice(r.changed ? `«${l.title}» возвращён` : 'Эта вещь уже была возвращена');
    active.reload();
    done.reload();
  };
  return (
    <main>
      <section className="panel" aria-labelledby="act-h">
        <h2 id="act-h">Сейчас у меня</h2>
        {active.data?.loans.length ? <LoanTable loans={active.data.loans} onReturn={(l) => void ret(l)} /> : <p className="empty">Ничего не взято.</p>}
      </section>
      <section className="panel" aria-labelledby="hist-h">
        <h2 id="hist-h">История</h2>
        {done.data?.loans.length ? <LoanTable loans={done.data.loans} /> : <p className="empty">Возвратов пока не было.</p>}
      </section>
    </main>
  );
}

function Overdue({ setNotice }: { setNotice: (t: string) => void }) {
  const od = useLoad(() => api.loans('overdue'), []);
  const all = useLoad(() => api.loans('active'), []);
  const ret = async (l: Loan) => {
    const r = await api.giveBack(l.id);
    setNotice(r.changed ? `«${l.title}» (${l.code}) принят от ${l.borrower}` : 'Уже возвращено');
    od.reload();
    all.reload();
  };
  return (
    <main>
      <section className="panel" aria-labelledby="od-h">
        <h2 id="od-h">Просроченные выдачи</h2>
        {od.data?.loans.length ? <LoanTable loans={od.data.loans} showBorrower onReturn={(l) => void ret(l)} /> : <p className="empty">Просрочек нет.</p>}
      </section>
      <section className="panel" aria-labelledby="all-h">
        <h2 id="all-h">Все открытые выдачи</h2>
        {all.data?.loans.length ? <LoanTable loans={all.data.loans} showBorrower onReturn={(l) => void ret(l)} /> : <p className="empty">Открытых выдач нет.</p>}
      </section>
    </main>
  );
}

function Journal() {
  const { data, error } = useLoad(() => api.events(), []);
  if (error) return <p className="errors">{error}</p>;
  return (
    <main>
      <section className="panel" aria-labelledby="j-h">
        <h2 id="j-h">Последние операции</h2>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Когда</th>
                <th>Кто</th>
                <th>Что</th>
                <th>Вещь</th>
              </tr>
            </thead>
            <tbody>
              {(data?.events ?? []).map((e: EventRow) => (
                <tr key={e.id} data-testid="event" data-kind={e.kind}>
                  <td>{dateTime(e.at)}</td>
                  <td>{e.actor}</td>
                  <td>{e.text}</td>
                  <td>
                    {e.title ?? '—'}
                    {e.code ? ` · ${e.code}` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
