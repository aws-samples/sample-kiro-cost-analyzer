# Plano de Implementação: Quick Wins UI/UX (M1–M6)

## Visão Geral

Este plano implementa as seis melhorias rápidas de UI/UX do Kiro Cost Analyzer de forma incremental. Começa pela fundação (componente reutilizável e hook), depois aplica nas páginas, corrige o bug de export, adiciona branding e finaliza com o agendamento do ETL (backend + frontend).

## Tasks

- [x] 1. Criar componente LocalizedDateRangePicker com valor padrão "Últimos 30 dias"
  - [x] 1.1 Criar `frontend/src/components/LocalizedDateRangePicker.tsx`
    - Definir interface `LocalizedDateRangePickerProps` com props `value`, `onChange`, `placeholder` (default: "Selecione o período"), `relativeOptions` (default: 7d, 30d, 90d) e `i18nStrings` (default: strings pt-BR)
    - Exportar constante `DEFAULT_DATE_RANGE` com `{ type: 'relative', amount: 30, unit: 'day' }`
    - Encapsular o `DateRangePicker` do Cloudscape com todas as strings i18n atualmente duplicadas nas 3 páginas
    - Incluir validação de range absoluto (data inicial anterior à final)
    - _Requisitos: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 1.2 Escrever teste de propriedade para validação de range absoluto
    - **Property 1: Validação de range absoluto rejeita datas invertidas**
    - Para quaisquer duas datas onde `startDate > endDate`, a validação retorna `{ valid: false }`. Para `startDate <= endDate`, retorna `{ valid: true }`.
    - Criar `frontend/src/components/__tests__/LocalizedDateRangePicker.test.ts` usando `fast-check`
    - **Valida: Requisito 2.5**

  - [ ]* 1.3 Escrever testes unitários para LocalizedDateRangePicker
    - Verificar que renderiza com defaults pt-BR
    - Verificar que aceita placeholder customizado
    - Verificar que opções relativas 7d/30d/90d estão presentes
    - Verificar que `DEFAULT_DATE_RANGE` tem os valores corretos
    - _Requisitos: 2.1, 2.3, 2.4_

- [x] 2. Criar hook useLastUpdated
  - [x] 2.1 Criar `frontend/src/hooks/useLastUpdated.ts`
    - Implementar hook com interface `{ lastUpdated, formattedTime, markUpdated }`
    - `markUpdated()` salva `new Date()` no state
    - `formattedTime` formata com `toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })`
    - Retornar `null` para `formattedTime` antes do primeiro `markUpdated()`
    - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 2.2 Escrever teste de propriedade para formatação de timestamp
    - **Property 2: Formatação de timestamp produz formato HH:mm válido**
    - Para qualquer objeto `Date` válido, a formatação produz string no formato `HH:mm` (24h) correspondente ao horário no locale pt-BR.
    - Criar `frontend/src/hooks/__tests__/useLastUpdated.test.ts` usando `fast-check`
    - **Valida: Requisito 3.6**

  - [ ]* 2.3 Escrever testes unitários para useLastUpdated
    - Verificar que `formattedTime` retorna `null` antes do primeiro update
    - Verificar que `markUpdated()` atualiza o timestamp
    - Verificar que chamadas subsequentes a `markUpdated()` atualizam o horário
    - _Requisitos: 3.4, 3.5_

- [x] 3. Integrar LocalizedDateRangePicker e useLastUpdated nas páginas
  - [x] 3.1 Refatorar DashboardPage
    - Substituir o `DateRangePicker` inline pelo `LocalizedDateRangePicker`
    - Inicializar `dateRange` com `DEFAULT_DATE_RANGE` em vez de `null`
    - Integrar `useLastUpdated`: chamar `markUpdated()` após `setData(resp)` no `fetchData`
    - Exibir `formattedTime` no `Header` via prop `description`
    - Remover ~40 linhas de configuração i18n duplicada
    - _Requisitos: 1.1, 1.4, 1.5, 2.7, 3.1, 3.4, 3.5_

  - [x] 3.2 Refatorar AccountUsagePage
    - Substituir o `DateRangePicker` inline pelo `LocalizedDateRangePicker`
    - Inicializar `dateRange` com `DEFAULT_DATE_RANGE` em vez de `null`
    - Integrar `useLastUpdated`: chamar `markUpdated()` após `setData(resp)` no `fetchData`
    - Exibir `formattedTime` no `Header` via prop `description`
    - Remover ~40 linhas de configuração i18n duplicada
    - _Requisitos: 1.2, 2.8, 3.2, 3.4, 3.5_

  - [x] 3.3 Refatorar UserDetailPage
    - Substituir o `DateRangePicker` inline pelo `LocalizedDateRangePicker`
    - Inicializar `dateRange` com `DEFAULT_DATE_RANGE` em vez de `null`
    - Integrar `useLastUpdated`: chamar `markUpdated()` após `setData(resp)` no `fetchData`
    - Exibir `formattedTime` no `Header` via prop `description`
    - Remover ~40 linhas de configuração i18n duplicada
    - _Requisitos: 1.3, 2.9, 3.3, 3.4, 3.5_

