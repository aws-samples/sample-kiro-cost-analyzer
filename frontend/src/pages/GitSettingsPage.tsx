import { useEffect, useState, useCallback } from 'react';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Table from '@cloudscape-design/components/table';
import Button from '@cloudscape-design/components/button';
import Box from '@cloudscape-design/components/box';
import Alert from '@cloudscape-design/components/alert';
import Select, { type SelectProps } from '@cloudscape-design/components/select';
import FormField from '@cloudscape-design/components/form-field';
import GitRepoForm from '../components/GitRepoForm';
import GitMappingForm from '../components/GitMappingForm';
import { useAuth } from '../auth/useAuth';
import { useI18n } from '../i18n/useI18n';
import { get, ApiError } from '../api/client';
import {
  listGitRepos,
  createGitRepo,
  deleteGitRepo,
  listGitMappings,
  createGitMapping,
  deleteGitMapping,
} from '../api/gitApi';
import type { GitRepository, GitUserMapping, UsageResponse } from '../types';

export default function GitSettingsPage() {
  const { user } = useAuth();
  const { t, formatDateTime } = useI18n();
  const isAdmin = user?.groups?.includes('Admins') ?? false;

  const [repos, setRepos] = useState<GitRepository[]>([]);
  const [reposLoading, setReposLoading] = useState(false);
  const [showRepoForm, setShowRepoForm] = useState(false);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [repoSuccess, setRepoSuccess] = useState<string | null>(null);

  const [mappings, setMappings] = useState<GitUserMapping[]>([]);
  const [mappingsLoading, setMappingsLoading] = useState(false);
  const [mappingError, setMappingError] = useState<string | null>(null);

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

  useEffect(() => {
    if (isAdmin) {
      fetchRepos();
      fetchUsers();
    }
  }, [isAdmin, fetchRepos, fetchUsers]);

  async function handleCreateRepo(data: { name: string; url: string; provider: string; accessToken: string }) {
    await createGitRepo(data);
    setRepoSuccess(t('gitSettings.repos.success.added'));
    fetchRepos();
  }

  async function handleDeleteRepo(repoId: string) {
    setRepoError(null);
    try {
      await deleteGitRepo(repoId);
      setRepoSuccess(t('gitSettings.repos.success.removed'));
      fetchRepos();
    } catch (err) {
      setRepoError(err instanceof Error ? err.message : t('gitSettings.repos.error.delete'));
    }
  }

  async function handleCreateMapping(data: { userId: string; provider: string; gitUsername: string }) {
    await createGitMapping(data);
    if (selectedMappingUser?.value) fetchMappings(selectedMappingUser.value);
  }

  async function handleDeleteMapping(m: GitUserMapping) {
    setMappingError(null);
    try {
      await deleteGitMapping(m.userId, m.provider, m.gitUsername);
      if (selectedMappingUser?.value) fetchMappings(selectedMappingUser.value);
    } catch (err) {
      setMappingError(err instanceof Error ? err.message : t('gitSettings.mappings.error.delete'));
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
              id: 'actions',
              header: t('gitSettings.repos.header.actions'),
              cell: (item) => (
                <Button iconName="remove" variant="icon" onClick={() => handleDeleteRepo(item.repoId)} ariaLabel={t('gitSettings.repos.action.remove')} />
              ),
              width: 80,
            },
          ]}
          items={repos}
          trackBy="repoId"
        />

        <GitRepoForm visible={showRepoForm} onDismiss={() => setShowRepoForm(false)} onSubmit={handleCreateRepo} />

        {mappingError && <Alert type="error" dismissible onDismiss={() => setMappingError(null)}>{mappingError}</Alert>}

        <Header variant="h2">{t('gitSettings.mappings.title')}</Header>

        <SpaceBetween size="s">
          <FormField label={t('gitSettings.mappings.userSelector.label')}>
            <div style={{ minWidth: 300 }}>
              <Select
                selectedOption={selectedMappingUser}
                onChange={({ detail }) => {
                  const opt = detail.selectedOption;
                  setSelectedMappingUser(opt?.value ? opt : null);
                  if (opt?.value) fetchMappings(opt.value);
                  else setMappings([]);
                }}
                options={[
                  { value: '', label: t('gitSettings.mappings.userSelector.placeholder') },
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
                    : t('gitSettings.mappings.empty.selectUser')}
                </Box>
              </Box>
            }
            columnDefinitions={[
              { id: 'userId',      header: t('gitSettings.mappings.header.userId'),      cell: (item) => item.userId,      width: 200 },
              { id: 'provider',    header: t('gitSettings.mappings.header.provider'),    cell: (item) => item.provider,    width: 120 },
              { id: 'gitUsername', header: t('gitSettings.mappings.header.gitUsername'), cell: (item) => item.gitUsername, width: 180 },
              { id: 'createdAt',   header: t('gitSettings.mappings.header.createdAt'),   cell: (item) => item.createdAt ? formatDateTime(item.createdAt) : '—', width: 180 },
              {
                id: 'actions',
                header: t('gitSettings.mappings.header.actions'),
                cell: (item) => (
                  <Button iconName="remove" variant="icon" onClick={() => handleDeleteMapping(item)} ariaLabel={t('gitSettings.mappings.action.remove')} />
                ),
                width: 80,
              },
            ]}
            items={mappings}
            trackBy={(item) => `${item.userId}-${item.provider}-${item.gitUsername}`}
          />

          <GitMappingForm userOptions={userOptions} onSubmit={handleCreateMapping} />
        </SpaceBetween>
      </SpaceBetween>
  );
}
