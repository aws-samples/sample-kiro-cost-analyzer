# Plano de Implementação: Migração DynamoDB Single-Table Design

## Visão Geral

Migração do backend analítico do Kiro Cost Analyzer de Athena/Glue/Parquet para DynamoDB Single-Table Design com Step Functions. A implementação segue uma ordem lógica: módulos compartilhados e fundacionais primeiro, depois pipeline ETL, depois refatoração do backend API, depois infraestrutura SAM, e por fim limpeza de código legado.

## Tarefas

- [x] 1. Criar módulo compartilhado SK Normalizer e modelos de dados
  - [x] 1.1 Implementar `shared/sk_normalizer.py` com a função `normalize_sk_value`
    - Implementar o pipeline de transformações: lookup canônico, lowercase, trim, substituir especiais por hífens, remover não-alfanuméricos exceto hífens, colapsar hífens consecutivos, remover hífens nas extremidades, truncar para 128 caracteres
    - Suportar dicionário canônico opcional via parâmetro `canonical_map`
    - _Requisitos: 2.1, 2.2, 2.5, 2.6, 2.7_

  - [ ]* 1.2 Escrever teste de propriedade para invariantes de saída do SK Normalizer
    - **Propriedade 1: Invariantes de saída do SK Normalizer**
    - Usar `@given(st.text())` para verificar: apenas lowercase alfanuméricos e hífens, sem hífens no início/final, sem hífens consecutivos, comprimento ≤128, saída não-vazia para entradas com alfanuméricos
    - **Valida: Requisitos 2.1, 2.2, 2.6**

  - [ ]* 1.3 Escrever teste de propriedade para determinismo e idempotência do SK Normalizer
    - **Propriedade 2: Determinismo e idempotência do SK Normalizer**
    - Usar `@given(st.text())` para verificar: `normalize(x) == normalize(x)` e `normalize(normalize(x)) == normalize(x)`
    - **Valida: Requisitos 2.3, 2.8**

  - [ ]* 1.4 Escrever teste de propriedade para mapeamento canônico do SK Normalizer
    - **Propriedade 3: Mapeamento canônico do SK Normalizer**
    - Usar `@given(st.dictionaries(st.text(), st.text()), st.text())` para verificar comportamento com e sem match no dicionário
    - **Valida: Requisito 2.5**

  - [x] 1.5 Criar `backend/models/types.py` com dataclasses do backend
    - Definir `PromptMetadata`, `DailyStats`, `ModelDistribution`, `TriggerDistribution`, `GlobalDailyStats`
    - Criar `backend/models/__init__.py`
    - _Requisitos: 11.1_

  - [x] 1.6 Criar módulo de logging estruturado `shared/structured_logger.py`
    - Implementar classe `StructuredLogger` com métodos `info`, `warning`, `error`
    - Emitir logs em formato JSON com campos: timestamp, level, message, lambda, correlationId e kwargs adicionais
    - _Requisitos: 10.1, 10.7_

- [x] 2. Checkpoint — Verificar módulos compartilhados
  - Garantir que todos os testes passam, perguntar ao usuário se houver dúvidas.

- [x] 3. Implementar a Analytics_Table no template SAM e o repository de leitura
  - [x] 3.1 Adicionar recurso `Analytics_Table` ao `template.yaml`
    - Definir `AWS::DynamoDB::Table` com PK (String) e SK (String), PAY_PER_REQUEST
    - Adicionar GSI `requestId-index` com PK `requestId` e projeção ALL
    - _Requisitos: 1.1, 1.6, 1.7, 12.1_

  - [x] 3.2 Implementar `backend/repository/analytics_repository.py`
    - Implementar classe `AnalyticsRepository` com injeção de dependência do recurso DynamoDB
    - Implementar métodos: `get_user_daily_stats`, `get_user_model_distribution`, `get_user_trigger_distribution`, `get_user_prompts`, `get_global_daily_stats`, `get_prompt_by_request_id`, `scan_user_stats`
    - Usar `begins_with` e `between` nas condições de SK conforme padrões de acesso do design
    - Criar `backend/repository/__init__.py`
    - _Requisitos: 11.2, 11.3, 11.4_

  - [ ]* 3.3 Escrever testes unitários para `AnalyticsRepository`
    - Testar queries com filtros de data, paginação com LastEvaluatedKey, scan com FilterExpression
    - Usar moto para mock do DynamoDB
    - _Requisitos: 11.2, 11.4_

  - [ ]* 3.4 Escrever teste de propriedade para completude da paginação
    - **Propriedade 9: Completude da paginação**
    - Verificar que iterar por todas as páginas retorna todos os itens exatamente uma vez, sem duplicatas e sem omissões
    - **Valida: Requisitos 6.4, 8.3**

