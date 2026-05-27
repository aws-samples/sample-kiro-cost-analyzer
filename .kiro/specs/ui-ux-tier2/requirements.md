# Documento de Requisitos — Melhorias UI/UX Tier 2

## Introdução

Este documento especifica os requisitos para cinco melhorias de experiência do usuário (Tier 2) no Kiro Cost Analyzer. As melhorias abordam problemas identificados na análise UI/UX (M6, M7, M8, M9, M11) e visam tornar o dashboard mais legível, responsivo e profissional, sem alterar a lógica de negócio existente.

## Glossário

- **DailyUsageChart**: Componente React que renderiza o gráfico de linha de consumo diário (créditos e interações) na página de detalhes do usuário.
- **RecentPromptsTable**: Componente React que exibe a tabela de prompts recentes na página de detalhes do usuário.
- **Drawer**: Painel lateral deslizante do Cloudscape Design System que se abre pela direita da tela para exibir conteúdo contextual sem alterar o layout da página principal.
- **Skeleton_Loading**: Padrão de carregamento que exibe placeholders visuais com a forma aproximada do conteúdo final, em vez de spinners genéricos.
- **StatusIndicator**: Componente do Cloudscape que exibe um ícone colorido com texto para representar estados como sucesso, erro, aviso ou informação.
- **SideNavigation**: Componente de navegação lateral do Cloudscape usado no AppLayout para navegar entre as páginas da aplicação.
- **Divider**: Elemento visual de separação (tipo `divider`) suportado pelo SideNavigation do Cloudscape para agrupar itens de menu.
- **ETL_Status**: Informação operacional sobre a última execução do pipeline de extração, transformação e carga de dados, disponível via endpoint `GET /api/config`.
- **Créditos**: Unidade de consumo do Kiro com valores decimais pequenos (ex: 0.5, 1.2, 3.8).
- **Interações**: Contagem inteira de interações do usuário com o Kiro, tipicamente na ordem de dezenas a centenas (ex: 50, 200).

## Requisitos

### Requisito 1: Separar gráficos de créditos e interações (M6)

**User Story:** Como administrador, eu quero visualizar créditos e interações em gráficos separados, para que ambas as métricas sejam legíveis independentemente da diferença de escala entre elas.

#### Critérios de Aceitação

1. WHEN a página de detalhes do usuário exibe dados de consumo diário, THE DailyUsageChart SHALL renderizar dois gráficos de linha distintos: um para Créditos e outro para Interações.
2. THE DailyUsageChart SHALL exibir o gráfico de Créditos com eixo Y dimensionado exclusivamente para valores de créditos (escala decimal).
3. THE DailyUsageChart SHALL exibir o gráfico de Interações com eixo Y dimensionado exclusivamente para valores de interações (escala inteira).
4. WHEN os dados de consumo diário estão vazios, THE DailyUsageChart SHALL exibir uma mensagem de estado vazio para cada gráfico.
5. THE DailyUsageChart SHALL manter o eixo X (Data) sincronizado entre os dois gráficos, exibindo o mesmo intervalo de datas.
6. WHEN o componente recebe dados válidos, THE DailyUsageChart SHALL preservar todos os pontos de dados originais sem perda de informação (propriedade de preservação de dados: a quantidade de pontos no gráfico de Créditos e no gráfico de Interações é igual à quantidade de entradas em `dailyUsage`).

### Requisito 2: Drawer lateral para detalhes de prompt (M7)

**User Story:** Como administrador, eu quero visualizar os detalhes de um prompt em um painel lateral, para que o layout da tabela de prompts recentes permaneça estável e eu possa ler o conteúdo completo sem distorção visual.

#### Critérios de Aceitação

1. WHEN o usuário clica em uma linha da tabela de prompts recentes, THE RecentPromptsTable SHALL abrir um Drawer lateral pela direita exibindo os detalhes do prompt selecionado.
2. THE Drawer SHALL exibir o timestamp formatado, o modelo, o tipo de trigger, o conteúdo do prompt e o conteúdo da resposta do prompt selecionado.
3. WHILE o Drawer está aberto, THE RecentPromptsTable SHALL manter o layout da tabela inalterado, sem deslocamento de linhas ou colunas.
4. WHEN o usuário clica no botão de fechar do Drawer, THE RecentPromptsTable SHALL fechar o Drawer e retornar ao estado inicial.
5. WHILE os detalhes do prompt estão sendo carregados da API, THE Drawer SHALL exibir um indicador de carregamento.
6. IF a requisição de detalhes do prompt falhar, THEN THE Drawer SHALL exibir uma mensagem de erro descritiva.
7. WHEN o usuário clica em outra linha da tabela enquanto o Drawer está aberto, THE RecentPromptsTable SHALL atualizar o conteúdo do Drawer com os detalhes do novo prompt selecionado.

