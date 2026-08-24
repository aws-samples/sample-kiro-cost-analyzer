import Table from '@cloudscape-design/components/table';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Alert from '@cloudscape-design/components/alert';
import { useI18n } from '../i18n/useI18n';
import {
  EM_DASH,
  EXECUTION_STATUS_LABEL_KEYS,
  executionStatusType,
  formatElapsed,
} from '../utils/etlHistoryFormat';
import type { EtlExecution } from '../types';

interface EtlExecutionHistoryProps {
  executions: EtlExecution[];
  loading: boolean;
  error: string | null;
  days: number;
}

/**
 * Execution history for the ETL pipeline.
 *
 * Timing and outcome come from Step Functions; the file and record counters come
 * from the per-execution records the ETL persists. A counter is null — rendered
 * as an em dash — when no record exists for that execution, which is the case
 * for runs that predate this feature. That is deliberately distinct from a run
 * that genuinely processed zero files.
 */
export default function EtlExecutionHistory({
  executions,
  loading,
  error,
  days,
}: EtlExecutionHistoryProps) {
  const { t, formatDateTime, formatNumber } = useI18n();

  const renderDate = (value: string | null) => (value ? formatDateTime(value) : EM_DASH);

  const renderCount = (value: number | null) =>
    typeof value === 'number' ? formatNumber(value) : EM_DASH;

  return (
    <Container
      header={
        <Header variant="h2" description={t('settings.etl.history.description', { days })}>
          {t('settings.etl.history.title')}
        </Header>
      }
    >
      {error ? (
        <Alert type="error">{error}</Alert>
      ) : (
        <Table
          variant="embedded"
          loading={loading}
          loadingText={t('settings.etl.history.loading')}
          items={executions}
          trackBy="executionName"
          empty={
            <Box textAlign="center" color="inherit">
              <b>{t('settings.etl.history.empty.title')}</b>
              <Box variant="p" color="inherit">
                {t('settings.etl.history.empty.description', { days })}
              </Box>
            </Box>
          }
          columnDefinitions={[
            {
              id: 'startDate',
              header: t('settings.etl.history.header.startDate'),
              cell: (item) => renderDate(item.startDate),
            },
            {
              id: 'endDate',
              header: t('settings.etl.history.header.endDate'),
              cell: (item) => renderDate(item.stopDate),
            },
            {
              id: 'elapsed',
              header: t('settings.etl.history.header.elapsed'),
              cell: (item) => formatElapsed(item.elapsedSeconds),
            },
            {
              id: 'files',
              header: t('settings.etl.history.header.files'),
              cell: (item) => renderCount(item.filesProcessed),
            },
            {
              id: 'status',
              header: t('settings.etl.history.header.status'),
              cell: (item) => {
                const labelKey =
                  EXECUTION_STATUS_LABEL_KEYS[
                    item.status as keyof typeof EXECUTION_STATUS_LABEL_KEYS
                  ];
                return (
                  <StatusIndicator type={executionStatusType(item.status)}>
                    {labelKey ? t(labelKey) : item.status}
                  </StatusIndicator>
                );
              },
            },
          ]}
        />
      )}
    </Container>
  );
}
