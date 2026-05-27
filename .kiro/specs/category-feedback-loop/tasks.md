# Plano de Implementação: Category Feedback Loop

## Visão Geral

Implementação incremental do ciclo de feedback para o classificador de prompts. O plano segue a ordem: infraestrutura → backend (repository, handlers, correção, exportação) → ETL (classificador dinâmico) → frontend (modal, painel admin) → integração final. Cada etapa constrói sobre a anterior, sem código órfão.

## Tarefas

- [x] 1. Infraestrutura — FeedbackTable + permissões SAM
  - [x] 1.1 Adicionar FeedbackTable ao `template.yaml`
    - Criar recurso DynamoDB `FeedbackTable` com PK (String, HASH) + SK (String, RANGE), BillingMode PAY_PER_REQUEST
    - Nomear como `!Sub "${StackName}-feedback"`
    - Adicionar variável de ambiente `FEEDBACK_TABLE: !Ref FeedbackTable` ao `BackendFunction`
    - Habilitar versionamento no `DataBucket` adicionando `VersioningConfiguration: Status: Enabled`
    - _Requisitos: 2.3, 5.4_

  - [x] 1.2 Adicionar permissões IAM e rotas de API ao `BackendFunction`
    - Adicionar policy para `FeedbackTable` (PutItem, GetItem, Query, Scan, UpdateItem)
    - Adicionar eventos de API Gateway: POST `/api/prompts/{requestId}/feedback`, GET `/api/feedback`, PUT `/api/feedback/{feedbackId}/review`
    - Adicionar permissão de UpdateItem na `AnalyticsTable` para o BackendFunction (necessário para atualizar categoria do prompt e contadores)
    - _Requisitos: 1.5, 3.1, 3.3_

- [x] 2. Backend — FeedbackRepository e tipos
  - [x] 2.1 Criar `backend/repository/feedback_repository.py`
    - Implementar classe `FeedbackRepository` com injeção de dependência do DynamoDB resource
    - Métodos: `write_feedback`, `get_pending_by_request_id`, `list_feedbacks` (com filtro por status e paginação), `get_feedback_by_pk_sk`, `update_feedback_status`
    - Usar padrão de encode/decode de nextToken (base64 JSON) consistente com `AnalyticsRepository`
    - _Requisitos: 2.3, 2.6, 3.1, 3.3_

  - [ ]* 2.2 Escrever testes unitários para `FeedbackRepository`
    - Testar write_feedback, get_pending_by_request_id, list_feedbacks com filtros, update_feedback_status
    - Usar moto `@mock_aws` para DynamoDB mockado
    - _Requisitos: 2.3, 2.6, 3.1_

- [x] 3. Backend — Feedback Handler (submissão e listagem)
  - [x] 3.1 Criar `backend/handlers/feedback_handler.py`
    - Implementar `handle_submit_feedback(request_id, body, claims, dynamodb_resource, s3_client)`:
      - Validar `suggestedCategory` pertence às 14 Valid_Categories
      - Buscar prompt via `AnalyticsRepository.get_prompt_by_request_id`; retornar 404 se não existe
      - Rejeitar com 400 se `suggestedCategory` == categoria atual do prompt
      - Verificar feedback pendente via `FeedbackRepository.get_pending_by_request_id`; retornar 409 se existe
      - Extrair `promptSnippet` (primeiros 200 chars); se `contentInS3=true`, buscar do S3
      - Truncar `reason` em 500 chars
      - Criar registro com PK=`FEEDBACK#{requestId}`, SK=`FEEDBACK#{timestamp}`, status="pending", incluindo `promptPK` e `promptSK`
    - Implementar `handle_list_feedback(query_params, dynamodb_resource)`:
      - Filtro por status, paginação com limit (max 50, default 20) e nextToken
    - _Requisitos: 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 8.1, 8.2, 8.3_

  - [ ]* 3.2 Escrever testes unitários para `handle_submit_feedback`
    - Testar validação de categoria, rejeição de mesma categoria, prompt não encontrado, feedback pendente duplicado, truncamento de reason e snippet, fluxo feliz
    - _Requisitos: 2.1, 2.2, 2.5, 2.6, 8.1, 8.2, 8.3_

  - [ ]* 3.3 Escrever teste property-based para validação de categoria (Property 1)
    - **Property 1: Validação de categoria aceita apenas Valid_Categories**
    - Gerar strings aleatórias com Hypothesis, verificar que apenas as 14 Valid_Categories são aceitas
    - **Valida: Requisitos 2.1, 8.1**

  - [ ]* 3.4 Escrever teste property-based para rejeição de mesma categoria (Property 2)
    - **Property 2: Rejeição de mesma categoria**
    - Gerar categorias válidas aleatórias, verificar rejeição quando suggestedCategory == currentCategory
    - **Valida: Requisitos 2.2**

  - [ ]* 3.5 Escrever teste property-based para truncamento de campos (Property 11)
    - **Property 11: Truncamento de campos**
    - Gerar strings de comprimento aleatório, verificar que reason ≤ 500 chars e promptSnippet ≤ 200 chars, e que o valor armazenado é prefixo do original
    - **Valida: Requisitos 8.2, 8.3**

