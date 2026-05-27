# Plano de Implementação: Ingestão de Prompts e Correlação com Atividade

## Visão Geral

Implementação incremental que estende o Kiro Cost Analyzer existente para ingerir logs de prompt `.json.gz`, correlacionar com dados de atividade via Athena, resolver nomes de usuário via IAM Identity Center, e exibir métricas de correlação em uma nova página de detalhes do usuário. Linguagem de implementação: **Python** (ETL + Backend) e **TypeScript** (Frontend React).

## Tasks

- [x] 1. Infraestrutura SAM — Novos recursos e parâmetros
  - [x] 1.1 Adicionar parâmetros e recursos ao template.yaml
    - Adicionar parâmetros de deploy: `PromptsPrefix` (String, default vazio), `IdentityStoreId` (String, default vazio)
    - Criar `GluePromptsTable` (AWS::Glue::Table) no database `kiro_usage` com nome `prompts`, schema de metadados conforme design (userId, originalUserId, displayName, userName, timestamp, date, hour, modelId, triggerType, customizationArn, requestId, conversationId, utteranceId, region, accountId, promptLength, responseLength), particionada por year/month, location `s3://${DataBucket}/prompts-metadata/`
    - Criar `UserNamesTable` (AWS::DynamoDB::Table) com PK=userId (String), PAY_PER_REQUEST
    - Criar parâmetros SSM: `/kiro-cost-analyzer/prompts-prefix` e `/kiro-cost-analyzer/identity-store-id`
    - Atualizar `GlueActivityTable` — adicionar colunas `displayName` (string) e `userName` (string) ao schema existente
    - Adicionar permissões Lake Formation para ETL e Backend na tabela `prompts`
    - _Requisitos: 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.6, 10.1, 10.2, 10.5, 13.1, 13.2, 13.8, 13.9_

  - [x] 1.2 Atualizar variáveis de ambiente e permissões IAM das Lambdas
    - Adicionar variáveis de ambiente ao EtlFunction: `SSM_PROMPTS_PREFIX`, `SSM_IDENTITY_STORE_ID`, `USER_NAMES_TABLE`, `GLUE_PROMPTS_TABLE`
    - Adicionar variáveis de ambiente ao BackendFunction: `GLUE_PROMPTS_TABLE`, `SSM_PROMPTS_PREFIX`, `SSM_IDENTITY_STORE_ID`, `USER_NAMES_TABLE`
    - Adicionar permissões IAM ao EtlFunction: `identitystore:DescribeUser`, `identitystore:ListUsers`, DynamoDB access para UserNamesTable, Glue access para tabela prompts
    - Adicionar permissões IAM ao BackendFunction: Glue read para tabela prompts, DynamoDB read para UserNamesTable
    - _Requisitos: 10.3, 10.4, 10.5, 10.7, 13.8_

  - [x] 1.3 Adicionar novos endpoints de API ao BackendFunction
    - Adicionar eventos API Gateway: `GET /api/prompts`, `GET /api/prompts/{requestId}`, `GET /api/usage/{userId}/details`
    - Todos com autenticação Cognito (CognitoAuthorizer existente)
    - _Requisitos: 10.6_

