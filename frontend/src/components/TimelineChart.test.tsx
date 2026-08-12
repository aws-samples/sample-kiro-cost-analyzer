import { render } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LineChart from '@cloudscape-design/components/line-chart';
import { I18nProvider } from '../i18n/I18nProvider';
import { i18n } from '../i18n';
import TimelineChart from './TimelineChart';

let lineChartProps: ComponentProps<typeof LineChart> | undefined;

vi.mock('@cloudscape-design/components/line-chart', () => ({
  default: (props: ComponentProps<typeof LineChart>) => {
    lineChartProps = props;
    return <div data-testid="line-chart" />;
  },
}));

describe('TimelineChart', () => {
  beforeEach(() => {
    lineChartProps = undefined;
  });

  it.each(['en', 'pt-BR'] as const)(
    'formats time-axis ticks as concise %s locale dates',
    async (locale) => {
      await i18n.changeLanguage(locale);

      render(
        <I18nProvider>
          <TimelineChart
            loading={false}
            timeline={[
              {
                period: '2026-07-19',
                totalCredits: 10,
                totalOverageCredits: 2,
                totalMessages: 3,
                totalConversations: 1,
              },
            ]}
          />
        </I18nProvider>,
      );

      const formatter = lineChartProps?.xTickFormatter;
      expect(formatter).toBeTypeOf('function');

      const date = new Date('2026-07-19');
      const label = formatter?.(date);
      const expected = new Intl.DateTimeFormat(locale, {
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC',
      }).format(date);
      const previousDayInBrazil = new Intl.DateTimeFormat('en', {
        month: 'short',
        day: 'numeric',
        timeZone: 'America/Sao_Paulo',
      }).format(date);

      expect(label).toBe(expected);
      expect(label).not.toBe(previousDayInBrazil);
      expect(label).not.toBe(date.toString());
    },
  );
});
