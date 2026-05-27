# Plano de Implementação: Melhorias UI/UX Tier 2

## Visão Geral

Implementação de cinco melhorias de experiência do usuário no frontend React/TypeScript com Cloudscape Design System. As mudanças são exclusivamente no frontend — nenhuma alteração no backend é necessária. As tarefas seguem uma ordem incremental: primeiro componentes reutilizáveis (SkeletonLoader), depois refatorações de componentes existentes (DailyUsageChart, RecentPromptsTable), seguidas de integrações nas páginas (ETL Status, SplitPanel) e finalizando com a mudança estática na navegação.

## Tarefas

- [x] 1. Criar componente SkeletonLoader reutilizável (M8)
  - [x] 1.1 Criar `frontend/src/components/SkeletonLoader.tsx` com as 5 variantes (`cards`, `table`, `chart`, `container`, `key-value`)
    - Definir tipo `SkeletonVariant` e interface `SkeletonLoaderProps` com props `variant`, `count?`, `height?`, `columns?`
    - Implementar blocos `div` com classes CSS para cada variante
    - Variante `cards`: renderizar `count` blocos retangulares em grid com `columns` colunas
    - Variante `table`: renderizar `count` linhas com blocos simulando colunas
    - Variante `chart`: renderizar bloco único com `height` pixels de altura
    - Variante `container`: renderizar bloco retangular com padding interno
    - Variante `key-value`: renderizar pares de blocos (label + valor) em `columns` colunas
    - _Requisitos: 3.5, 3.6_
  - [x] 1.2 Criar CSS do shimmer em `frontend/src/components/SkeletonLoader.css`
    - Implementar `@keyframes shimmer` com `background-position` animado
    - Usar variáveis CSS do Cloudscape (`--color-background-layout-main`, `--color-background-container-content`) para integração visual
    - Classe `.skeleton-block` com `linear-gradient`, `background-size: 200px 100%`, `animation: shimmer 1.5s ease-in-out infinite`, `border-radius: 4px`
    - _Requisitos: 3.5, 3.6_
  - [ ]* 1.3 Escrever testes unitários para SkeletonLoader
    - Testar que cada variante renderiza o número correto de blocos
    - Testar que a classe CSS `skeleton-block` está presente nos elementos
    - Testar props opcionais (`count`, `height`, `columns`)
    - _Requisitos: 3.5_

- [x] 2. Refatorar DailyUsageChart para dois gráficos separados (M6)
  - [x] 2.1 Extrair funções puras `computeYDomain` e `computeXDomain` em `frontend/src/components/DailyUsageChart.tsx`
    - `computeYDomain(values: number[]): [number, number]` — retorna `[0, Math.max(...values, 1)]`
    - `computeXDomain(data: DailyUsageEntry[]): [Date, Date] | undefined` — retorna `[new Date(data[0].date), new Date(data[data.length - 1].date)]` ou `undefined` se vazio
    - Exportar ambas as funções para uso nos testes
    - _Requisitos: 1.2, 1.3, 1.5_
  - [x] 2.2 Refatorar o componente `DailyUsageChart` para renderizar dois `LineChart` separados
    - Substituir o `LineChart` único por dois gráficos empilhados verticalmente dentro de `SpaceBetween`
    - Gráfico de Créditos: série única com `data.map(e => ({ x: new Date(e.date), y: e.credits }))`, `yDomain` via `computeYDomain(data.map(e => e.credits))`
    - Gráfico de Interações: série única com `data.map(e => ({ x: new Date(e.date), y: e.interactions }))`, `yDomain` via `computeYDomain(data.map(e => e.interactions))`
    - Ambos compartilham `xDomain` via `computeXDomain(data)`
    - Cada gráfico com `Header variant="h3"` ("Créditos" e "Interações"), envolvidos por `Header variant="h2"` ("Consumo Diário")
    - Cada gráfico com sua própria mensagem de estado vazio
    - Manter a interface `DailyUsageChartProps` inalterada
    - _Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
  - [ ]* 2.3 Escrever teste de propriedade para escalas Y independentes
    - **Propriedade 1: Escalas Y independentes por métrica**
    - Gerar arrays arbitrários de `DailyUsageEntry` com `fast-check`
    - Verificar que `computeYDomain(data.map(e => e.credits))[1]` é igual a `Math.max(...data.map(e => e.credits), 1)`
    - Verificar que `computeYDomain(data.map(e => e.interactions))[1]` é igual a `Math.max(...data.map(e => e.interactions), 1)`
    - **Valida: Requisitos 1.2, 1.3**
  - [ ]* 2.4 Escrever teste de propriedade para sincronização do eixo X
    - **Propriedade 2: Sincronização do eixo X entre gráficos**
    - Gerar arrays não-vazios de `DailyUsageEntry` com `fast-check`
    - Verificar que `computeXDomain(data)` retorna `[new Date(data[0].date), new Date(data[data.length - 1].date)]`
    - **Valida: Requisito 1.5**
  - [ ]* 2.5 Escrever teste de propriedade para preservação de dados
    - **Propriedade 3: Preservação de dados na separação dos gráficos**
    - Gerar arrays arbitrários de `DailyUsageEntry` com `fast-check`
    - Verificar que o número de pontos na série de Créditos e na série de Interações é igual ao comprimento do array de entrada
    - **Valida: Requisito 1.6**