- [x] 2. Checkpoint — Validar template SAM
  - Executar `sam validate` para garantir que o template atualizado é válido
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. ETL — Módulos de leitura e parsing de prompts
  - [x] 3.1 Estender `etl/config.py` — adicionar prompts_prefix e identity_store_id
    - Adicionar campos `prompts_prefix` e `identity_store_id` ao dataclass `EtlConfig`
    - Ler novos parâmetros do Parameter Store via variáveis de ambiente `SSM_PROMPTS_PREFIX` e `SSM_IDENTITY_STORE_ID`
    - Tratar parâmetros vazios/ausentes retornando string vazia (sem erro)
    - _Requisitos: 2.3, 2.4, 13.1, 13.2_

  - [x] 3.2 Criar `etl/prompt_s3_reader.py` — listagem e leitura de .json.gz
    - Função `list_prompt_files(bucket, prompts_prefix)` que lista todos os `.json.gz` recursivamente sob `{prompts_prefix}GenerateAssistantResponse/`
    - Usar paginação S3 (ContinuationToken), filtrar apenas `.json.gz`
    - Função `read_prompt_file(bucket, key)` que retorna bytes brutos (gzipped)
    - _Requisitos: 1.1_

  - [x] 3.3 Criar `etl/prompt_parser.py` — descompressão gzip e parsing JSON
    - Dataclass `RawPromptRecord` com campos: prompt, response, userId, timestamp, modelId, triggerType, customizationArn, requestId, conversationId, utteranceId, followupPrompts, codeReferenceEvents, supplementaryWebLinksEvent
    - Função `parse_prompt_file(gzipped_content: bytes) -> list[RawPromptRecord]` que descomprime gzip, faz parsing JSON, extrai cada record do array `records`
    - Extrair campos de `generateAssistantResponseEventRequest` e `generateAssistantResponseEventResponse`
    - Retornar lista vazia se `records` está vazio (sem erro)
    - Levantar exceção descritiva se gzip ou JSON inválido
    - _Requisitos: 1.2, 1.3, 1.7, 1.8, 11.1, 11.2, 11.4, 11.5_

  - [x] 3.4 Criar `etl/prompt_normalizer.py` — normalização para PromptRecord
    - Dataclass `PromptRecord` com campos conforme design: userId, originalUserId, displayName, userName, timestamp, date, hour, modelId, triggerType, customizationArn, requestId, conversationId, utteranceId, region, accountId, promptLength, responseLength
    - Função `extract_uuid(user_id: str) -> str` — extrai parte após `.` ou retorna original se não contém `.`
    - Função `normalize_prompt_records(raw_records, path_metadata, name_cache)` que normaliza cada registro: extrai UUID, deriva date/hour do timestamp, substitui None por string vazia, calcula promptLength/responseLength, enriquece com displayName/userName do cache
    - _Requisitos: 1.3, 1.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4_

  - [ ]* 3.5 Escrever teste de propriedade — Round-trip gzip + JSON (Property 1)
    - **Property 1: Round-trip gzip + JSON de logs de prompt**
    - Gerar estruturas JSON válidas de log de prompt com `hypothesis`
    - Verificar que comprimir com gzip e depois descomprimir + parsing produz estrutura equivalente
    - **Valida: Requisitos 1.2, 11.1**

  - [ ]* 3.6 Escrever teste de propriedade — Normalização completa (Property 2)
    - **Property 2: Normalização completa de registros de prompt**
    - Gerar arrays de raw prompt records com campos variados
    - Verificar que normalização produz N PromptRecords com campos corretos, nulls substituídos por string vazia, promptLength/responseLength calculados
    - **Valida: Requisitos 1.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 11.2**

  - [ ]* 3.7 Escrever teste de propriedade — Extração de UUID (Property 3)
    - **Property 3: Extração de UUID e preservação do userId original**
    - Gerar strings no formato `d-xxx.uuid` e strings sem `.`
    - Verificar que extract_uuid retorna parte após `.` ou valor original, e originalUserId preserva entrada completa
    - **Valida: Requisitos 1.4, 5.1, 5.2, 5.3, 5.4**