- [x] 4. Implementar pipeline ETL — Parse Lambda e Writer Lambda
  - [x] 4.1 Criar `etl/processors/csv_processor.py`
    - Implementar parse de CSV de atividade + normalização de registros para formato de escrita no DynamoDB
    - Reutilizar lógica existente de `csv_parser.py` e `normalizer.py` adaptada para retornar dicts prontos para DynamoDB
    - Criar `etl/processors/__init__.py`
    - _Requisitos: 4.1, 11.5_

  - [x] 4.2 Criar `etl/processors/prompt_processor.py`
    - Implementar parse de .json.gz de prompts + normalização para formato de escrita no DynamoDB
    - Reutilizar lógica existente de `prompt_parser.py` e `prompt_normalizer.py`
    - Incluir lógica de extração de UUID via `extract_uuid`
    - _Requisitos: 4.2, 5.3, 11.5_

  - [ ]* 4.3 Escrever teste de propriedade para extração de UUID
    - **Propriedade 7: Extração de UUID de userId com prefixo de diretório**
    - Usar `@given(st.text(), st.uuids())` para verificar que `extract_uuid("d-{x}.{uuid}") == str(uuid)` e strings sem `.` retornam inalteradas
    - **Valida: Requisito 5.3**

  - [x] 4.4 Criar `etl/repository/analytics_writer.py`
    - Implementar classe `AnalyticsWriter` com injeção de dependência (DynamoDB resource, S3 client)
    - Implementar `write_prompt`: PutItem com decisão inline (≤4KB) vs S3 (>4KB), definindo `contentInS3`
    - Implementar `increment_daily_stats`: UpdateItem ADD para `STATS#DAILY#{date}`
    - Implementar `increment_model_count`: UpdateItem ADD para `STATS#MODEL#{normalizedModelId}`, SET rawModelId if_not_exists
    - Implementar `increment_trigger_count`: UpdateItem ADD para `STATS#TRIGGER#{normalizedTriggerType}`, SET rawTriggerType if_not_exists
    - Implementar `increment_global_daily_stats`: UpdateItem ADD para `GLOBAL` / `STATS#DAILY#{date}`
    - Usar `shared/sk_normalizer.py` para normalizar valores de SK
    - Criar `etl/repository/__init__.py`
    - _Requisitos: 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 11.6_

  - [ ]* 4.5 Escrever teste de propriedade para preservação de valores originais
    - **Propriedade 4: Preservação de valores originais nas escritas**
    - Verificar que itens de distribuição contêm tanto o valor normalizado na SK quanto o valor original bruto em rawModelId/rawTriggerType
    - **Valida: Requisito 2.4**

  - [ ]* 4.6 Escrever teste de propriedade para acumulação de contadores atômicos
    - **Propriedade 5: Acumulação correta de contadores atômicos**
    - Usar `@given(st.lists(st.floats(min_value=0, max_value=1000)))` para verificar que soma dos incrementos == valor final dos contadores
    - **Valida: Requisitos 4.3, 4.4, 4.5, 4.6**

  - [ ]* 4.7 Escrever teste de propriedade para decisão de armazenamento híbrido
    - **Propriedade 6: Decisão de armazenamento híbrido baseada no tamanho**
    - Usar `@given(st.text(min_size=0, max_size=10000))` para verificar que contentInS3 é true iff tamanho > 4096
    - **Valida: Requisitos 4.7, 4.8**

  - [x] 4.8 Criar `etl/parse_handler.py` — entry point da Parse Lambda
    - Receber evento do Step Functions com `bucket`, `key`, `fileType`, `correlationId`
    - Configurar `StructuredLogger` com correlationId
    - Ler arquivo do S3, despachar para csv_processor ou prompt_processor
    - Resolver nomes de usuário via `etl/utils/name_resolver.py` (adaptar de `user_name_resolver.py`)
    - Retornar registros normalizados prontos para escrita
    - _Requisitos: 4.1, 4.2, 5.1, 5.2, 10.2, 10.3_

  - [x] 4.9 Criar `etl/writer_handler.py` — entry point da Writer Lambda
    - Receber evento do Step Functions com `records`, `fileType`, `key`, `correlationId`
    - Configurar `StructuredLogger` com correlationId
    - Para cada registro: escrever na Analytics_Table via `AnalyticsWriter`
    - Retornar resultado com `recordCount`, `itemsWritten`, `durationMs`
    - _Requisitos: 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 10.4, 10.5_

  - [ ]* 4.10 Escrever teste de propriedade para consistência de recuperação de conteúdo
    - **Propriedade 8: Consistência de recuperação de conteúdo de prompts**
    - Verificar round-trip: write → read retorna conteúdo idêntico, tanto para inline quanto para S3
    - **Valida: Requisitos 8.4, 8.5**

