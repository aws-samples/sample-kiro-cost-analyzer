# Plano de Implementação: Kiro Cost Analyzer

## Visão Geral

Implementação incremental de uma aplicação serverless composta por ETL Lambda (Python 3.12), API Backend Lambda (Python 3.12), e Dashboard React/Cloudscape. A camada analítica usa S3 Parquet + Glue Catalog + Athena. Infraestrutura definida via AWS SAM. Linguagem de implementação: **Python** (backend/ETL) e **TypeScript** (frontend React).

## Tasks

- [x] 1. Estrutura do projeto e template SAM base
  - [x] 1.1 Criar estrutura de diretórios do projeto
    - Criar diretórios: `etl/`, `backend/`, `frontend/`, `tests/`, `template.yaml`
    - Criar `etl/requirements.txt` com dependências (boto3, pyarrow, awswrangler)
    - Criar `backend/requirements.txt` com dependências (boto3)
    - Inicializar projeto frontend com Vite + React + TypeScript + Cloudscape
    - _Requisitos: 1.1_

  - [x] 1.2 Criar template SAM com recursos base
    - Definir `Parameters`: StackName, SourceBucketName, SourcePrefix, AdminEmail, EtlScheduleExpression
    - Criar recursos: `CognitoUserPool`, `CognitoUserPoolClient` (SPA, PKCE), `CognitoUserPoolDomain`
    - Criar `DataBucket` (S3 para Parquet), `WebsiteBucket` (S3 para SPA)
    - Criar `ProcessedFilesTable` (DynamoDB) com PK=fileKey (String)
    - Criar `GlueDatabase` (kiro_usage), `GlueActivityTable` (activity — schema Parquet com partition keys year/month)
    - Criar `AthenaWorkgroup` (kiro-cost-analyzer, output no DataBucket/athena-results/)
    - Criar parâmetros SSM: `/kiro-cost-analyzer/bucket-name`, `/kiro-cost-analyzer/source-prefix`, `/kiro-cost-analyzer/etl-status`
    - Criar `ApiGateway` (AWS::Serverless::Api com CognitoAuthorizer)
    - Definir `EtlFunction` e `BackendFunction` como AWS::Serverless::Function (Python 3.12)
    - Definir evento ScheduleV2 no EtlFunction com expressão configurável
    - Definir roles IAM com permissões mínimas para cada Lambda
    - _Requisitos: 1.1, 1.2, 1.3, 1.5, 6.2, 6.7_

  - [x] 1.3 Criar Custom Resource para criação do admin user no Cognito
    - Criar `AdminUserCreatorFunction` (Lambda Python) que executa `admin_create_user` no Cognito
    - Registrar como Custom Resource no template SAM, recebendo AdminEmail como parâmetro
    - O admin user deve ser criado com grupo/role de administrador
    - _Requisitos: 1.4, 2.2_