- [x] 4. ETL — Escrita Parquet/JSON e resolução de nomes
  - [x] 4.1 Criar `etl/prompt_writer.py` — escrita de metadados Parquet e conteúdo JSON
    - Definir `PROMPTS_METADATA_SCHEMA` com pyarrow conforme design (17 colunas de metadados)
    - Função `write_prompt_metadata_parquet(records, data_bucket)` que agrupa por year/month e grava Parquet em `prompts-metadata/year=YYYY/month=MM/data.parquet`
    - Função `write_prompt_content_json(raw_record, normalized, data_bucket)` que grava JSON completo (metadados + prompt + response) em `prompts-content/{requestId}.json`
    - _Requisitos: 1.5, 3.4, 3.5, 4.7_

  - [x] 4.2 Criar `etl/user_name_resolver.py` — resolução via Identity Center + cache DynamoDB
    - Dataclass `UserNameEntry` com campos: userId, displayName, userName, resolvedAt
    - Função `resolve_user_names(user_ids, identity_store_id, table_name)` que: consulta cache DynamoDB, reutiliza se resolvedAt < 7 dias, chama `identitystore:DescribeUser` se cache expirado/ausente, salva no cache, retorna dict[userId, (displayName, userName)]
    - Log warning e retorna ("", "") se API falha para um userId
    - _Requisitos: 13.3, 13.4, 13.5, 13.6, 13.7_

  - [x] 4.3 Estender `etl/normalizer.py` — adicionar displayName/userName ao UserActivityRecord
    - Adicionar campos `displayName: str` e `userName: str` ao dataclass `UserActivityRecord` com default string vazia
    - Atualizar `normalize_records` para aceitar e propagar displayName/userName
    - _Requisitos: 13.10_

  - [x] 4.4 Estender `etl/parquet_writer.py` — adicionar colunas displayName/userName ao schema activity
    - Adicionar campos `displayName` (pa.string()) e `userName` (pa.string()) ao `ACTIVITY_SCHEMA`
    - Atualizar `_records_to_table` para incluir os novos campos nos arrays
    - _Requisitos: 13.10_

  - [x] 4.5 Estender `etl/handler.py` — orquestrar pipeline de prompts e resolução de nomes
    - Importar novos módulos: prompt_s3_reader, prompt_parser, prompt_normalizer, prompt_writer, user_name_resolver
    - Após pipeline de activity existente, executar pipeline de prompts se `cfg.prompts_prefix` configurado
    - Coletar userIds únicos de ambos os pipelines
    - Se `cfg.identity_store_id` configurado, resolver nomes via `resolve_user_names`
    - Enriquecer registros de activity e prompts com displayName/userName antes de gravar
    - Gravar conteúdo JSON individual para cada prompt via `write_prompt_content_json`
    - Gravar metadados Parquet via `write_prompt_metadata_parquet`
    - Marcar arquivos .json.gz processados no DynamoDB (reutilizar processing_tracker)
    - Atualizar status ETL no Parameter Store com contadores de prompts
    - Se prompts_prefix vazio, log informativo e pular processamento de prompts
    - _Requisitos: 1.1, 1.5, 1.6, 1.7, 1.8, 1.9, 2.3, 2.4, 13.3, 13.6, 13.10, 13.11, 13.12_

  - [ ]* 4.6 Escrever teste de propriedade — Round-trip JSON conteúdo (Property 4)
    - **Property 4: Round-trip de conteúdo JSON de prompt**
    - Gerar PromptRecords com textos de prompt/resposta variados
    - Verificar que gravar como JSON e ler de volta produz objeto com campos equivalentes
    - **Valida: Requisitos 3.5, 4.7**

  - [ ]* 4.7 Escrever teste de propriedade — Round-trip Parquet metadados (Property 5)
    - **Property 5: Round-trip de metadados Parquet de prompt**
    - Gerar listas de PromptRecords com campos variados
    - Verificar que serializar para Parquet e ler de volta produz registros equivalentes
    - **Valida: Requisitos 11.3**

  - [ ]* 4.8 Escrever teste de propriedade — Cache TTL (Property 11)
    - **Property 11: Cache de nomes respeita TTL de 7 dias**
    - Gerar entradas de cache com resolvedAt variando de 0 a 14 dias atrás
    - Verificar que entradas < 7 dias usam cache, entradas >= 7 dias chamam API
    - **Valida: Requisitos 13.5**

  - [ ]* 4.9 Escrever teste de propriedade — Enriquecimento displayName (Property 12)
    - **Property 12: Enriquecimento de registros Parquet com displayName/userName**
    - Gerar registros com e sem entradas no cache de nomes
    - Verificar que registros com cache recebem valores resolvidos, sem cache recebem string vazia
    - **Valida: Requisitos 13.10, 13.11, 13.12**

