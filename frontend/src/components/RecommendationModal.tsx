import Modal from '@cloudscape-design/components/modal';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Button from '@cloudscape-design/components/button';
import { useI18n } from '../i18n/useI18n';
import type { TierRecommendation } from '../types';

interface RecommendationModalProps {
  recommendation: TierRecommendation | null;
  visible: boolean;
  onDismiss: () => void;
}

export default function RecommendationModal({
  recommendation,
  visible,
  onDismiss,
}: RecommendationModalProps) {
  const { t, formatNumber } = useI18n();

  const formatUSD = (value: number) =>
    formatNumber(value, { style: 'currency', currency: 'USD' });

  return (
    <Modal
      visible={visible}
      onDismiss={onDismiss}
      header={t('recommendations.modal.title')}
      closeAriaLabel={t('recommendations.modal.close')}
      footer={
        <Box float="right">
          <Button variant="primary" onClick={onDismiss}>
            {t('recommendations.modal.close')}
          </Button>
        </Box>
      }
    >
      {recommendation && (
        <SpaceBetween size="l">
          <ColumnLayout columns={2} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">
                {t('recommendations.modal.currentTier')}
              </Box>
              <div>{recommendation.currentTier}</div>
            </div>
            <div>
              <Box variant="awsui-key-label">
                {t('recommendations.modal.projectedUsage')}
              </Box>
              <div>
                {formatNumber(recommendation.projectedMonthlyUsage)}
              </div>
            </div>
            <div>
              <Box variant="awsui-key-label">
                {t('recommendations.modal.currentMonthlyCost')}
              </Box>
              <div>{formatUSD(recommendation.currentMonthlyCost)}</div>
            </div>
            <div>
              <Box variant="awsui-key-label">
                {t('recommendations.modal.recommendedTier')}
              </Box>
              <div>{recommendation.recommendedTier}</div>
            </div>
            <div>
              <Box variant="awsui-key-label">
                {t('recommendations.modal.recommendedMonthlyCost')}
              </Box>
              <div>{formatUSD(recommendation.recommendedMonthlyCost)}</div>
            </div>
            <div>
              <Box variant="awsui-key-label">
                {t('recommendations.modal.annualSavings')}
              </Box>
              <div>{formatUSD(recommendation.annualSavings)}</div>
            </div>
          </ColumnLayout>
        </SpaceBetween>
      )}
    </Modal>
  );
}