- [x] 4. Checkpoint — Validar infraestrutura e backend de submissão
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Backend — CategoryCorrector e novos métodos no AnalyticsWriter
  - [x] 5.1 Adicionar métodos `update_prompt_category` e `decrement_category_count` ao `etl/repository/analytics_writer.py`
    - `update_prompt_category(pk, sk, new_category)`: UpdateItem SET category = :cat no prompt
    - `decrement_category_count(user_id, normalized_category)`: UpdateItem ADD #count :neg_one para STATS#CATEGORY#{normalizedCategory}
    - _Requisitos: 4.1, 4.2, 4.4_

  - [x] 5.2 Criar `backend/handlers/category_corrector.py`
    - Classe `CategoryCorrector` com injeção de dependência
    - Método `apply_correction(feedback)`:
      - Atualizar campo `category` do prompt original via `update_prompt_category`
      - Decrementar contador da categoria original via `decrement_category_count`
      - Incrementar contador da nova categoria via `increment_category_count` (existente)
    - Usar `normalize_sk_value` de `shared/sk_normalizer.py` para normalizar categorias
    - _Requisitos: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 5.3 Escrever testes unitários para `CategoryCorrector` e novos métodos do `AnalyticsWriter`
    - Testar atualização de categoria, decremento/incremento de contadores, caso de contador zerado
    - _Requisitos: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 5.4 Escrever teste property-based para invariante de soma dos contadores (Property 7)
    - **Property 7: Invariante de soma dos contadores de distribuição**
    - Gerar sequências aleatórias de feedbacks e aprovações, verificar que a soma dos contadores STATS#CATEGORY# permanece constante
    - **Valida: Requisitos 4.2, 4.3, 8.4**

- [x] 6. Backend — FewShotExporter
  - [x] 6.1 Criar `backend/handlers/few_shot_exporter.py`
    - Classe `FewShotExporter` com injeção de dependência do S3 client
    - `add_example(category, prompt_snippet, feedback_id, approved_at)`: ler arquivo S3, adicionar exemplo, aplicar limite de 5 por categoria (manter mais recentes por `approvedAt`), reescrever
    - `load_examples()`: carregar exemplos do S3, retornar [] se arquivo não existe
    - `_save_examples(examples)`: serializar JSON com UTF-8 e indentação
    - `seed_initial_examples(bucket, s3_client)`: migrar exemplos hardcoded do `SYSTEM_PROMPT` para S3 com `source: "seed"`, pular se arquivo já existe
    - Caminho S3: `config/few-shot-examples.json`
    - Formato: `{"category": "...", "example": "...", "source": "seed"|"feedback", "feedbackId": "...", "approvedAt": "..."}`
    - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 6.2 Escrever testes unitários para `FewShotExporter`
    - Testar add_example, load_examples, limite por categoria, seed_initial_examples, serialização UTF-8
    - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 6.3 Escrever teste property-based para limite por categoria (Property 8)
    - **Property 8: Exportação few-shot respeita limite por categoria**
    - Gerar sequências de exemplos por categoria, verificar que cada categoria tem no máximo 5 exemplos e são os mais recentes
    - **Valida: Requisitos 5.1, 5.2, 5.3**

  - [ ]* 6.4 Escrever teste property-based para round-trip JSON (Property 9)
    - **Property 9: Round-trip de serialização JSON dos exemplos dinâmicos**
    - Gerar listas aleatórias de exemplos, verificar que serializar e deserializar produz dados equivalentes
    - **Valida: Requisitos 5.4, 8.5**