- [x] 5. Checkpoint — Validar ETL de prompts
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Backend — Endpoints de prompts e detalhes do usuário
  - [x] 6.1 Criar `backend/prompts_handler.py` — GET /api/prompts e GET /api/prompts/{requestId}
    - Função `handle_list_prompts(query_params)` que constrói SQL Athena com filtros opcionais (userId, startDate, endDate, modelId, triggerType), paginação via limit/nextToken (offset base64), máximo 50 registros por página, filtros de partição year/month
    - Função `handle_get_prompt_detail(request_id)` que lê JSON de `s3://{DataBucket}/prompts-content/{requestId}.json` via S3 GetObject, retorna 404 se não encontrado
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x] 6.2 Criar `backend/user_details_handler.py` — GET /api/usage/{userId}/details
    - Função `handle_user_details(user_id, query_params)` que executa múltiplas queries Athena:
      - Consumo diário (activity): créditos, mensagens, conversas, overage por dia
      - Interações diárias (prompts): contagem por dia
      - Distribuição por modelo: contagem e percentual por modelId
      - Distribuição por trigger: contagem e percentual por triggerType
      - Prompts recentes: últimos 20 com campos resumidos
      - Custo por interação: LEFT JOIN activity ↔ prompts por userId e date
    - Usar filtros de partição year/month em todas as queries
    - Retornar 404 se userId não possui dados em nenhuma tabela
    - Aceitar parâmetros startDate e endDate para filtrar período
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 6.3 Estender `backend/handler.py` — adicionar novas rotas
    - Importar `prompts_handler` e `user_details_handler`
    - Adicionar rota `GET /api/prompts` → `prompts_handler.handle_list_prompts`
    - Adicionar rota `GET /api/prompts/{requestId}` → `prompts_handler.handle_get_prompt_detail` (usar regex para extrair requestId do path)
    - Adicionar rota `GET /api/usage/{userId}/details` → `user_details_handler.handle_user_details` (usar regex para extrair userId do path)
    - _Requisitos: 6.1, 6.5, 7.1_

  - [x] 6.4 Estender `backend/usage_handler.py` — incluir displayName/userName nos resultados
    - Atualizar SQL de `_build_sql` para incluir `MAX(displayName) AS displayName, MAX(userName) AS userName` no SELECT
    - Atualizar `_parse_user_row` para incluir displayName e userName no dict retornado
    - _Requisitos: 14.1_

  - [x] 6.5 Estender `backend/config_handler.py` — adicionar prompts-prefix e identity-store-id
    - Atualizar `handle_get_config` para ler e retornar `promptsPrefix` e `identityStoreId` do Parameter Store
    - Criar `handle_put_config_prompts_prefix(body)` para salvar prompts-prefix no Parameter Store
    - Criar `handle_put_config_identity_store_id(body)` para salvar identity-store-id no Parameter Store
    - Adicionar rotas `PUT /api/config/prompts-prefix` e `PUT /api/config/identity-store-id` no handler.py
    - _Requisitos: 2.5, 13.1, 13.2_

  - [ ]* 6.6 Escrever teste de propriedade — Filtros SQL de prompts (Property 6)
    - **Property 6: Geração correta de filtros SQL para consultas de prompts**
    - Gerar combinações de parâmetros de filtro (userId, startDate, endDate, modelId, triggerType)
    - Verificar que SQL contém cláusulas WHERE correspondentes e filtros de partição quando datas presentes
    - **Valida: Requisitos 6.3, 6.4, 9.3**

  - [ ]* 6.7 Escrever teste de propriedade — Paginação de prompts (Property 7)
    - **Property 7: Limite de paginação de prompts**
    - Gerar conjuntos de resultados de 0 a 200 registros
    - Verificar que resposta contém no máximo 50 registros e nextToken quando há mais
    - **Valida: Requisitos 6.7**

  - [ ]* 6.8 Escrever teste de propriedade — Custo por interação (Property 8)
    - **Property 8: Cálculo de custo por interação**
    - Gerar pares (créditos, interações) com valores aleatórios incluindo 0
    - Verificar que custo = créditos/interações quando interações > 0, null quando interações == 0
    - **Valida: Requisitos 7.4**

  - [ ]* 6.9 Escrever teste de propriedade — Distribuição preserva totais (Property 9)
    - **Property 9: Distribuição por dimensão preserva totais**
    - Gerar listas de prompts com modelIds e triggerTypes variados
    - Verificar que soma de count = total de prompts e soma de percentage = 100%
    - **Valida: Requisitos 7.5, 7.6**

  - [ ]* 6.10 Escrever teste de propriedade — Prompts recentes (Property 10)
    - **Property 10: Prompts recentes ordenados e limitados**
    - Gerar listas de prompts com timestamps aleatórios (0 a 100 itens)
    - Verificar que retorna no máximo 20, ordenados por timestamp DESC, e são os 20 mais recentes
    - **Valida: Requisitos 7.7**