- [x] 2. Checkpoint — Validar template SAM
  - Executar `sam validate` para garantir que o template é válido
  - Verificar que todos os recursos estão definidos corretamente
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Componente ETL — Módulos de leitura e parsing
  - [x] 3.1 Implementar `etl/config.py` — leitura de configuração
    - Ler parâmetros do Parameter Store: bucket-name, source-prefix
    - Retornar dataclass `EtlConfig` com bucket_name e source_prefix
    - _Requisitos: 3.3, 3.4_

  - [x] 3.2 Implementar `etl/s3_reader.py` — navegação no bucket de origem
    - Função `list_csv_files(bucket, prefix)` que lista CSVs recursivamente nos sub-caminhos `by_user_analytic/` e `user_report/`
    - Filtrar apenas arquivos `.csv`, ignorar UUIDs soltos e outros paths
    - Função `read_csv_content(bucket, key)` que retorna o conteúdo do CSV como string
    - _Requisitos: 4.2_

  - [x] 3.3 Implementar `etl/path_resolver.py` — extração de metadados do path S3
    - Função `resolve_path_metadata(s3_key, source_prefix)` que extrai format_type, region, year, month, day, account_id, client_type
    - Suportar paths de `by_user_analytic/` (legado) e `user_report/` (novo)
    - Retornar `None` para paths não reconhecidos
    - _Requisitos: 4.2, 4.4_

  - [x] 3.4 Implementar `etl/csv_parser.py` — parsing com detecção de formato
    - Detecção de formato em duas camadas: path S3 (primário) + header CSV (validação)
    - Parsing do Formato Novo: extrair todos os campos diretamente
    - Parsing do Formato Legado: mapear `Chat_MessagesSent` → `totalMessages`, campos ausentes com defaults
    - Ignorar arquivos vazios ou com apenas header (sem erro)
    - Log de erro descritivo para formatos desconhecidos (colunas esperadas vs encontradas)
    - Combinar registros de múltiplos arquivos part (part_1, part_2, etc.)
    - _Requisitos: 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4_

  - [ ]* 3.5 Escrever teste de propriedade — Parsing e normalização de CSV (Property 1)
    - **Property 1: Parsing e normalização de CSV preserva dados**
    - Gerar CSVs válidos nos formatos Novo e Legado com `hypothesis`
    - Verificar que parsing + normalização produz `UserActivityRecord` com todos os campos corretos
    - No Formato Legado: `Chat_MessagesSent` → `totalMessages`, campos ausentes → defaults
    - **Valida: Requisitos 4.3, 4.4, 5.1, 5.2, 5.3, 5.4**

  - [ ]* 3.6 Escrever teste de propriedade — Identificação de arquivos novos (Property 2)
    - **Property 2: Identificação de arquivos novos**
    - Gerar conjuntos de S3 keys e conjuntos de keys já processadas
    - Verificar que a diferença retornada é exata (sem omissões, sem inclusões indevidas)
    - **Valida: Requisito 4.2**

  - [ ]* 3.7 Escrever teste de propriedade — Combinação de arquivos part (Property 3)
    - **Property 3: Combinação de arquivos part**
    - Gerar listas de listas de registros (simulando parts)
    - Verificar que a combinação tem tamanho = soma dos tamanhos individuais, sem duplicação/perda
    - **Valida: Requisito 4.7**

- [x] 4. Componente ETL — Escrita Parquet e controle de processamento
  - [x] 4.1 Implementar `etl/normalizer.py` — normalização para estrutura comum
    - Dataclass `UserActivityRecord` com todos os campos da estrutura comum
    - Função `normalize_records(raw_records, format_type, path_metadata)` que retorna lista de `UserActivityRecord`
    - Aplicar mapeamento legado → comum conforme tabela do design
    - _Requisitos: 5.3_

  - [x] 4.2 Implementar `etl/parquet_writer.py` — escrita Parquet particionado no S3
    - Função `write_parquet(records, data_bucket)` que agrupa registros por year/month e grava Parquet no S3
    - Usar `pyarrow` ou `awswrangler` para escrita Parquet
    - Estrutura de particionamento: `activity/year=YYYY/month=MM/`
    - Sobrescrever partição existente para evitar duplicação
    - _Requisitos: 6.1, 6.5, 6.6_

  - [x] 4.3 Implementar `etl/processing_tracker.py` — controle via DynamoDB
    - Função `get_processed_keys(table)` que retorna set de S3 keys já processadas
    - Função `mark_as_processed(table, key, record_count, status)` que registra no DynamoDB
    - Função `filter_new_files(all_keys, processed_keys)` que retorna apenas arquivos novos
    - _Requisitos: 4.2, 4.9, 6.7_

  - [x] 4.4 Implementar `etl/handler.py` — entry point Lambda ETL
    - Orquestrar o fluxo completo: config → list files → filter new → parse → normalize → write parquet → mark processed
    - Registrar status da execução no Parameter Store (`etl-status`) com JSON
    - Tratamento de erros conforme tabela do design (retry com backoff, logs, continuar em erros parciais)
    - _Requisitos: 4.1, 4.2, 4.8, 4.9_

  - [ ]* 4.5 Escrever teste de propriedade — Particionamento Parquet (Property 4)
    - **Property 4: Particionamento Parquet por ano/mês**
    - Gerar listas de registros com datas variadas
    - Verificar que o agrupamento por year/month é correto e a união de todas as partições = registros originais
    - **Valida: Requisitos 6.1, 6.5**

  - [ ]* 4.6 Escrever testes unitários do ETL
    - Testar `path_resolver` com paths legado, novo e inválido
    - Testar `csv_parser` com CSV de 1 linha, campos entre aspas, arquivo vazio
    - Testar `normalizer` com registro legado completo e com campos ausentes
    - Testar `processing_tracker.filter_new_files` com conjuntos variados
    - _Requisitos: 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.4_