- [x] 7. Backend — Review Handler (aprovação/rejeição com correção e exportação)
  - [x] 7.1 Implementar `handle_review_feedback` no `feedback_handler.py`
    - Buscar feedback por PK/SK; retornar 404 se não existe
    - Validar que `action` é "approve" ou "reject"; retornar 400 se inválido
    - Validar que status é "pending"; retornar 400 se já revisado
    - Atualizar status, `reviewedBy`, `reviewedAt` via `FeedbackRepository`
    - Se action == "approve":
      - Chamar `CategoryCorrector.apply_correction` para atualizar prompt e contadores
      - Chamar `FewShotExporter.add_example` para exportar exemplo ao S3
    - _Requisitos: 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 5.1_

  - [ ]* 7.2 Escrever testes unitários para `handle_review_feedback`
    - Testar aprovação (com correção e exportação), rejeição, feedback não encontrado, feedback já revisado, action inválida
    - _Requisitos: 3.3, 3.4, 3.5_

- [x] 8. Backend — Integrar rotas no Router (`handler.py`)
  - [x] 8.1 Adicionar rotas de feedback ao `backend/handler.py`
    - Adicionar patterns: `_FEEDBACK_SUBMIT_PATTERN` para POST `/api/prompts/{requestId}/feedback`, `_FEEDBACK_REVIEW_PATTERN` para PUT `/api/feedback/{feedbackId}/review`
    - Rota POST feedback: qualquer usuário autenticado, passar `claims` ao handler
    - Rota GET `/api/feedback`: admin-only, retornar 403 se não admin
    - Rota PUT review: admin-only, retornar 403 se não admin
    - Importar `feedback_handler` com try/except fallback
    - _Requisitos: 1.5, 3.1, 3.2, 3.3_

  - [ ]* 8.2 Escrever testes unitários para as novas rotas no router
    - Testar roteamento correto, verificação de admin, passagem de claims
    - _Requisitos: 3.2_

- [x] 9. Checkpoint — Validar backend completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. ETL — Classificador com exemplos dinâmicos do S3
  - [x] 10.1 Modificar `etl/prompt_categorizer.py` para carregar exemplos do S3
    - Adicionar parâmetros `s3_client` e `data_bucket` ao `__init__`
    - Implementar `_load_examples_from_s3()`: carregar `config/few-shot-examples.json` do S3; retornar [] se não existe (log warning)
    - Implementar `_build_system_prompt()`: construir prompt combinando template base (definições de categorias + regras, sem exemplos hardcoded) com exemplos do S3 agrupados por categoria
    - Implementar `build_system_prompt_with_examples(examples)` como método estático puro para testabilidade
    - Remover exemplos hardcoded do `SYSTEM_PROMPT` — manter apenas definições de categorias e regras de classificação
    - Usar `self._full_system_prompt` no método `categorize` em vez do `SYSTEM_PROMPT` global
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 10.2 Atualizar `etl/categorize_prompt_handler.py` para passar S3 ao classificador
    - Modificar `_get_categorizer()` para passar `s3_client` e `data_bucket` (de `os.environ["DATA_BUCKET"]`) ao `PromptCategorizer`
    - _Requisitos: 6.1_

  - [ ]* 10.3 Escrever testes unitários para o classificador com exemplos dinâmicos
    - Testar carregamento de exemplos do S3, construção do system prompt, fallback quando arquivo não existe
    - _Requisitos: 6.1, 6.2, 6.3_

  - [ ]* 10.4 Escrever teste property-based para construção do system prompt (Property 10)
    - **Property 10: Construção do system prompt usa template base + exemplos S3**
    - Gerar conjuntos aleatórios de exemplos, verificar que o system prompt preserva o template base inalterado e inclui os exemplos agrupados por categoria
    - **Valida: Requisitos 6.3, 6.4, 6.5**