### Requisito 3: Skeleton loading em vez de spinners genéricos (M8)

**User Story:** Como administrador, eu quero ver placeholders visuais que representam a forma do conteúdo durante o carregamento, para que a transição entre estado de carregamento e conteúdo final seja suave e previsível.

#### Critérios de Aceitação

1. WHILE os dados da DashboardPage estão sendo carregados pela primeira vez, THE DashboardPage SHALL exibir Skeleton_Loading com a forma aproximada dos cards de resumo e da tabela de usuários.
2. WHILE os dados da AccountUsagePage estão sendo carregados pela primeira vez, THE AccountUsagePage SHALL exibir Skeleton_Loading com a forma aproximada dos cards de totais, do gráfico de timeline e dos gráficos de breakdown.
3. WHILE os dados da UserDetailPage estão sendo carregados pela primeira vez, THE UserDetailPage SHALL exibir Skeleton_Loading com a forma aproximada dos cards de resumo, dos gráficos e da tabela de prompts.
4. WHILE os dados da SettingsPage estão sendo carregados pela primeira vez, THE SettingsPage SHALL exibir Skeleton_Loading com a forma aproximada dos containers de configuração e do status do ETL.
5. THE Skeleton_Loading SHALL substituir os componentes Spinner genéricos e as mensagens de texto "Carregando..." utilizados atualmente.
6. WHEN os dados terminam de carregar, THE Skeleton_Loading SHALL ser substituído pelo conteúdo real sem mudança brusca de layout (a área ocupada pelo skeleton é similar à área do conteúdo final).

### Requisito 4: Link de status do ETL no header do Dashboard (M9)

**User Story:** Como administrador, eu quero ver o status atual do ETL diretamente no header do Dashboard, para que eu saiba rapidamente se os dados exibidos estão atualizados sem precisar navegar até a página de Configurações.

#### Critérios de Aceitação

1. WHEN a DashboardPage é carregada, THE DashboardPage SHALL buscar o status do ETL via endpoint `GET /api/config` e exibir um StatusIndicator compacto no header da página.
2. THE StatusIndicator SHALL exibir o texto "ETL: Sucesso" com ícone de sucesso quando o status do ETL for "success".
3. WHEN o status do ETL for "error" ou "failed", THE StatusIndicator SHALL exibir o texto "ETL: Erro" com ícone de erro.
4. WHEN o status do ETL for "running" ou "in_progress", THE StatusIndicator SHALL exibir o texto "ETL: Em execução" com ícone informativo.
5. WHEN não houver execução registrada do ETL, THE StatusIndicator SHALL exibir o texto "ETL: Sem execução" com ícone de parado.
6. WHEN o usuário clica no StatusIndicator do ETL, THE DashboardPage SHALL navegar o usuário para a página de Configurações (`/settings`).
7. IF a requisição de status do ETL falhar, THEN THE DashboardPage SHALL omitir o StatusIndicator sem exibir erro, mantendo o header funcional.

### Requisito 5: Divider na navegação lateral separando grupos de menu (M11)

**User Story:** Como administrador, eu quero que os itens de navegação lateral estejam visualmente agrupados, para que eu identifique rapidamente a separação entre itens principais (Dashboard, Consumo da Conta) e itens administrativos (Usuários, Configurações).

#### Critérios de Aceitação

1. THE SideNavigation SHALL exibir os itens na seguinte ordem: Dashboard, Consumo da Conta, Divider, Usuários, Configurações.
2. THE SideNavigation SHALL renderizar um Divider visual entre "Consumo da Conta" e "Usuários".
3. THE SideNavigation SHALL posicionar "Usuários" antes de "Configurações" no grupo administrativo.
4. WHEN o usuário navega entre as páginas, THE SideNavigation SHALL manter o item ativo destacado corretamente independentemente do grupo em que se encontra.