- [x] 5. Checkpoint — Verificar pipeline ETL
  - Garantir que todos os testes passam, perguntar ao usuário se houver dúvidas.

- [x] 6. Implementar ListFiles Lambda e RecordStatus Lambda
  - [x] 6.1 Criar `etl/list_handler.py` — entry point da ListFiles Lambda
    - Listar arquivos CSV sob prefixo `user_report/` e arquivos .json.gz sob prefixo de prompts
    - Consultar ProcessedFilesTable para determinar arquivos já processados
    - Retornar lista de arquivos novos com metadados: `bucket`, `key`, `fileType`, `newFilesCount`
    - Usar `StructuredLogger` com correlationId
    - _Requisitos: 3.1, 3.2, 10.1_

  - [x] 6.2 Criar `etl/record_status_handler.py` — entry point da RecordStatus Lambda
    - Receber resultados do Map state (listResult + mapResults)
    - Computar sumário: total de arquivos, processados com sucesso, com falha, registros escritos
    - Registrar status no SSM Parameter Store
    - _Requisitos: 3.6, 10.6_

  - [ ]* 6.3 Escrever testes unitários para ListFiles Lambda e RecordStatus Lambda
    - Testar filtragem de arquivos já processados, contagem de novos, escrita de status no SSM
    - _Requisitos: 3.1, 3.2, 3.6_