- [x] 5. Checkpoint — Validar ETL
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Lambda Backend — Endpoints de consulta via Athena
  - [x] 6.1 Implementar módulo `backend/athena_client.py` — cliente Athena
    - Função `execute_query(sql, workgroup, output_location)` que executa `StartQueryExecution`, faz polling com `GetQueryExecution`, e retorna resultados via `GetQueryResults`
    - Tratamento de timeout e erros de query
    - _Requisitos: 6.3, 6.4_

  - [x] 6.2 Implementar endpoint `GET /api/usage` — consumo por usuário
    - Construir query SQL Athena com filtros opcionais: startDate, endDate, subscriptionTier, clientType, overageOnly
    - Agregar por userId: totalCredits, overageCredits, totalMessages, totalConversations, averageDailyCredits
    - Retornar JSON com `summary` (totalUsers, totalCredits, totalOverageCredits, averageCreditsPerUser) e `users` (lista ordenada por totalCredits DESC)
    - Usar partições year/month para otimizar scan
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 9.3_

  - [x] 6.3 Implementar endpoint `GET /api/usage/account` — consumo total da conta
    - Construir queries Athena para: totais da conta, evolução temporal (por granularidade), breakdown por tier, breakdown por clientType
    - Query parameters: startDate, endDate, granularity (day/week/month)
    - Retornar JSON com `totals`, `timeline`, `breakdownByTier`, `breakdownByClientType`
    - _Requisitos: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 6.4 Implementar endpoint `GET /api/usage/export` — exportação CSV/JSON
    - Reutilizar lógica de `/api/usage` para obter dados
    - Serializar para CSV (com header) ou JSON conforme parâmetro `format`
    - Retornar com Content-Type apropriado
    - _Requisitos: 9.9, 12.1, 12.2_

  - [ ]* 6.5 Escrever testes de propriedade — Agregação e filtragem (Properties 5–9)
    - **Property 5: Agregação de consumo por usuário** — soma de creditsUsed, overageCreditsUsed, totalMessages, chatConversations por userId; averageDailyCredits = totalCredits / datas distintas
    - **Property 6: Filtragem por intervalo de datas** — retorna exatamente registros dentro do range [startDate, endDate] inclusivo
    - **Property 7: Ordenação por créditos decrescente** — cada elemento tem totalCredits >= próximo
    - **Property 8: Filtragem por overage** — retorna apenas usuários com overageCredits > 0
    - **Property 9: Cálculo do resumo geral** — totalUsers = len(lista), totalCredits = soma, averageCreditsPerUser = totalCredits/totalUsers
    - **Valida: Requisitos 7.1–7.5, 9.3, 9.7, 9.8**

  - [ ]* 6.6 Escrever testes de propriedade — Account-level (Properties 10–12)
    - **Property 10: Agregação account-level** — soma de todos os campos = soma dos agregados individuais
    - **Property 11: Breakdown preserva totais** — soma dos breakdowns por tier = total da conta; idem por clientType
    - **Property 12: Evolução temporal preserva totais** — soma dos períodos na timeline = total da conta
    - **Valida: Requisitos 8.1–8.7**

  - [ ]* 6.7 Escrever testes de propriedade — Round-trip (Properties 13–14)
    - **Property 13: Round-trip CSV** — serializar → parse → resultado equivalente ao original
    - **Property 14: Round-trip JSON** — serializar → parse → resultado equivalente ao original
    - **Valida: Requisitos 12.1–12.4**