- [x] 3. Checkpoint — Verificar testes e funcionalidade dos gráficos
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implementar SplitPanel para detalhes de prompt (M7)
  - [x] 4.1 Criar componente `PromptDetailPanel` em `frontend/src/components/PromptDetailPanel.tsx`
    - Interface `PromptDetailPanelProps { requestId: string; onClose: () => void; }`
    - Buscar detalhes via `get<PromptDetail>('/api/prompts/${requestId}')` no `useEffect`
    - Renderizar dentro de `SplitPanel` do Cloudscape com `header="Detalhes do Prompt"`
    - Exibir: timestamp formatado, modelo (`modelId`), tipo de trigger (`triggerType`), conteúdo do prompt, conteúdo da resposta
    - Estado de carregamento: `Spinner` com texto "Carregando detalhes..."
    - Estado de erro: `Alert type="error"` com mensagem descritiva
    - Conteúdo vazio: exibir "Sem conteúdo disponível" em itálico quando `prompt` ou `response` forem strings vazias
    - _Requisitos: 2.1, 2.2, 2.5, 2.6_
  - [x] 4.2 Refatorar `RecentPromptsTable` para usar callback em vez de `ExpandableSection`
    - Atualizar interface para `RecentPromptsTableProps { prompts: RecentPrompt[]; loading: boolean; onPromptSelect: (requestId: string | null) => void; selectedRequestId: string | null; }`
    - Remover estado interno de `expandedRequestId`, `promptDetail`, `detailLoading`, `detailError`
    - Remover import de `ExpandableSection`, `Spinner`, `get`, `PromptDetail`
    - Coluna "Data/Hora": renderizar como `Link` clicável que chama `onPromptSelect(item.requestId)`
    - Destacar visualmente a linha selecionada (usar `selectedItems` do Table do Cloudscape)
    - _Requisitos: 2.1, 2.3, 2.4, 2.7_
  - [x] 4.3 Integrar `SplitPanel` no `UserDetailPage`
    - Adicionar estado `selectedPromptId` com `useState<string | null>(null)`
    - Passar `onPromptSelect` e `selectedRequestId` para `RecentPromptsTable`
    - Envolver o conteúdo em `AppLayout` com prop `splitPanel` renderizando `PromptDetailPanel` quando `selectedPromptId !== null`
    - Configurar `splitPanelOpen` e `onSplitPanelToggle` para controlar abertura/fechamento
    - Ao fechar o SplitPanel, resetar `selectedPromptId` para `null`
    - _Requisitos: 2.1, 2.3, 2.4, 2.7_
  - [ ]* 4.4 Escrever teste de propriedade para completude do conteúdo do Drawer
    - **Propriedade 4: Completude do conteúdo do Drawer**
    - Gerar objetos `PromptDetail` arbitrários com `fast-check`
    - Verificar que o componente `PromptDetailPanel` renderiza timestamp, modelId, triggerType, prompt e response
    - **Valida: Requisito 2.2**
  - [ ]* 4.5 Escrever testes unitários para RecentPromptsTable e PromptDetailPanel
    - Testar que clique na linha chama `onPromptSelect` com o `requestId` correto
    - Testar estados de loading e erro no `PromptDetailPanel`
    - _Requisitos: 2.1, 2.5, 2.6_