- [x] 4. Checkpoint — Verificar componente e hook
  - Garantir que o build compila sem erros (`tsc -b && vite build`)
  - Garantir que todos os testes passam
  - Perguntar ao usuário se há dúvidas

- [x] 5. Corrigir export CSV no DashboardPage
  - [x] 5.1 Corrigir função `handleExport` em `frontend/src/pages/DashboardPage.tsx`
    - Para formato CSV: usar a string retornada diretamente no Blob sem `JSON.stringify`
    - Para formato JSON: aplicar `JSON.stringify(resp, null, 2)` antes de criar o Blob
    - Usar content-type `text/csv;charset=utf-8` para CSV e `application/json` para JSON
    - Manter extensão `.csv` e `.json` no download
    - Manter tratamento de erro com mensagem "Erro ao exportar dados"
    - _Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 5.2 Escrever teste de propriedade para CSV Blob
    - **Property 3: CSV Blob preserva conteúdo original**
    - Para qualquer string CSV retornada pelo backend, o conteúdo do Blob gerado com formato "csv" é idêntico à string original.
    - Criar `frontend/src/pages/__tests__/handleExport.test.ts` usando `fast-check`
    - **Valida: Requisito 4.2**

  - [ ]* 5.3 Escrever teste de propriedade para JSON Blob
    - **Property 4: JSON Blob aplica stringify**
    - Para qualquer objeto retornado pelo backend, o conteúdo do Blob gerado com formato "json" é igual a `JSON.stringify(objeto, null, 2)`.
    - Adicionar ao arquivo `frontend/src/pages/__tests__/handleExport.test.ts` usando `fast-check`
    - **Valida: Requisito 4.3**

- [x] 6. Adicionar branding na LoginPage
  - [x] 6.1 Copiar logo e atualizar LoginPage
    - Copiar `docs/logo.png` para `frontend/src/assets/logo.png`
    - Importar logo como asset estático no `LoginPage.tsx`
    - Adicionar bloco de branding acima do Container: imagem do logo (80x80), título "Kiro Cost Analyzer" (`Box variant="h1"`), tagline "Monitoramento de custos e uso de IA" (`Box variant="p"`)
    - Centralizar verticalmente e horizontalmente com flexbox (`min-height: 100vh`, `display: flex`, `align-items: center`, `justify-content: center`)
    - Adicionar `onError` handler na imagem para esconder o logo se falhar ao carregar
    - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ]* 6.2 Escrever testes unitários para LoginPage branding
    - Verificar que logo, título e tagline estão visíveis
    - Verificar fallback quando logo falha ao carregar
    - _Requisitos: 5.1, 5.2, 5.3, 5.6_

- [x] 7. Checkpoint — Verificar correções frontend
  - Garantir que o build compila sem erros
  - Garantir que todos os testes passam
  - Perguntar ao usuário se há dúvidas

