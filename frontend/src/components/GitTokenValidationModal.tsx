import Modal from '@cloudscape-design/components/modal';
import Box from '@cloudscape-design/components/box';
import Button from '@cloudscape-design/components/button';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Alert from '@cloudscape-design/components/alert';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import { useI18n } from '../i18n/useI18n';
import type { GitTokenCheckStatus, GitTokenValidation } from '../types';
import type { TranslationKey } from '../locales/keys';

interface GitTokenValidationModalProps {
  /** The validation to render; null keeps the modal closed. */
  result: GitTokenValidation | null;
  onDismiss: () => void;
}

/**
 * i18next treats ":" as a namespace separator, so a permission identifier
 * like "contents:read" cannot be interpolated into a key as-is. Slugify it.
 *
 * Each permission carries two sub-keys: `name` is the provider's own literal
 * label (identical in every locale, like a brand string) and `level` is the
 * translated access level to grant.
 */
function permissionKey(permission: string, part: 'name' | 'level'): TranslationKey {
  const slug = permission.replace(/:/g, '_');
  return `gitTokenValidation.permission.${slug}.${part}` as TranslationKey;
}

/**
 * Explains a failed or partial token validation and names the exact
 * permissions to grant.
 *
 * Permission names (Contents, Pull requests, Metadata, repo, read_api) are
 * rendered untranslated inside translated sentences on purpose: they are
 * the labels the user will look for in GitHub's or GitLab's own UI, which
 * does not follow the KCA locale. Translating them would send a pt-BR user
 * hunting for a control that does not exist under that name.
 */
export default function GitTokenValidationModal({
  result,
  onDismiss,
}: GitTokenValidationModalProps) {
  const { t } = useI18n();

  if (!result) return null;

  const alertType = result.overall === 'failed' ? 'error' : 'warning';

  const indicatorFor = (status: GitTokenCheckStatus) => {
    if (status === 'ok') return 'success';
    if (status === 'rate_limited' || status === 'unreachable') return 'warning';
    return 'error';
  };

  return (
    <Modal
      visible={result !== null}
      onDismiss={onDismiss}
      header={t('gitTokenValidation.modal.title')}
      footer={
        <Box float="right">
          <SpaceBetween size="xs" direction="horizontal">
            <Button variant="primary" onClick={onDismiss}>
              {t('common.close')}
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="m">
        <Alert type={alertType}>
          {result.tokenMissing
            ? t('gitTokenValidation.summary.tokenMissing')
            : t(
                result.overall === 'failed'
                  ? 'gitTokenValidation.summary.failed'
                  : 'gitTokenValidation.summary.partial',
              )}
        </Alert>

        <Box>
          <Box variant="h4">{t('gitTokenValidation.checks.title')}</Box>
          <SpaceBetween size="xs">
            {result.checks.map((check) => (
              <StatusIndicator key={check.id} type={indicatorFor(check.status)}>
                {t(`gitTokenValidation.check.${check.id}` as TranslationKey)}
                {' — '}
                {t(`gitTokenValidation.status.${check.status}` as TranslationKey)}
                {check.httpStatus !== null ? ` (HTTP ${check.httpStatus})` : ''}
              </StatusIndicator>
            ))}
          </SpaceBetween>
        </Box>

        {result.requiredPermissions.length > 0 && (
          <Box>
            <Box variant="h4">{t('gitTokenValidation.remediation.title')}</Box>
            <SpaceBetween size="s">
              <Box variant="p">
                {t(
                  result.provider === 'github'
                    ? 'gitTokenValidation.remediation.intro.github'
                    : 'gitTokenValidation.remediation.intro.gitlab',
                )}
              </Box>

              {/* Same shape for every provider: one row per permission, the
                  identifier in code type and the level in bold, so the two
                  things the user must act on are the two things that stand
                  out. */}
              <ul>
                {result.requiredPermissions.map((permission) => (
                  <li key={permission}>
                    <Box variant="code" display="inline">
                      {t(permissionKey(permission, 'name'))}
                    </Box>
                    {' — '}
                    <Box variant="strong" display="inline">
                      {t(permissionKey(permission, 'level'))}
                    </Box>
                  </li>
                ))}
              </ul>

              <Box variant="p">
                {t(
                  result.provider === 'github'
                    ? 'gitTokenValidation.remediation.note.github.prefix'
                    : 'gitTokenValidation.remediation.note.gitlab.prefix',
                )}{' '}
                <Box variant="code" display="inline">
                  {t(
                    result.provider === 'github'
                      ? 'gitTokenValidation.remediation.note.github.term'
                      : 'gitTokenValidation.remediation.note.gitlab.term',
                  )}
                </Box>{' '}
                {t(
                  result.provider === 'github'
                    ? 'gitTokenValidation.remediation.note.github.suffix'
                    : 'gitTokenValidation.remediation.note.gitlab.suffix',
                )}
              </Box>
            </SpaceBetween>
          </Box>
        )}
      </SpaceBetween>
    </Modal>
  );
}
