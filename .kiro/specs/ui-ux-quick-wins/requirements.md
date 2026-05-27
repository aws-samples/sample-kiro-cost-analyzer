# Documento de Requisitos — Quick Wins UI/UX (M1–M6)

## Introdução

Este documento especifica os requisitos para as seis melhorias rápidas (Quick Wins) identificadas na análise UI/UX do Kiro Cost Analyzer. As melhorias cobrem: período padrão de 30 dias, extração de componente reutilizável de DateRangePicker, timestamp de última atualização, correção do export CSV, branding na página de login e exibição do agendamento do ETL na página de configurações. Todas as melhorias visam resolver problemas concretos de usabilidade com esforço mínimo de implementação.

## Glossário

- **Dashboard**: Página principal da aplicação (`DashboardPage`) que exibe resumo de uso, filtros e tabela de usuários.
- **AccountUsagePage**: Página de consumo da conta que exibe totais, timeline e breakdowns por tier e tipo de cliente.
- **UserDetailPage**: Página de detalhes de um usuário específico com gráficos de uso diário, distribuição e prompts recentes.
- **LoginPage**: Página de autenticação onde o usuário insere email e senha para acessar a aplicação.
- **LocalizedDateRangePicker**: Componente reutilizável e agnóstico de locale que encapsula o `DateRangePicker` do Cloudscape com strings i18n configuráveis, opções relativas padrão e validação. Atualmente configurado com strings em pt-BR, mas a arquitetura do componente não está vinculada a nenhum idioma específico.
- **Período_Padrão**: Valor inicial do seletor de período, configurado como "Últimos 30 dias" (tipo relativo, 30 dias).
- **Timestamp_Atualização**: Texto exibido no header da página indicando o horário da última carga de dados bem-sucedida, no formato "Última atualização: HH:mm".
- **Export_Handler**: Função do backend que serializa dados de uso em formato CSV ou JSON.
- **API_Client**: Módulo frontend (`api/client.ts`) responsável por fazer requisições HTTP ao backend.
- **SettingsPage**: Página de configurações da aplicação que exibe configurações de bucket, prefixos, Identity Store ID, status do ETL e agendamento do ETL.
- **ETL_Schedule**: Agendamento de execução automática do pipeline ETL, definido por uma regra do Amazon EventBridge com expressão cron. O valor padrão é `cron(59 23 * * ? *)` (todos os dias às 23:59). Exibido na SettingsPage em formato legível em pt-BR (ex: "Todos os dias às 23:59").
- **Schedule_Endpoint**: Endpoint do backend (`GET /api/config/schedule`) que consulta a regra do EventBridge e retorna a expressão de agendamento do ETL.
- **Cron_Humanizer**: Lógica que converte uma expressão cron ou rate do EventBridge em texto legível em pt-BR para exibição ao usuário.

## Requisitos

### Requisito 1: Período padrão "Últimos 30 dias"

**User Story:** Como administrador, eu quero que o seletor de período inicie com "Últimos 30 dias" selecionado, para que eu veja dados relevantes imediatamente ao abrir qualquer página sem precisar selecionar um período manualmente.

#### Critérios de Aceitação

1. WHEN o Dashboard é carregado pela primeira vez, THE Dashboard SHALL exibir o DateRangePicker com o valor "Últimos 30 dias" pré-selecionado.
2. WHEN a AccountUsagePage é carregada pela primeira vez, THE AccountUsagePage SHALL exibir o DateRangePicker com o valor "Últimos 30 dias" pré-selecionado.
3. WHEN a UserDetailPage é carregada pela primeira vez, THE UserDetailPage SHALL exibir o DateRangePicker com o valor "Últimos 30 dias" pré-selecionado.
4. WHEN o Período_Padrão está ativo, THE Dashboard SHALL enviar os parâmetros `startDate` e `endDate` correspondentes aos últimos 30 dias na requisição à API.
5. WHEN o usuário limpa o seletor de período, THE Dashboard SHALL permitir a busca sem filtro de data.

### Requisito 2: Componente reutilizável LocalizedDateRangePicker

**User Story:** Como desenvolvedor, eu quero um componente reutilizável e agnóstico de locale que encapsule o DateRangePicker com strings i18n configuráveis, para que eu não precise duplicar ~40 linhas de configuração em cada página e possa reutilizar o componente independentemente do idioma.

#### Critérios de Aceitação

1. THE LocalizedDateRangePicker SHALL encapsular todas as strings i18n atualmente duplicadas nas páginas Dashboard, AccountUsagePage e UserDetailPage, com as strings em pt-BR configuradas como padrão.
2. THE LocalizedDateRangePicker SHALL aceitar as props `value` e `onChange` para controle externo do valor selecionado.
3. THE LocalizedDateRangePicker SHALL aceitar uma prop opcional `placeholder` com valor padrão "Selecione o período".
4. THE LocalizedDateRangePicker SHALL incluir as opções relativas padrão: 7 dias, 30 dias e 90 dias.
5. THE LocalizedDateRangePicker SHALL validar que, em ranges absolutos, a data inicial seja anterior à data final.
6. THE LocalizedDateRangePicker SHALL ter um nome de componente e interface de props que não referenciem nenhum locale específico, permitindo reutilização futura com outros idiomas.
7. WHEN o LocalizedDateRangePicker é utilizado no Dashboard, THE Dashboard SHALL manter o mesmo comportamento visual e funcional que a implementação atual.
8. WHEN o LocalizedDateRangePicker é utilizado na AccountUsagePage, THE AccountUsagePage SHALL manter o mesmo comportamento visual e funcional que a implementação atual.
9. WHEN o LocalizedDateRangePicker é utilizado na UserDetailPage, THE UserDetailPage SHALL manter o mesmo comportamento visual e funcional que a implementação atual.

