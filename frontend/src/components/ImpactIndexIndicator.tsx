import ProgressBar from '@cloudscape-design/components/progress-bar';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Box from '@cloudscape-design/components/box';
import Header from '@cloudscape-design/components/header';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useI18n } from '../i18n/useI18n';

interface ImpactIndexIndicatorProps {
  impactIndex: number | null;
  impactLevel: string | null;
  sufficientData: boolean;
}

type StatusType = 'error' | 'warning' | 'info' | 'success';

function getLevelStatus(level: string | null): StatusType {
  switch (level) {
    case 'veryHigh':
    case 'high':
      return 'success';
    case 'moderate':
      return 'info';
    case 'low':
      return 'warning';
    default:
      return 'info';
  }
}

export default function ImpactIndexIndicator({ impactIndex, impactLevel, sufficientData }: ImpactIndexIndicatorProps) {
  const { t } = useI18n();

  const levelLabel = impactLevel
    ? t(`git.impact.level.${impactLevel}` as any, { defaultValue: impactLevel })
    : '—';

  if (!sufficientData || impactIndex === null) {
    return (
      <div>
        <Header variant="h2">{t('git.impact.title')}</Header>
        <Box textAlign="center" padding="l" color="text-status-inactive">
          <StatusIndicator type="info">
            {t('git.impact.insufficient')}
          </StatusIndicator>
        </Box>
      </div>
    );
  }

  return (
    <div>
      <Header variant="h2">{t('git.impact.title')}</Header>
      <ColumnLayout columns={2} variant="text-grid">
        <div>
          <Box variant="awsui-key-label">{t('git.impact.indexLabel')}</Box>
          <ProgressBar
            value={impactIndex}
            additionalInfo={`${impactIndex}/100`}
            description={t('git.impact.description')}
          />
        </div>
        <div>
          <Box variant="awsui-key-label">{t('git.impact.classification')}</Box>
          <Box variant="h2">
            <StatusIndicator type={getLevelStatus(impactLevel)}>
              {levelLabel}
            </StatusIndicator>
          </Box>
        </div>
      </ColumnLayout>
    </div>
  );
}