- [x] 7. Checkpoint — Validar Backend
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Frontend — Tipos, roteamento e extensão de componentes existentes
  - [x] 8.1 Estender `frontend/src/types/index.ts` — novos tipos TypeScript
    - Adicionar `displayName` e `userName` ao tipo `UserUsage` existente
    - Criar tipos: `PromptMetadata`, `PromptDetail`, `PromptsListResponse`, `DailyUsageEntry`, `ModelDistribution`, `TriggerDistribution`, `RecentPrompt`, `UserDetailSummary`, `UserDetailResponse`
    - Atualizar `AppConfig` para incluir `promptsPrefix` e `identityStoreId`
    - _Requisitos: 8.1, 14.2_

  - [x] 8.2 Estender `frontend/src/App.tsx` — adicionar rota /user/:userId
    - Importar `UserDetailPage`
    - Adicionar `<Route path="/user/:userId" element={<UserDetailPage />} />` ao React Router
    - _Requisitos: 12.1, 12.5_

  - [x] 8.3 Estender `frontend/src/components/UsageTable.tsx` — userId como link clicável e coluna displayName
    - Importar `Link` do Cloudscape e `useNavigate` do React Router
    - Atualizar coluna userId para exibir `displayName` como texto principal (link clicável para `/user/{userId}`) com UUID como texto secundário
    - Quando displayName vazio, exibir apenas UUID como link
    - Atualizar filtro de texto para buscar também por displayName
    - _Requisitos: 12.2, 12.3, 14.2, 14.4_

  - [x] 8.4 Estender `frontend/src/pages/SettingsPage.tsx` — campos prompts-prefix e identity-store-id
    - Adicionar campos de formulário para `promptsPrefix` e `identityStoreId` na seção de configuração
    - Carregar valores atuais via GET /api/config
    - Salvar via PUT /api/config/prompts-prefix e PUT /api/config/identity-store-id
    - _Requisitos: 2.5, 14.5_