### Requisito 3: Timestamp de última atualização

**User Story:** Como administrador, eu quero ver o horário da última atualização dos dados, para que eu saiba se estou olhando informações recentes após clicar em "Atualizar".

#### Critérios de Aceitação

1. WHEN uma carga de dados é concluída com sucesso no Dashboard, THE Dashboard SHALL exibir o texto "Última atualização: HH:mm" no header da página.
2. WHEN uma carga de dados é concluída com sucesso na AccountUsagePage, THE AccountUsagePage SHALL exibir o texto "Última atualização: HH:mm" no header da página.
3. WHEN uma carga de dados é concluída com sucesso na UserDetailPage, THE UserDetailPage SHALL exibir o texto "Última atualização: HH:mm" no header da página.
4. WHEN o usuário clica em "Atualizar" e a carga é bem-sucedida, THE Timestamp_Atualização SHALL ser atualizado para o horário corrente.
5. IF a carga de dados falha, THEN THE Timestamp_Atualização SHALL manter o valor anterior sem alteração.
6. THE Timestamp_Atualização SHALL exibir o horário no formato 24h localizado em pt-BR (ex: "14:35").

### Requisito 4: Correção do export CSV

**User Story:** Como administrador, eu quero exportar dados de uso em formato CSV válido, para que eu possa abrir o arquivo em planilhas sem corrupção de dados.

#### Critérios de Aceitação

1. WHEN o usuário solicita export no formato CSV, THE Dashboard SHALL gerar um arquivo CSV válido que pode ser aberto em aplicações de planilha.
2. WHEN o backend retorna dados CSV como string, THE Dashboard SHALL usar a string diretamente no Blob sem aplicar `JSON.stringify`.
3. WHEN o usuário solicita export no formato JSON, THE Dashboard SHALL aplicar `JSON.stringify` ao conteúdo da resposta antes de criar o Blob.
4. WHEN o export CSV é concluído, THE Dashboard SHALL iniciar o download de um arquivo com extensão `.csv` e content-type `text/csv`.
5. WHEN o export JSON é concluído, THE Dashboard SHALL iniciar o download de um arquivo com extensão `.json` e content-type `application/json`.
6. IF o export falha, THEN THE Dashboard SHALL exibir a mensagem de erro "Erro ao exportar dados" em um Alert dismissível.

### Requisito 5: Branding na página de login

**User Story:** Como usuário, eu quero ver a identidade visual da aplicação na página de login, para que eu saiba que estou acessando o Kiro Cost Analyzer e tenha uma primeira impressão profissional.

#### Critérios de Aceitação

1. THE LoginPage SHALL exibir o logotipo da aplicação acima do formulário de login.
2. THE LoginPage SHALL exibir o título "Kiro Cost Analyzer" abaixo do logotipo.
3. THE LoginPage SHALL exibir uma tagline descritiva abaixo do título (ex: "Monitoramento de custos e uso de IA").
4. THE LoginPage SHALL carregar a imagem do logotipo a partir do arquivo `docs/logo.png` importado como asset estático.
5. THE LoginPage SHALL centralizar verticalmente e horizontalmente o bloco de branding + formulário na viewport.
6. WHEN a imagem do logotipo falha ao carregar, THE LoginPage SHALL exibir o título "Kiro Cost Analyzer" sem a imagem, mantendo o layout funcional.


### Requisito 6: Exibição do agendamento do ETL na SettingsPage

**User Story:** Como administrador, eu quero ver o agendamento de execução automática do ETL na página de configurações, para que eu saiba quando a próxima execução ocorrerá sem precisar consultar o console da AWS.

#### Critérios de Aceitação

1. WHEN a SettingsPage é carregada, THE SettingsPage SHALL exibir o agendamento do ETL em formato legível em pt-BR dentro do container "Status do ETL".
2. THE Schedule_Endpoint SHALL consultar a regra do EventBridge associada à state machine do ETL e retornar a expressão de agendamento.
3. WHEN o Schedule_Endpoint retorna uma expressão do tipo `rate(1 day)`, THE Cron_Humanizer SHALL converter para o texto "Todos os dias" em pt-BR.
4. WHEN o Schedule_Endpoint retorna uma expressão cron com horário fixo (ex: `cron(59 23 * * ? *)`), THE Cron_Humanizer SHALL converter para texto legível incluindo o horário (ex: "Todos os dias às 23:59").
5. THE SettingsPage SHALL exibir o agendamento do ETL como informação somente leitura, sem permitir edição pelo usuário.
6. IF o Schedule_Endpoint falha ao consultar o EventBridge, THEN THE SettingsPage SHALL exibir o texto "Agendamento indisponível" no lugar do horário.
7. IF a regra do EventBridge está desabilitada, THEN THE SettingsPage SHALL exibir o texto "Agendamento desabilitado" com um StatusIndicator do tipo "stopped".
8. THE Schedule_Endpoint SHALL retornar a expressão original do EventBridge junto com a versão legível, permitindo que o frontend exiba ambas se necessário.