- [x] 7. Refatorar Backend API — Handlers para usar Repository Layer
  - [x] 7.1 Criar `backend/utils/` com SK Normalizer e logging
    - Copiar ou criar symlink de `shared/sk_normalizer.py` para `backend/utils/sk_normalizer.py`
    - Copiar ou criar symlink de `shared/structured_logger.py` para `backend/utils/logging.py`
    - Criar `backend/utils/__init__.py`
    - _Requisitos: 2.7, 11.1_

  - [x] 7.2 Criar `backend/handlers/` e mover handlers existentes
    - Criar diretório `backend/handlers/` com `__init__.py`
    - Mover `usage_handler.py`, `account_usage_handler.py`, `user_details_handler.py`, `prompts_handler.py`, `export_handler.py`, `config_handler.py`, `etl_trigger_handler.py`, `users_handler.py` para `backend/handlers/`
    - _Requisitos: 11.1_

  - [x] 7.3 Refatorar `backend/handlers/usage_handler.py` para usar DynamoDB
    - Substituir queries Athena por chamadas ao `AnalyticsRepository.scan_user_stats`
    - Implementar paginação com `limit` (máximo 50) e `nextToken` via LastEvaluatedKey
    - Manter schema de resposta idêntico: summary, users, period
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 13.1, 13.2_

  - [x] 7.4 Refatorar `backend/handlers/user_details_handler.py` para usar DynamoDB
    - Substituir 6 queries Athena sequenciais por queries DynamoDB via `AnalyticsRepository`
    - Usar `get_user_daily_stats`, `get_user_model_distribution`, `get_user_trigger_distribution`, `get_user_prompts`
    - Manter schema de resposta idêntico: userId, displayName, userName, summary, dailyUsage, modelDistribution, triggerDistribution, recentPrompts, period
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 13.1, 13.2_

  - [x] 7.5 Refatorar `backend/handlers/account_usage_handler.py` para usar DynamoDB
    - Substituir queries Athena por `AnalyticsRepository.get_global_daily_stats`
    - Implementar agrupamento por granularidade (dia, semana, mês) a partir dos itens diários globais
    - Manter schema de resposta idêntico: totals, timeline, breakdownByTier, breakdownByClientType, period
    - _Requisitos: 9.1, 9.2, 9.3, 9.4, 13.1, 13.2_

  - [ ]* 7.6 Escrever teste de propriedade para preservação de totais na agregação de timeline
    - **Propriedade 10: Preservação de totais na agregação de timeline**
    - Usar `@given(st.lists(st.tuples(st.dates(), st.floats())))` para verificar que soma dos valores agrupados == soma dos valores individuais
    - **Valida: Requisito 9.3**

  - [x] 7.7 Refatorar `backend/handlers/prompts_handler.py` para usar DynamoDB
    - Substituir queries Athena por `AnalyticsRepository.get_user_prompts` e `get_prompt_by_request_id`
    - Implementar lógica de conteúdo híbrido: inline do DynamoDB vs busca no S3 quando `contentInS3=true`
    - Manter schemas de resposta idênticos para listagem e detalhe
    - _Requisitos: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 13.1, 13.2_

  - [x] 7.8 Refatorar `backend/handlers/export_handler.py` para usar novo `usage_handler`
    - Atualizar importações para usar o handler refatorado
    - _Requisitos: 13.1_

  - [x] 7.9 Refatorar `backend/handlers/etl_trigger_handler.py` para iniciar Step Functions
    - Substituir invocação direta do Lambda ETL por `StartExecution` da ETL_StateMachine
    - Usar variável de ambiente `STATE_MACHINE_ARN` em vez de `ETL_FUNCTION_ARN`
    - _Requisitos: 3.8_

  - [x] 7.10 Atualizar `backend/handler.py` para importar dos novos caminhos
    - Atualizar importações para `backend.handlers.*` e `backend.repository.*`
    - Remover importações de `athena_client` e tratamento de `AthenaQueryError`/`AthenaQueryTimeout`
    - Adicionar tratamento de erros DynamoDB (throttling → 503)
    - _Requisitos: 11.1, 11.3, 13.3, 13.4_

  - [ ]* 7.11 Escrever testes unitários para handlers refatorados
    - Testar cada handler com repository mockado
    - Verificar schemas de resposta compatíveis com interfaces TypeScript do frontend
    - _Requisitos: 13.1, 13.2, 13.3, 13.4_

- [x] 8. Checkpoint — Verificar backend refatorado
  - Garantir que todos os testes passam, perguntar ao usuário se houver dúvidas.