- [x] 7. Lambda Backend — Endpoints de configuração e gestão
  - [x] 7.1 Implementar endpoint `GET /api/config` — obter configuração atual
    - Ler bucket-name, source-prefix e etl-status do Parameter Store
    - Retornar JSON com configuração e status da última execução ETL
    - _Requisitos: 11.1, 11.3_

  - [x] 7.2 Implementar endpoint `PUT /api/config/bucket` — atualizar bucket de origem
    - Validar acesso ao bucket (HeadBucket) antes de salvar
    - Salvar bucket-name e source-prefix no Parameter Store
    - Retornar status de validação
    - _Requisitos: 3.1, 3.2, 3.5, 11.2_

  - [x] 7.3 Implementar endpoint `POST /api/etl/trigger` — Executar ETL manual
    - Invocar a Lambda ETL de forma assíncrona (`InvocationType='Event'`)
    - Retornar status `triggered` com ARN da execução
    - _Requisitos: 11.4_

  - [x] 7.4 Implementar endpoints de gestão de usuários Cognito
    - `GET /api/users` — listar usuários com `list_users` do Cognito
    - `POST /api/users` — criar usuário com `admin_create_user` (enviar convite por email)
    - `DELETE /api/users/{userId}` — desativar usuário com `admin_disable_user`
    - Validar que admin não pode remover a si mesmo
    - _Requisitos: 2.3, 2.4, 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 7.5 Implementar `backend/handler.py` — entry point Lambda Backend (router)
    - Rotear requests por método HTTP + path para os handlers corretos
    - Extrair e validar JWT claims (userId, groups) do evento API Gateway
    - Verificar role admin para endpoints restritos
    - Tratamento de erros com HTTP status codes conforme tabela do design
    - _Requisitos: 2.6_

  - [ ]* 7.6 Escrever testes unitários do Backend
    - Testar cada endpoint com request válido e com parâmetros inválidos
    - Testar validação de JWT e verificação de role admin
    - Testar tratamento de erros (bucket inacessível, self-removal, email duplicado)
    - Testar serialização CSV e JSON do export
    - _Requisitos: 2.6, 3.5, 10.5, 12.1, 12.2_

- [x] 8. Checkpoint — Validar Backend
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Frontend — Estrutura base e autenticação
  - [x] 9.1 Configurar projeto React com Vite, TypeScript e Cloudscape
    - Instalar dependências: `@cloudscape-design/components`, `@cloudscape-design/global-styles`, `react-router-dom`
    - Configurar Vite com proxy para API em desenvolvimento
    - Criar `src/types/index.ts` com tipos TypeScript compartilhados (UserUsage, AccountUsage, EtlStatus, etc.)
    - _Requisitos: 9.1_

  - [x] 9.2 Implementar autenticação Cognito no frontend
    - Criar `src/auth/AuthProvider.tsx` com context de autenticação
    - Criar `src/auth/useAuth.ts` hook para acessar estado de auth e tokens
    - Implementar fluxo PKCE: redirect para Cognito Hosted UI → callback com authorization code → troca por tokens
    - Armazenar tokens no localStorage, redirect para login quando expirado
    - _Requisitos: 2.1, 2.5_

  - [x] 9.3 Implementar layout principal e navegação
    - Criar `src/App.tsx` com React Router e AuthProvider
    - Usar `AppLayout` + `SideNavigation` do Cloudscape com menu: Dashboard, Consumo da Conta, Configurações, Usuários
    - Criar `src/api/client.ts` — cliente HTTP com token JWT no header Authorization
    - _Requisitos: 9.1_