- [x] 9. Frontend — Página de detalhes do usuário
  - [x] 9.1 Criar `frontend/src/components/UserSummaryCards.tsx` — cards de resumo
    - Exibir 4 cards com Cloudscape `ColumnLayout`: Total Créditos, Total Interações, Custo Médio/Interação, Total Mensagens
    - Aceitar dados de `UserDetailSummary` como props
    - Formatar números em pt-BR
    - _Requisitos: 8.2_

  - [x] 9.2 Criar `frontend/src/components/DailyUsageChart.tsx` — gráfico dual-axis
    - Usar Cloudscape `LineChart` com duas séries: créditos diários (eixo esquerdo) e interações por dia (eixo direito)
    - Aceitar dados de `DailyUsageEntry[]` como props
    - _Requisitos: 8.3_

  - [x] 9.3 Criar `frontend/src/components/DistributionCharts.tsx` — gráficos de pizza
    - Dois `PieChart` do Cloudscape lado a lado: distribuição por modelo e distribuição por trigger
    - Aceitar dados de `ModelDistribution[]` e `TriggerDistribution[]` como props
    - _Requisitos: 8.4, 8.5_

  - [x] 9.4 Criar `frontend/src/components/RecentPromptsTable.tsx` — tabela de prompts recentes
    - Cloudscape `Table` com colunas: data/hora, modelo, tipo de trigger, tamanho do prompt, tamanho da resposta
    - Ao clicar em uma linha, expandir com `ExpandableSection` mostrando conteúdo completo do prompt e resposta (carregado via GET /api/prompts/{requestId})
    - _Requisitos: 8.6, 8.7_

  - [x] 9.5 Criar `frontend/src/pages/UserDetailPage.tsx` — página de detalhes do usuário
    - Usar `ContentLayout` com header exibindo displayName + userId + botão "Voltar"
    - `BreadcrumbGroup`: Dashboard > Detalhes do Usuário
    - `DateRangePicker` para seleção de período
    - Compor componentes: UserSummaryCards, DailyUsageChart, DistributionCharts, RecentPromptsTable
    - Carregar dados via GET /api/usage/{userId}/details com parâmetros de período
    - Tratar estados: loading, erro (Alert + botão tentar novamente), dados vazios
    - Exibir displayName no cabeçalho junto com userId
    - _Requisitos: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 12.1, 12.4, 12.5, 14.3_

- [x] 10. Checkpoint — Validar Frontend
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Integração final e wiring
  - [x] 11.1 Verificar template SAM completo
    - Garantir que todas as variáveis de ambiente das Lambdas estão configuradas para os novos recursos
    - Verificar permissões IAM: ETL (S3 read prompts, S3 write dados, DynamoDB UserNamesTable, Identity Center, Glue prompts), Backend (Athena, S3 dados, Glue prompts, DynamoDB UserNamesTable)
    - Verificar Lake Formation permissions para tabela prompts
    - Executar `sam validate` e `sam build`
    - _Requisitos: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [ ]* 11.2 Escrever testes unitários dos novos módulos
    - Testar `prompt_parser` com JSON de 1 record, múltiplos records, JSON inválido, gzip inválido, records vazio
    - Testar `prompt_normalizer` com record completo, com nulls, userId sem ponto, userId com múltiplos pontos
    - Testar `prompt_writer` com escrita de 1 prompt, partições diferentes, texto Unicode
    - Testar `prompt_s3_reader` com paginação S3, nenhum arquivo, filtro .json.gz
    - Testar `user_name_resolver` com cache hit, cache miss, cache expirado, API failure, Identity Store não configurado
    - Testar `prompts_handler` com e sem filtros, requestId existente e inexistente
    - Testar `user_details_handler` com activity + prompts, só activity, usuário inexistente
    - Testar `config_handler` com GET/PUT prompts-prefix e identity-store-id
    - _Requisitos: 1.2, 1.7, 1.8, 4.5, 4.6, 5.1, 5.2, 6.5, 6.6, 7.9, 13.5, 13.6, 13.7_

- [x] 12. Checkpoint final
  - Ensure all tests pass, ask the user if questions arise.

## Notas

- Tasks marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada task referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Testes de propriedade validam propriedades universais de corretude definidas no design
- Testes unitários validam exemplos específicos e edge cases
- Linguagem de implementação: Python 3.13 (ETL + Backend), TypeScript (Frontend React)
- Todos os 14 requisitos estão cobertos por pelo menos uma task