- [x] 5. Adicionar ETL StatusIndicator no header do Dashboard (M9)
  - [x] 5.1 Implementar função pura `mapEtlStatus` e integrar no `DashboardPage`
    - Criar interface `EtlStatusDisplay { type: 'success' | 'error' | 'info' | 'stopped'; text: string; }`
    - Implementar `mapEtlStatus(status: string | null | undefined): EtlStatusDisplay` com mapeamento conforme design
    - Exportar a função para uso nos testes
    - Adicionar estado `etlStatusDisplay` com `useState<EtlStatusDisplay | null>(null)`
    - Buscar `GET /api/config` em paralelo com dados do Dashboard no `useEffect`
    - Em caso de sucesso: chamar `mapEtlStatus(resp.etlStatus.status)` e setar no estado
    - Em caso de falha: manter `etlStatusDisplay` como `null` (omitir silenciosamente)
    - Renderizar `StatusIndicator` no `actions` do `Header` envolvido por `Link` para `/settings`
    - Usar `navigate('/settings')` no `onFollow` do `Link`
    - _Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_
  - [ ]* 5.2 Escrever teste de propriedade para mapeamento de status ETL
    - **Propriedade 5: Mapeamento correto do status ETL**
    - Gerar strings arbitrárias e valores conhecidos com `fc.oneof(fc.constant('success'), fc.constant('error'), fc.constant('failed'), fc.constant('running'), fc.constant('in_progress'), fc.constant(null), fc.string())`
    - Verificar que `mapEtlStatus` retorna o tipo e texto corretos para cada caso
    - **Valida: Requisitos 4.2, 4.3, 4.4, 4.5**
  - [ ]* 5.3 Escrever testes unitários para ETL Status no Dashboard
    - Testar renderização do `StatusIndicator` no header quando status disponível
    - Testar navegação para `/settings` ao clicar
    - Testar omissão do `StatusIndicator` quando requisição falha
    - _Requisitos: 4.1, 4.6, 4.7_

- [x] 6. Checkpoint — Verificar testes e integração do SplitPanel e ETL Status
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Integrar SkeletonLoader em todas as páginas (M8)
  - [x] 7.1 Substituir spinners por `SkeletonLoader` no `DashboardPage`
    - Importar `SkeletonLoader` no `DashboardPage.tsx`
    - Quando `loading && !data`: renderizar `<SkeletonLoader variant="cards" count={4} columns={4} />` + `<SkeletonLoader variant="table" count={5} />`
    - Remover texto "Carregando..." e `Spinner` genéricos
    - _Requisitos: 3.1, 3.5_
  - [x] 7.2 Substituir spinners por `SkeletonLoader` no `AccountUsagePage`
    - Quando `loading && !data`: renderizar `<SkeletonLoader variant="cards" count={4} columns={4} />` + `<SkeletonLoader variant="chart" height={300} />` × 2
    - _Requisitos: 3.2, 3.5_
  - [x] 7.3 Substituir spinners por `SkeletonLoader` no `UserDetailPage`
    - Substituir o bloco `loading && !data` que renderiza `<Spinner size="large" />`
    - Renderizar `<SkeletonLoader variant="key-value" columns={4} />` + `<SkeletonLoader variant="chart" height={300} />` × 2 + `<SkeletonLoader variant="table" count={5} />`
    - Remover import de `Spinner` se não for mais utilizado
    - _Requisitos: 3.3, 3.5_
  - [x] 7.4 Substituir spinners por `SkeletonLoader` no `SettingsPage`
    - Adicionar estado de loading inicial e renderizar `<SkeletonLoader variant="container" />` × 3 quando `loading && !etlStatus`
    - _Requisitos: 3.4, 3.5_

- [x] 8. Adicionar Divider na SideNavigation (M11)
  - [x] 8.1 Atualizar array `NAV_ITEMS` em `frontend/src/App.tsx`
    - Reordenar itens para: Dashboard, Consumo da Conta, `{ type: 'divider' }`, Usuários, Configurações
    - Mover "Usuários" antes de "Configurações" no grupo administrativo
    - _Requisitos: 5.1, 5.2, 5.3_
  - [ ]* 8.2 Escrever testes unitários para a ordem dos itens de navegação
    - Verificar que `NAV_ITEMS` contém 5 elementos (4 links + 1 divider)
    - Verificar que o divider está na posição correta (índice 2)
    - Verificar que "Usuários" vem antes de "Configurações"
    - _Requisitos: 5.1, 5.2, 5.3_

- [x] 9. Checkpoint final — Verificar todos os testes e build
  - Executar `npm run test` no diretório `frontend/` para garantir que todos os testes passam
  - Executar `npm run build` no diretório `frontend/` para garantir que o build compila sem erros
  - Ensure all tests pass, ask the user if questions arise.

## Notas

- Tarefas marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada tarefa referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Testes de propriedade validam propriedades universais de corretude definidas no design
- Testes unitários validam exemplos específicos e edge cases
- Todas as mudanças são exclusivamente no frontend — nenhuma alteração no backend
