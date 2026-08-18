import { useEffect, useState, useCallback } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Modal from '@cloudscape-design/components/modal';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import FormField from '@cloudscape-design/components/form-field';
import GitRepoForm from '../components/GitRepoForm';
import GitMappingForm from '../components/GitMappingForm';
import { useAuth } from '../auth/useAuth';
import { useI18n } from '../i18n/useI18n';
import { get, ApiError } from '../api/client';
import {
  listGitRepos,
  createGitRepo,
  updateGitRepo,
  deleteGitRepo,
  listGitMappings,
  listAllGitMappings,
  createGitMapping,
  deleteGitMapping,
  type GitRepoPatch,
} from '../api/gitApi';
import type { GitRepository, GitUserMapping, GitMappingCreated, UsageResponse } from '../types';

export default function GitSettingsPage() {
  const { user } = useAuth();
  const { t, formatDateTime } = useI18n();
  const isAdmin = user?.groups?.includes('Admins') ?? false;

  const [repos, setRepos] = useState<GitRepository[]>([]);
  const [reposLoading, setReposLoading] = useState(false);
  const [showRepoForm, setShowRepoForm] = useState(false);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [repoSuccess, setRepoSuccess] = useState<string | null>(null);
  const [repoDeleteTarget, setRepoDeleteTarget] = useState<GitRepository | null>(null);
  const [deletingRepo, setDeletingRepo] = useState(false);
  const [repoEditTarget, setRepoEditTarget] = useState<GitRepository | null>(null);

  const [mappings, setMappings] = useState<GitUserMapping[]>([]);
  const [mappingsLoading, setMappingsLoading] = useState(false);
  const [mappingError, setMappingError] = useState<string | null>(null);
  const [mappingSuccess, setMappingSuccess] = useState<string | null>(null);
  const [mappingDeleteTarget, setMappingDeleteTarget] = useState<GitUserMapping | null>(null);
  const [deletingMapping, setDeletingMapping] = useState(false);
  const [mappingsLastKey, setMappingsLastKey] = useState<string | null>(null);

  const [userOptions, setUserOptions] = useState<SelectProps.Option[]>([]);
  const [selectedMappingUser, setSelectedMappingUser] = useState<SelectProps.Option | null>(null);

  const fetchRepos = useCallback(async () => {
    setReposLoading(true);
    setRepoError(null);
    try {
      const resp = await listGitRepos();
      setRepos(resp.repositories ?? []);
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : t('gitSettings.repos.error.load'));
    } finally {
      setReposLoading(false);
    }
  }, [t]);

  const fetchUsers = useCallback(async () => {
    try {
      const resp = await get<UsageResponse>('/api/usage', { limit: '100' });
      setUserOptions(resp.users.map((u) => ({
        value: u.userId,
        label: u.displayName || u.userName || u.userId,
      })));
    } catch {
      // silently fail
    }
  }, []);

  const fetchMappings = useCallback(async (userId: string) => {
    setMappingsLoading(true);
    setMappingError(null);
    try {
      const resp = await listGitMappings(userId);
      setMappings(resp.mappings ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setMappings([]);
      } else {
        setMappingError(err instanceof Error ? err.message : t('gitSettings.mappings.error.load'));
      }
    } finally {
      setMappingsLoading(false);
    }
  }, [t]);

  /**
   * Cross-user default view (issue #12). `reset` replaces the list (page
   * load / filter cleared); otherwise appends the next page (Load more).
   */
  const fetchAllMappings = useCallback(async (reset: boolean, lastKey?: string) => {
    setMappingsLoading(true);
    setMappingError(null);
    try {
      const resp = await listAllGitMappings(lastKey ? { lastKey } : undefined);
      setMappings((prev) => (reset ? resp.mappings ?? [] : [...prev, ...(resp.mappings ?? [])]));
      setMappingsLastKey(resp.lastKey ?? null);
    } catch (err) {
      setMappingError(err instanceof Error ? err.message : t('gitSettings.mappings.error.load'));
    } finally {
      setMappingsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (isAdmin) {
      fetchRepos();
      fetchUsers();
      fetchAllMappings(true);
    }
  }, [isAdmin, fetchRepos, fetchUsers, fetchAllMappings]);

  async function handleCreateRepo(data: { name: string; url: string; provider: string; accessToken: string }) {
    await createGitRepo(data);
    setRepoSuccess(t('gitSettings.repos.success.added'));
    fetchRepos();
  }

  async function handleUpdateRepo(data: { name: string; url: string; provider: string; accessToken: string }) {
    if (!repoEditTarget) return;
    // Blank token means "keep the current token" — omit it from the patch.
    const body: GitRepoPatch = {
      name: data.name,
      url: data.url,
      provider: data.provider,
      ...(data.accessToken ? { accessToken: data.accessToken } : {}),
    };
    await updateGitRepo(repoEditTarget.repoId, body);
    setRepoSuccess(t('gitSettings.repos.success.updated'));
    setRepoEditTarget(null);
    fetchRepos();
  }

  async function handleDeleteRepo() {
    if (!repoDeleteTarget) return;
    setDeletingRepo(true);
    setRepoError(null);
    try {
      await deleteGitRepo(repoDeleteTarget.repoId);
      setRepoSuccess(t('gitSettings.repos.success.removed'));
      fetchRepos();
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : t('gitSettings.repos.error.delete'));
    } finally {
      setDeletingRepo(false);
      setRepoDeleteTarget(null);
    }
  }

  async function handleCreateMapping(data: { userId: string; provider: string; gitUsername: string }): Promise<GitMappingCreated> {
    const result = await createGitMapping(data);
    if (selectedMappingUser?.value) fetchMappings(selectedMappingUser.value);
    return result;
  }

  async function handleDeleteMapping() {
    if (!mappingDeleteTarget) return;
    setDeletingMapping(true);
    setMappingError(null);
    try {
      await deleteGitMapping(mappingDeleteTarget.userId, mappingDeleteTarget.provider);
      setMappingSuccess(t('gitSettings.mappings.success.removed'));
      if (selectedMappingUser?.value) fetchMappings(selectedMappingUser.value);
      else fetchAllMappings(true);
    } catch (err) {
      setMappingError(err instanceof Error ? err.message : t('gitSettings.mappings.error.delete'));
    } finally {
      setDeletingMapping(false);
      setMappingDeleteTarget(null);
    }
  }

  if (!isAdmin) {
    return (
      <Alert type="error">{t('gitSettings.page.restricted.alert')}</Alert>
    );
  }

  return (
    <SpaceBetween size="l">
        {repoError && <Alert type="error" dismissible onDismiss={() => setRepoError(null)}>{repoError}</Alert>}
        {repoSuccess && <Alert type="success" dismissible onDismiss={() => setRepoSuccess(null)}>{repoSuccess}</Alert>}

        <Table
          loading={reposLoading}
          loadingText={t('gitSettings.repos.loading')}
          header={
            <Header
              variant="h2"
              counter={`(${repos.length})`}
              actions={
                <Button iconName="add-plus" onClick={() => setShowRepoForm(true)}>
                  {t('gitSettings.repos.add')}
                </Button>
              }
            >
              {t('gitSettings.repos.title')}
            </Header>
          }
          empty={
            <Box textAlign="center" color="inherit">
              <b>{t('gitSettings.repos.empty.title')}</b>
              <Box variant="p" color="inherit">{t('gitSettings.repos.empty.description')}</Box>
            </Box>
          }
          columnDefinitions={[
            { id: 'name',     header: t('gitSettings.repos.header.name'),     cell: (item) => item.name,                                    width: 200 },
            { id: 'url',      header: t('gitSettings.repos.header.url'),      cell: (item) => item.url,                                     width: 400 },
            { id: 'provider', header: t('gitSettings.repos.header.provider'), cell: (item) => item.provider,                                width: 120 },
            {
              id: 'token',
              header: t('gitSettings.repos.header.token'),
              cell: (item) => (
                <StatusIndicator type={item.tokenConfigured ? 'success' : 'warning'}>
                  {t(item.tokenConfigured ? 'gitSettings.repos.token.configured' : 'gitSettings.repos.token.missing')}
                </StatusIndicator>
              ),
              width: 150,
            },
            {
              id: 'actions',
              header: t('gitSettings.repos.header.actions'),
              cell: (item) => (
                <SpaceBetween size="xxs" direction="horizontal">
                  <Button iconName="edit" variant="icon" onClick={() => setRepoEditTarget(item)} ariaLabel={t('gitSettings.repos.action.edit')} />
                  <Button iconName="remove" variant="icon" onClick={() => setRepoDeleteTarget(item)} ariaLabel={t('gitSettings.repos.action.remove')} />
                </SpaceBetween>
              ),
              width: 110,
            },
          ]}
          items={repos}
          trackBy="repoId"
        />

        <GitRepoForm
          visible={showRepoForm || repoEditTarget !== null}
          onDismiss={() => { setShowRepoForm(false); setRepoEditTarget(null); }}
          onSubmit={repoEditTarget ? handleUpdateRepo : handleCreateRepo}
          editTarget={repoEditTarget}
        />

        {mappingError && <Alert type="error" dismissible onDismiss={() => setMappingError(null)}>{mappingError}</Alert>}
        {mappingSuccess && <Alert type="success" dismissible onDismiss={() => setMappingSuccess(null)}>{mappingSuccess}</Alert>}

        <Header variant="h2">{t('gitSettings.mappings.title')}</Header>

        <SpaceBetween size="s">
          <FormField label={t('gitSettings.mappings.userSelector.label')}>
            <div style={{ minWidth: 300 }}>
              <Select
                selectedOption={selectedMappingUser}
                onChange={({ detail }) => {
                  const opt = detail.selectedOption;
                  setSelectedMappingUser(opt?.value ? opt : null);
                  setMappingsLastKey(null);
                  if (opt?.value) fetchMappings(opt.value);
                  else fetchAllMappings(true);
                }}
                options={[
                  { value: '', label: t('gitSettings.mappings.userSelector.all') },
                  ...userOptions,
                ]}
                placeholder={t('gitSettings.mappings.userSelector.placeholder')}
                filteringType="auto"
              />
            </div>
          </FormField>

          <Table
            loading={mappingsLoading}
            loadingText={t('gitSettings.mappings.loading')}
            empty={
              <Box textAlign="center" color="inherit">
                <b>{t('gitSettings.mappings.empty.title')}</b>
                <Box variant="p" color="inherit">
                  {selectedMappingUser?.value
                    ? t('gitSettings.mappings.empty.prompt')
                    : t('gitSettings.mappings.empty.noneAnywhere')}
                </Box>
              </Box>
            }
            footer={
              !selectedMappingUser?.value && mappingsLastKey ? (
                <Box textAlign="center">
                  <Button
                    onClick={() => fetchAllMappings(false, mappingsLastKey)}
                    loading={mappingsLoading}
                  >
                    {t('gitSettings.mappings.loadMore')}
                  </Button>
                </Box>
              ) : undefined
            }
            columnDefinitions={[
              {
                id: 'userId',
                header: t('gitSettings.mappings.header.userId'),
                // Resolve the display name from the already-loaded user
                // options; fall back to the raw userId when unknown
                // (issue #18 F3: avoid raw UUIDs as the primary identifier).
                cell: (item) => userOptions.find((o) => o.value === item.userId)?.label ?? item.userId,
                width: 200,
              },
              { id: 'provider',    header: t('gitSettings.mappings.header.provider'),    cell: (item) => item.provider,    width: 120 },
              { id: 'gitUsername', header: t('gitSettings.mappings.header.gitUsername'), cell: (item) => item.gitUsername, width: 180 },
              { id: 'createdAt',   header: t('gitSettings.mappings.header.createdAt'),   cell: (item) => item.createdAt ? formatDateTime(item.createdAt) : '—', width: 180 },
              {
                id: 'actions',
                header: t('gitSettings.mappings.header.actions'),
                cell: (item) => (
                  <Button iconName="remove" variant="icon" onClick={() => setMappingDeleteTarget(item)} ariaLabel={t('gitSettings.mappings.action.remove')} />
                ),
                width: 80,
              },
            ]}
            items={mappings}
            trackBy={(item) => `${item.userId}-${item.provider}-${item.gitUsername}`}
          />

          <GitMappingForm userOptions={userOptions} onSubmit={handleCreateMapping} />
        </SpaceBetween>

        {/* Repository Delete Confirmation Modal */}
        <Modal
          visible={repoDeleteTarget !== null}
          onDismiss={() => setRepoDeleteTarget(null)}
          header={t('gitSettings.repos.deleteModal.title')}
          footer={
            <Box float="right">
              <SpaceBetween size="xs" direction="horizontal">
                <Button variant="link" onClick={() => setRepoDeleteTarget(null)}>
                  {t('common.cancel')}
                </Button>
                <Button variant="primary" onClick={handleDeleteRepo} loading={deletingRepo}>
                  {t('gitSettings.repos.deleteModal.submit')}
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween size="m">
            <Alert type="warning">{t('gitSettings.repos.deleteModal.warning')}</Alert>
            <Box>
              {t('gitSettings.repos.deleteModal.confirm')}{' '}
              <strong>{repoDeleteTarget?.name}</strong> (<strong>{repoDeleteTarget?.url}</strong>)?
            </Box>
          </SpaceBetween>
        </Modal>

        {/* Mapping Delete Confirmation Modal */}
        <Modal
          visible={mappingDeleteTarget !== null}
          onDismiss={() => setMappingDeleteTarget(null)}
          header={t('gitSettings.mappings.deleteModal.title')}
          footer={
            <Box float="right">
              <SpaceBetween size="xs" direction="horizontal">
                <Button variant="link" onClick={() => setMappingDeleteTarget(null)}>
                  {t('common.cancel')}
                </Button>
                <Button variant="primary" onClick={handleDeleteMapping} loading={deletingMapping}>
                  {t('gitSettings.mappings.deleteModal.submit')}
                </Button>
              </SpaceBetween>
            </Box>
          }
        >
          <SpaceBetween size="m">
            <Alert type="warning">{t('gitSettings.mappings.deleteModal.warning')}</Alert>
            <Box>
              {t('gitSettings.mappings.deleteModal.confirm')}{' '}
              <strong>{userOptions.find((o) => o.value === mappingDeleteTarget?.userId)?.label ?? t('common.unidentifiedUser', { id: mappingDeleteTarget?.userId.slice(0, 8) ?? '' })}</strong> → <strong>{mappingDeleteTarget?.gitUsername}</strong> (<strong>{mappingDeleteTarget?.provider}</strong>)?
            </Box>
          </SpaceBetween>
        </Modal>
      </SpaceBetween>
  );
}