- [x] 10. Frontend — Páginas do Dashboard
  - [x] 10.1 Implementar `DashboardPage.tsx` — tabela de consumo por usuário
    - Componente `UsageTable` com Cloudscape `Table` (sortable, filterable)
    - Colunas: UserId, SubscriptionTier, Total Créditos, Créditos Overage, Total Mensagens, Total Conversas, Média Diária
    - Ordenação padrão por Total Créditos DESC
    - Componente `SummaryCards` com cards: total usuários, soma créditos, soma overage, média por usuário
    - _Requisitos: 9.2, 9.3, 9.8_

  - [x] 10.2 Implementar filtros do Dashboard
    - `DateRangeFilter` com Cloudscape `DateRangePicker` para período
    - `TierFilter` com `Select` para subscription tier (PRO, PRO_PLUS, POWER)
    - `ClientTypeFilter` com `Select` para tipo de cliente (KIRO_IDE, KIRO_CLI, PLUGIN)
    - `Toggle` para filtro de overage only
    - `ExportButton` com opções CSV/JSON
    - Integrar filtros com chamada à API `/api/usage`
    - _Requisitos: 9.4, 9.5, 9.6, 9.7, 9.9_

  - [x] 10.3 Implementar `AccountUsagePage.tsx` — consumo total da conta
    - `AccountSummaryCards` com totais: créditos, overage, mensagens, conversas
    - `TimelineChart` com Cloudscape `LineChart` — evolução temporal
    - `GranularitySelector` com `Select` (dia/semana/mês)
    - `BreakdownCharts` com `PieChart`/`BarChart` — breakdown por tier e clientType
    - `DateRangeFilter` para período
    - Integrar com API `/api/usage/account`
    - _Requisitos: 8.8, 8.9, 8.10_

- [x] 11. Frontend — Páginas de administração
  - [x] 11.1 Implementar `SettingsPage.tsx` — configuração de parâmetros
    - Formulário com `Input` para bucket name e source prefix
    - Exibir status da última execução ETL com `StatusIndicator`
    - Botão para Executar ETL manual
    - Validação e feedback com `Alert`
    - Integrar com APIs `/api/config` e `/api/etl/trigger`
    - _Requisitos: 3.1, 11.1, 11.2, 11.3, 11.4_

  - [x] 11.2 Implementar `UsersPage.tsx` — gestão de usuários
    - Tabela de usuários com status (ativo/desativado)
    - Formulário para adicionar novo usuário (campo email)
    - Botão de remoção com confirmação
    - Impedir remoção do próprio admin (validação no frontend)
    - Integrar com APIs `/api/users`
    - _Requisitos: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 11.3 Implementar tratamento de erros no frontend
    - Interceptar respostas 401 → limpar tokens, redirect para login
    - Exibir `Alert` Cloudscape para erros 4xx com mensagem da API
    - Exibir `Alert` genérico + botão "Tentar novamente" para erros 5xx
    - Estado vazio com mensagem orientativa quando não há dados
    - _Requisitos: 2.1, 2.5_

- [x] 12. Checkpoint — Validar Frontend
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Integração final e wiring
  - [x] 13.1 Conectar frontend ao backend via API Gateway
    - Configurar variáveis de ambiente no frontend (API URL, Cognito User Pool ID, Client ID)
    - Verificar que o Cognito Authorizer valida JWT em todas as rotas
    - Testar fluxo completo: login → dashboard → filtros → export
    - _Requisitos: 2.1, 2.6_

  - [x] 13.2 Verificar template SAM completo
    - Garantir que todas as variáveis de ambiente das Lambdas estão configuradas (nomes de tabelas, buckets, parâmetros SSM, Athena workgroup)
    - Verificar permissões IAM: ETL Lambda (S3 read origem, S3 write dados, DynamoDB, SSM, Glue), Backend Lambda (Athena, S3 dados, DynamoDB, SSM, Cognito)
    - Executar `sam validate` e `sam build`
    - _Requisitos: 1.1, 1.2_

  - [ ]* 13.3 Escrever testes de integração
    - Testar fluxo ETL end-to-end com mocks (S3 → Parser → Parquet)
    - Testar endpoints da API com Athena mockado
    - Testar fluxo de autenticação
    - _Requisitos: 1.2, 2.6, 4.8_

- [x] 14. Checkpoint final
  - Ensure all tests pass, ask the user if questions arise.

## Notas

- Tasks marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada task referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Testes de propriedade validam propriedades universais de corretude definidas no design
- Testes unitários validam exemplos específicos e edge cases
- O Requisito 13 (BACKLOG) não tem tasks — será implementado em fase futura
- Linguagem de implementação: Python 3.12 (ETL + Backend), TypeScript (Frontend React)