- [x] 11. Frontend — Tipos e FeedbackModal
  - [x] 11.1 Adicionar interfaces de feedback ao `frontend/src/types/index.ts`
    - Adicionar `FeedbackSubmission`, `FeedbackRecord`, `FeedbackListResponse`, `FeedbackReviewAction` conforme design
    - _Requisitos: 1.5, 3.1_

  - [x] 11.2 Criar `frontend/src/components/FeedbackModal.tsx`
    - Modal Cloudscape com Select das 14 Valid_Categories e campo Input para motivo (opcional)
    - Pré-selecionar categoria atual, desabilitar botão "Confirmar" enquanto categoria selecionada == atual
    - Enviar POST `/api/prompts/{requestId}/feedback` via api client
    - Exibir notificação de sucesso e fechar modal; exibir erro e manter modal aberto em caso de falha
    - Tratar erro 409 com mensagem específica "Já existe uma correção pendente para este prompt"
    - Textos em português brasileiro
    - _Requisitos: 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 11.3 Modificar `frontend/src/components/PromptDetailPanel.tsx`
    - Adicionar exibição da categoria atual do prompt nos metadados
    - Adicionar botão "Corrigir categoria" ao lado da categoria
    - Ocultar botão para System_Categories (Empty, NOT_CATEGORIZED, Classification Error)
    - Abrir `FeedbackModal` ao clicar no botão, passando `requestId` e categoria atual
    - _Requisitos: 1.1, 1.2, 1.3_

  - [ ]* 11.4 Escrever testes unitários para `FeedbackModal`
    - Testar renderização, pré-seleção, validação de submit, tratamento de erros
    - _Requisitos: 1.3, 1.4, 1.6, 1.7_

- [x] 12. Checkpoint — Validar frontend de submissão de feedback
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Frontend — Painel Administrativo de Feedbacks
  - [x] 13.1 Criar `frontend/src/pages/FeedbackAdminPage.tsx`
    - Tabela Cloudscape com colunas: prompt snippet, categoria original, categoria sugerida, motivo, data de submissão, status
    - Select para filtro por status (pendente, aprovado, rejeitado)
    - Botões "Aprovar" e "Rejeitar" para feedbacks pendentes selecionados
    - Enviar PUT `/api/feedback/{feedbackId}/review` via api client
    - Atualizar tabela sem recarregar a página após ação
    - Paginação via nextToken
    - Exibir mensagem de acesso restrito para não-admins
    - Textos em português brasileiro
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 13.2 Integrar `FeedbackAdminPage` no `App.tsx`
    - Adicionar rota `/feedback` no Routes
    - Adicionar item "Feedbacks" no `SideNavigation` (visível apenas para admins via `useAuth().user.groups`)
    - Importar e renderizar `FeedbackAdminPage`
    - _Requisitos: 7.5_

  - [ ]* 13.3 Escrever testes unitários para `FeedbackAdminPage`
    - Testar tabela, filtros, ações de aprovação/rejeição, acesso restrito
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 14. Seed de exemplos iniciais e integração final
  - [x] 14.1 Criar script `scripts/seed_few_shot_examples.py`
    - Script que invoca `FewShotExporter.seed_initial_examples()` para migrar os exemplos hardcoded do `prompt_categorizer.py` para o S3
    - Extrair os exemplos do `SYSTEM_PROMPT` atual e converter para o formato JSON com `source: "seed"`
    - Pode ser executado manualmente ou como parte do deploy inicial
    - _Requisitos: 5.5, 6.4_

  - [x] 14.2 Verificação de integração ponta a ponta
    - Verificar que todas as rotas estão conectadas no router
    - Verificar que o template.yaml tem todos os recursos e permissões
    - Verificar que o frontend navega corretamente entre as páginas
    - Verificar que imports com try/except fallback estão corretos em todos os novos módulos
    - _Requisitos: 1.1–1.7, 2.1–2.6, 3.1–3.5, 4.1–4.4, 5.1–5.5, 6.1–6.5, 7.1–7.5, 8.1–8.5_

- [x] 15. Checkpoint final — Validar tudo
  - Ensure all tests pass, ask the user if questions arise.

## Notas

- Tarefas marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada tarefa referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental a cada fase
- Testes property-based validam as propriedades de corretude universais definidas no design
- Testes unitários validam exemplos específicos e edge cases
- O backend usa Python 3.13, o frontend usa TypeScript com React + Cloudscape