- [x] 9. Atualizar template SAM — Novos recursos e permissões
  - [x] 9.1 Adicionar Lambdas ETL ao `template.yaml`
    - Definir `ListFilesFunction`, `ParseFunction`, `WriterFunction`, `RecordStatusFunction` como `AWS::Serverless::Function`
    - Configurar variáveis de ambiente para cada Lambda (tabelas, buckets, SSM params)
    - Configurar permissões IAM conforme tabela de permissões do design
    - _Requisitos: 12.4, 12.8_

  - [x] 9.2 Adicionar ETL_StateMachine ao `template.yaml`
    - Definir `AWS::Serverless::StateMachine` com tipo Standard
    - Incluir definição ASL em YAML conforme design (ListNewFiles → CheckNewFiles → ProcessFiles Map → RecordStatus)
    - Configurar integrações nativas DynamoDB para MarkFileProcessed e RecordStatusNoFiles
    - Configurar role IAM com permissão para invocar Lambdas e acessar DynamoDB
    - _Requisitos: 12.2, 12.5_

  - [x] 9.3 Adicionar regra EventBridge para ETL_StateMachine
    - Definir ScheduleV2 como evento da StateMachine com expressão configurável
    - _Requisitos: 12.3, 3.7_

  - [x] 9.4 Atualizar permissões e variáveis de ambiente do BackendFunction
    - Adicionar acesso de leitura à Analytics_Table (Query, GetItem, Scan) e GSI
    - Adicionar variável de ambiente `ANALYTICS_TABLE` e `STATE_MACHINE_ARN`
    - Remover variáveis de ambiente Athena/Glue (ATHENA_WORKGROUP, ATHENA_OUTPUT_LOCATION, GLUE_DATABASE, GLUE_TABLE, GLUE_PROMPTS_TABLE)
    - _Requisitos: 12.7, 12.9_

  - [x] 9.5 Copiar `shared/sk_normalizer.py` e `shared/structured_logger.py` para `etl/utils/` e `backend/utils/`
    - Criar `etl/utils/sk_normalizer.py` e `etl/utils/logging.py`
    - Garantir que ambos os pacotes Lambda incluem os módulos compartilhados
    - _Requisitos: 2.7_

- [x] 10. Remover recursos legados do template SAM e código morto
  - [x] 10.1 Remover recursos Athena/Glue/LakeFormation do `template.yaml`
    - Remover: `GlueDatabase`, `GlueActivityTable`, `GluePromptsTable`, `AthenaWorkgroup`
    - Remover: `LakeFormationSetupFunction`, `LakeFormationSetup`
    - Remover: Todas as `AWS::LakeFormation::Permissions` (LakeFormationEtlDatabase, LakeFormationEtlTable, LakeFormationBackendDatabase, LakeFormationBackendTable, LakeFormationEtlPromptsTable, LakeFormationBackendPromptsTable)
    - Remover políticas IAM de Athena/Glue do BackendFunction e EtlFunction
    - _Requisitos: 12.6, 12.7_

  - [x] 10.2 Remover código legado do backend
    - Remover `backend/athena_client.py`
    - Remover handlers antigos da raiz de `backend/` (os que foram movidos para `backend/handlers/`)
    - _Requisitos: 14.1, 14.2_

  - [x] 10.3 Remover código legado do ETL
    - Remover `etl/parquet_writer.py` e dependência de pyarrow
    - Remover `etl/prompt_writer.py` (funções de escrita Parquet e registro Glue)
    - Remover `etl/handler.py` (handler monolítico antigo, substituído por parse_handler + writer_handler + list_handler + record_status_handler)
    - Remover pyarrow de `etl/requirements.txt`
    - _Requisitos: 14.3, 14.4, 14.5_

  - [x] 10.4 Remover custom resource `custom_resources/lake_formation_setup.py`
    - Remover arquivo e referências no template
    - _Requisitos: 12.6_

- [x] 11. Checkpoint final — Verificar tudo integrado
  - Garantir que todos os testes passam, perguntar ao usuário se houver dúvidas.

## Notas

- Tarefas marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada tarefa referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Testes de propriedade validam propriedades universais de corretude definidas no design
- Testes unitários validam exemplos específicos e casos de borda