- [x] 8. Implementar endpoint de agendamento do ETL (backend)
  - [x] 8.1 Atualizar infraestrutura no `template.yaml`
    - Alterar valor padrão do parâmetro `EtlScheduleExpression` de `rate(1 day)` para `cron(59 23 * * ? *)`
    - Adicionar variável de ambiente `ETL_SCHEDULE_NAME` ao `BackendFunction` referenciando o nome do schedule do EventBridge Scheduler (derivado do `EtlStateMachine`)
    - Adicionar permissão `scheduler:GetSchedule` ao `BackendFunction`
    - Adicionar novo evento API Gateway `GET /api/config/schedule` ao `BackendFunction`
    - _Requisitos: 6.2, 6.8_

  - [x] 8.2 Implementar `handle_get_schedule` em `backend/handlers/config_handler.py`
    - Criar função que consulta o EventBridge Scheduler via `scheduler.get_schedule(Name=...)`
    - Retornar `{ expression, enabled, humanReadable }` em caso de sucesso
    - Retornar `{ expression: null, enabled: false, humanReadable: "Agendamento indisponível", error: true }` em caso de falha
    - Ler nome do schedule da variável de ambiente `ETL_SCHEDULE_NAME`
    - _Requisitos: 6.2, 6.6, 6.7, 6.8_

  - [x] 8.3 Adicionar rota no `backend/handler.py`
    - Adicionar rota `GET /api/config/schedule` que chama `config_handler.handle_get_schedule()`
    - Posicionar entre os endpoints públicos (qualquer usuário autenticado)
    - _Requisitos: 6.2_

  - [ ]* 8.4 Escrever testes unitários para `handle_get_schedule`
    - Mock do EventBridge Scheduler retorna schedule válido com expressão cron
    - Mock retorna exceção (simular falha de API)
    - Mock retorna regra desabilitada (`State: "DISABLED"`)
    - Criar em `tests/test_config_handler.py` (ou adicionar ao existente)
    - _Requisitos: 6.2, 6.6, 6.7_

- [x] 9. Implementar cronHumanizer e integrar na SettingsPage (frontend)
  - [x] 9.1 Criar utility `frontend/src/utils/cronHumanizer.ts`
    - Implementar função `humanizeSchedule(expression: string): string`
    - Suportar `rate(1 day)` → "Todos os dias", `rate(N hours)` → "A cada N horas", `rate(N minutes)` → "A cada N minutos"
    - Suportar `cron(M H * * ? *)` → "Todos os dias às HH:MM"
    - Suportar `cron(M H ? * DOW *)` → dias da semana específicos
    - Suportar `cron(M H D * ? *)` → dia do mês específico
    - Retornar expressão original como fallback para padrões não reconhecidos
    - _Requisitos: 6.3, 6.4_

  - [ ]* 9.2 Escrever teste de propriedade para cronHumanizer
    - **Property 5: Humanizer de schedule EventBridge produz texto pt-BR válido**
    - Para qualquer expressão de agendamento válida do EventBridge (rate ou cron), `humanizeSchedule` produz string não-vazia. Se a expressão contém horário fixo, a saída inclui o componente de horário no formato `HH:MM`.
    - Criar `frontend/src/utils/__tests__/cronHumanizer.test.ts` usando `fast-check`
    - **Valida: Requisitos 6.3, 6.4**

  - [ ]* 9.3 Escrever testes unitários para cronHumanizer
    - `rate(1 day)` → "Todos os dias"
    - `cron(59 23 * * ? *)` → "Todos os dias às 23:59"
    - `cron(0 0 * * ? *)` → "Todos os dias às 00:00"
    - `rate(2 hours)` → "A cada 2 horas"
    - Expressão desconhecida → retorna expressão original como fallback
    - _Requisitos: 6.3, 6.4_

  - [x] 9.4 Adicionar tipo `EtlSchedule` e integrar na SettingsPage
    - Adicionar interface `EtlSchedule` em `frontend/src/types/index.ts` com campos `expression`, `enabled`, `humanReadable`, `error?`
    - Adicionar state `schedule` na SettingsPage
    - Fazer fetch de `GET /api/config/schedule` junto com o config existente
    - Exibir campo "Agendamento" dentro do container "Status do ETL" (ColumnLayout existente, agora com 5 colunas)
    - Exibir "Agendamento indisponível" com `StatusIndicator type="warning"` em caso de erro
    - Exibir "Agendamento desabilitado" com `StatusIndicator type="stopped"` quando regra desabilitada
    - Exibir texto legível do `humanReadable` quando tudo ok
    - _Requisitos: 6.1, 6.5, 6.6, 6.7_

- [x] 10. Checkpoint final — Verificar tudo
  - Garantir que o build frontend compila sem erros (`tsc -b && vite build`)
  - Garantir que todos os testes frontend passam (`vitest --run`)
  - Garantir que todos os testes backend passam (`pytest`)
  - Perguntar ao usuário se há dúvidas

## Notas

- Tasks marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada task referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Testes de propriedade validam propriedades universais de corretude (fast-check)
- Testes unitários validam exemplos específicos e edge cases
- O frontend usa TypeScript + React 19 + Cloudscape; o backend usa Python 3.13 + Lambda
