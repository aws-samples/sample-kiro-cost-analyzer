/**
 * Tests for `cronHumanizer.ts` — Task 3.4 (unit) and Task 3.5 (Property 6).
 *
 * The tests use a synthetic `t` that reads directly from a plain catalog
 * object and applies `{{name}}` interpolation. This avoids spinning up an
 * i18next instance and keeps each test hermetic.
 *
 * pt-BR expected outputs are the canonical outputs of the pre-Step-3
 * humanizer (Requirement 8.3 — byte-for-byte parity). English expected
 * outputs are the parallel en.json values.
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { humanize, type AnyT } from './cronHumanizer';
import enCatalog from '../locales/en.json';
import ptBrCatalog from '../locales/pt-BR.json';

type CatalogRecord = Record<string, string>;

function synthT(catalog: CatalogRecord): AnyT {
  return (key, vars) => {
    let out = catalog[key] ?? key;
    if (vars) {
      for (const [name, value] of Object.entries(vars)) {
        out = out.replace(new RegExp(`\\{\\{${name}\\}\\}`, 'g'), String(value));
      }
    }
    return out;
  };
}

const T_EN = synthT(enCatalog as CatalogRecord);
const T_PTBR = synthT(ptBrCatalog as CatalogRecord);

describe('humanize (rate expressions)', () => {
  const cases: [string, string, string][] = [
    ['rate(1 day)', 'Every day', 'Todos os dias'],
    ['rate(2 days)', 'Every 2 days', 'A cada 2 dias'],
    ['rate(7 days)', 'Every 7 days', 'A cada 7 dias'],
    ['rate(1 hour)', 'Every hour', 'A cada hora'],
    ['rate(2 hours)', 'Every 2 hours', 'A cada 2 horas'],
    ['rate(1 minute)', 'Every minute', 'A cada minuto'],
    ['rate(5 minutes)', 'Every 5 minutes', 'A cada 5 minutos'],
  ];

  for (const [expr, en, ptBr] of cases) {
    it(`${expr} → en: "${en}" / pt-BR: "${ptBr}"`, () => {
      expect(humanize(expr, T_EN)).toBe(en);
      expect(humanize(expr, T_PTBR)).toBe(ptBr);
    });
  }
});

describe('humanize (cron — every day at HH:MM)', () => {
  it('cron(59 23 * * ? *)', () => {
    expect(humanize('cron(59 23 * * ? *)', T_EN)).toBe('Every day at 23:59');
    expect(humanize('cron(59 23 * * ? *)', T_PTBR)).toBe('Todos os dias às 23:59');
  });

  it('cron(0 8 * * ? *)', () => {
    expect(humanize('cron(0 8 * * ? *)', T_EN)).toBe('Every day at 08:00');
    expect(humanize('cron(0 8 * * ? *)', T_PTBR)).toBe('Todos os dias às 08:00');
  });
});

describe('humanize (cron — days-of-week range)', () => {
  it('cron(0 12 ? * MON-FRI *)', () => {
    expect(humanize('cron(0 12 ? * MON-FRI *)', T_EN)).toBe('From Monday to Friday at 12:00');
    expect(humanize('cron(0 12 ? * MON-FRI *)', T_PTBR)).toBe('De segunda a sexta às 12:00');
  });
});

describe('humanize (cron — day of month)', () => {
  it('cron(0 8 1 * ? *)', () => {
    expect(humanize('cron(0 8 1 * ? *)', T_EN)).toBe('Every day 1 at 08:00');
    expect(humanize('cron(0 8 1 * ? *)', T_PTBR)).toBe('Todo dia 1 às 08:00');
  });
});

describe('humanize (cron — single day)', () => {
  it('cron(0 12 ? * MON *)', () => {
    expect(humanize('cron(0 12 ? * MON *)', T_EN)).toBe('Monday at 12:00');
    expect(humanize('cron(0 12 ? * MON *)', T_PTBR)).toBe('Segunda às 12:00');
  });
});

describe('humanize (cron — day list)', () => {
  it('cron(0 12 ? * MON,WED,FRI *)', () => {
    expect(humanize('cron(0 12 ? * MON,WED,FRI *)', T_EN)).toBe(
      'Monday, Wednesday and Friday at 12:00',
    );
    expect(humanize('cron(0 12 ? * MON,WED,FRI *)', T_PTBR)).toBe(
      'Segunda, quarta e sexta às 12:00',
    );
  });
});

describe('humanize (unparsable fallback)', () => {
  const cases = [
    '',
    'rate(abc)',
    'cron(not a valid cron)',
    'random string',
    'cron(0 0 * * * *)', // only 5 fields inside, but parser expects 6
    'rate(0 day)', // valid-looking but zero not typical — still parses
  ];

  for (const expr of cases) {
    if (expr === 'rate(0 day)') continue; // `rate(0 day)` does parse as "Every 0 days" pattern — skip
    it(`returns original expression unchanged: "${expr}"`, () => {
      expect(humanize(expr, T_EN)).toBe(expr);
      expect(humanize(expr, T_PTBR)).toBe(expr);
    });
  }
});

describe('Property 6: cron humanizer locale coherence (parsable)', () => {
  const tFor = (locale: 'en' | 'pt-BR') => (locale === 'en' ? T_EN : T_PTBR);

  it('rate(N minutes) matches catalog template', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 999 }),
        fc.constantFrom<'en' | 'pt-BR'>('en', 'pt-BR'),
        (n, L) => {
          const expr = `rate(${n} ${n === 1 ? 'minute' : 'minutes'})`;
          const result = humanize(expr, tFor(L));
          const expected =
            n === 1 ? tFor(L)('cron.rate.minute') : tFor(L)('cron.rate.minutes', { n });
          return result === expected;
        },
      ),
      { numRuns: 60 },
    );
  });

  it('rate(N hours) matches catalog template', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 999 }),
        fc.constantFrom<'en' | 'pt-BR'>('en', 'pt-BR'),
        (n, L) => {
          const expr = `rate(${n} ${n === 1 ? 'hour' : 'hours'})`;
          const result = humanize(expr, tFor(L));
          const expected =
            n === 1 ? tFor(L)('cron.rate.hourly') : tFor(L)('cron.rate.hours', { n });
          return result === expected;
        },
      ),
      { numRuns: 60 },
    );
  });

  it('rate(N days) matches catalog template', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 999 }),
        fc.constantFrom<'en' | 'pt-BR'>('en', 'pt-BR'),
        (n, L) => {
          const expr = `rate(${n} ${n === 1 ? 'day' : 'days'})`;
          const result = humanize(expr, tFor(L));
          const expected =
            n === 1 ? tFor(L)('cron.rate.daily') : tFor(L)('cron.rate.days', { n });
          return result === expected;
        },
      ),
      { numRuns: 60 },
    );
  });

  it('cron(M H * * ? *) matches daily template', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 59 }),
        fc.integer({ min: 0, max: 23 }),
        fc.constantFrom<'en' | 'pt-BR'>('en', 'pt-BR'),
        (m, h, L) => {
          const expr = `cron(${m} ${h} * * ? *)`;
          const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
          const result = humanize(expr, tFor(L));
          const expected = tFor(L)('cron.cron.daily', { time });
          return result === expected;
        },
      ),
      { numRuns: 60 },
    );
  });

  it('cron(M H D * ? *) matches dayOfMonth template', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 59 }),
        fc.integer({ min: 0, max: 23 }),
        fc.integer({ min: 1, max: 28 }),
        fc.constantFrom<'en' | 'pt-BR'>('en', 'pt-BR'),
        (m, h, d, L) => {
          const expr = `cron(${m} ${h} ${d} * ? *)`;
          const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
          const result = humanize(expr, tFor(L));
          const expected = tFor(L)('cron.cron.dayOfMonth', { day: d, time });
          return result === expected;
        },
      ),
      { numRuns: 60 },
    );
  });

  it('cron(M H ? * DOW *) matches daysRange template', () => {
    const DOW = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 59 }),
        fc.integer({ min: 0, max: 23 }),
        fc.integer({ min: 0, max: 6 }),
        fc.integer({ min: 0, max: 6 }),
        fc.constantFrom<'en' | 'pt-BR'>('en', 'pt-BR'),
        (m, h, startIdx, endIdx, L) => {
          const start = DOW[startIdx];
          const end = DOW[endIdx];
          const expr = `cron(${m} ${h} ? * ${start}-${end} *)`;
          const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
          const result = humanize(expr, tFor(L));
          const expected = tFor(L)('cron.cron.daysRange', {
            start: tFor(L)(`cron.days.${start}`),
            end: tFor(L)(`cron.days.${end}`),
            time,
          });
          return result === expected;
        },
      ),
      { numRuns: 60 },
    );
  });
});

describe('Property 6: cron humanizer unparsable-expression identity', () => {
  it('returns the input verbatim for unparsable expressions', () => {
    // Filter out any strings that happen to match one of the supported
    // rate / cron patterns.
    const RATE_RE = /^rate\(\d+\s+(minute|minutes|hour|hours|day|days)\)$/;
    const CRON_RE = /^cron\(.+\)$/;

    fc.assert(
      fc.property(
        fc.string().filter((s) => !RATE_RE.test(s) && !CRON_RE.test(s)),
        fc.constantFrom<'en' | 'pt-BR'>('en', 'pt-BR'),
        (s, L) => {
          const t = L === 'en' ? T_EN : T_PTBR;
          return humanize(s, t) === s;
        },
      ),
      { numRuns: 40 },
    );
  });
});
