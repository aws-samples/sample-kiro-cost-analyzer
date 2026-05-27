# Plano de Implementação: Categorização Automática de Prompts

## Visão Geral

Implementação da categorização automática de prompts usando Amazon Bedrock (Nova Micro). O pipeline ETL existente salva prompts com `category: "NOT_CATEGORIZED"`. Após o RecordStatus, novos steps Standard (ListUncategorizedPrompts → CategorizePrompts Map Standard) categorizam os prompts pendentes com concorrência controlada (MaxConcurrency=10). O frontend exibe badges de categoria na tabela e um gráfico de pizza de distribuição.

## Tarefas

- [x] 1. Criar módulo categorizador isolado (`etl/prompt_categorizer.py`)
  - [x] 1.1 Implementar a classe `PromptCategorizer` com método `categorize()`
    - Criar `etl/prompt_categorizer.py` com a classe `PromptCategorizer`
    - Definir constante `VALID_CATEGORIES` com as 14 categorias
    - Implementar `__init__` recebendo `model_id`, `region` e `bedrock_client` opcional
    - Implementar `categorize(prompt_text)` que:
      - Retorna `"Empty"` se prompt vazio/whitespace sem chamar Bedrock
      - Trunca para 5000 caracteres antes de enviar
      - Usa `converse()` com `temperature=0.0`, `maxTokens=20`
      - Valida resposta contra `VALID_CATEGORIES`; se inválida → `"Other"`
      - Em caso de exceção → retorna `"Other"` e loga o erro
    - Definir `SYSTEM_PROMPT` reutilizando o few-shot prompt validado em `scripts/test_categorization.py`
    - _Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [ ]* 1.2 Escrever teste de propriedade — Saída sempre válida (Propriedade 1)
    - **Propriedade 1: Saída do categorizador é sempre válida**
    - Gerar strings aleatórias + respostas mock aleatórias do Bedrock, verificar saída ∈ `VALID_CATEGORIES ∪ {"Empty"}`
    - **Valida: Requisitos 1.1, 1.6**

  - [ ]* 1.3 Escrever teste de propriedade — Truncamento para 5000 chars (Propriedade 2)
    - **Propriedade 2: Truncamento para 5000 caracteres**
    - Gerar strings de comprimento variável, verificar que o texto enviado ao Bedrock ≤ 5000 chars
    - **Valida: Requisito 1.4**

  - [ ]* 1.4 Escrever teste de propriedade — Resiliência a erros (Propriedade 3)
    - **Propriedade 3: Resiliência a erros do Bedrock**
    - Gerar exceções aleatórias no mock do Bedrock, verificar retorno `"Other"`
    - **Valida: Requisito 1.7**

  - [ ]* 1.5 Escrever teste de propriedade — Prompt vazio retorna "Empty" (Propriedade 4)
    - **Propriedade 4: Prompt vazio retorna "Empty" sem chamar Bedrock**
    - Gerar strings whitespace-only (incluindo string vazia), verificar retorno `"Empty"` e Bedrock não chamado
    - **Valida: Requisitos 1.8, 2.2**

  - [ ]* 1.6 Escrever testes unitários para `PromptCategorizer`
    - Testar categorização com mock Bedrock retornando cada categoria válida
    - Testar resposta inválida do Bedrock → "Other"
    - Testar prompt vazio → "Empty"
    - Testar truncamento de prompt longo
    - _Requisitos: 1.1, 1.4, 1.6, 1.7, 1.8_

- [x] 2. Modificar camada de escrita para suportar campo `category`
  - [x] 2.1 Adicionar campo `category` ao `write_prompt()` em `etl/repository/analytics_writer.py`
    - Adicionar parâmetro `category=""` ao método `write_prompt()`
    - Incluir `item["category"] = category` no item do DynamoDB
    - _Requisitos: 2.3, 2.5_

  - [x] 2.2 Implementar `increment_category_count()` em `etl/repository/analytics_writer.py`
    - Seguir o padrão de `increment_model_count()` e `increment_trigger_count()`
    - SK: `STATS#CATEGORY#{normalized_category}`
    - UpdateItem ADD `#count :one` + SET `rawCategory = if_not_exists(rawCategory, :raw)`
    - _Requisitos: 2.4, 2.5_

  - [ ]* 2.3 Escrever teste de propriedade — Campo category persistido (Propriedade 5)
    - **Propriedade 5: Campo category é persistido no DynamoDB**
    - Gerar registros com categorias aleatórias, verificar campo `category` no PutItem
    - **Valida: Requisito 2.3**

  - [ ]* 2.4 Escrever teste de propriedade — Contador de categoria incrementado (Propriedade 6)
    - **Propriedade 6: Contador de categoria é incrementado**
    - Gerar categorias aleatórias, verificar UpdateItem ADD com SK `STATS#CATEGORY#{normalizedCategory}`
    - **Valida: Requisito 2.4**

  - [ ]* 2.5 Escrever testes unitários para `analytics_writer.py` (novos métodos)
    - Testar `write_prompt()` com campo `category` presente no item
    - Testar `increment_category_count()` com mock DynamoDB
    - _Requisitos: 2.3, 2.4, 2.5_

- [x] 3. Modificar `writer_handler.py` para salvar prompts com `category: "NOT_CATEGORIZED"`
  - Alterar `_write_prompt_record()` para passar `category="NOT_CATEGORIZED"` ao `write_prompt()`
  - NÃO invocar o categorizador aqui — a categorização roda fora do fluxo Express
  - _Requisitos: 2.1, 2.2_

- [x] 4. Checkpoint — Verificar que testes passam
  - Garantir que todos os testes passam, perguntar ao usuário se houver dúvidas.

- [x] 5. Criar Lambdas de categorização (fora do fluxo Express)
  - [x] 5.1 Criar `etl/list_uncategorized_handler.py`
    - Implementar `list_uncategorized_handler(event, context)`
    - Scan no DynamoDB com `FilterExpression: SK begins_with("PROMPT#") AND category = "NOT_CATEGORIZED"`
    - Retornar lista com campos mínimos: `PK`, `SK`, `requestId`, `contentInS3`, `prompt` (se inline)
    - Paginação completa (scan todas as páginas)
    - _Requisitos: 2.1_

  - [x] 5.2 Criar `etl/categorize_prompt_handler.py`
    - Implementar `categorize_prompt_handler(event, context)`
    - Receber `{PK, SK, requestId, contentInS3?, prompt?}` do Map Standard
    - Ler conteúdo do prompt (inline do event ou S3 via `prompts-content/{requestId}.json`)
    - Instanciar `PromptCategorizer` e chamar `categorize(prompt_text)`
    - UpdateItem no DynamoDB: SET `category` = resultado
    - Chamar `increment_category_count()` via `AnalyticsWriter`
    - Propagar exceções para que o Step Functions faça retry com backoff
    - _Requisitos: 1.1, 1.2, 1.3, 2.1, 2.3, 2.4_

  - [ ]* 5.3 Escrever testes unitários para `list_uncategorized_handler.py`
    - Testar scan com itens NOT_CATEGORIZED
    - Testar scan vazio (sem prompts pendentes)
    - Testar paginação com múltiplas páginas
    - _Requisitos: 2.1_

  - [ ]* 5.4 Escrever testes unitários para `categorize_prompt_handler.py`
    - Testar categorização com prompt inline
    - Testar categorização com prompt no S3
    - Testar prompt vazio → "Empty"
    - Testar propagação de exceção do Bedrock
    - _Requisitos: 1.1, 2.1, 2.3, 2.4_

- [x] 6. Adicionar leitura de distribuição de categorias no backend
  - [x] 6.1 Implementar `get_user_category_distribution()` em `backend/repository/analytics_repository.py`
    - Seguir o padrão de `get_user_model_distribution()` e `get_user_trigger_distribution()`
    - Query com `SK begins_with("STATS#CATEGORY#")`
    - _Requisitos: 3.1_

  - [x] 6.2 Modificar `backend/handlers/user_details_handler.py`
    - Chamar `repo.get_user_category_distribution(user_id)`
    - Calcular distribuição com `_compute_distributions(category_items, "category", "rawCategory")`
    - Incluir `categoryDistribution` na resposta JSON
    - Incluir campo `category` em cada item de `recentPrompts`
    - _Requisitos: 3.2, 3.3_

  - [x] 6.3 Modificar `backend/handlers/prompts_handler.py`
    - Adicionar `"category": item.get("category", "")` em `_parse_prompt_item()`
    - _Requisitos: 3.4_

  - [ ]* 6.4 Escrever teste de propriedade — Cálculo de porcentagem (Propriedade 7)
    - **Propriedade 7: Cálculo de porcentagem de distribuição**
    - Gerar listas de contagens, verificar `count / total * 100` arredondado para 1 casa decimal
    - **Valida: Requisito 3.3**

  - [ ]* 6.5 Escrever teste de propriedade — Metadados incluem category (Propriedade 8)
    - **Propriedade 8: Metadados de prompt incluem categoria**
    - Gerar items DynamoDB com campo `category`, verificar saída de `_parse_prompt_item()`
    - **Valida: Requisito 3.4**

  - [ ]* 6.6 Escrever testes unitários para os handlers do backend
    - Testar `get_user_category_distribution()` com mock DynamoDB
    - Testar resposta de `user_details_handler` com `categoryDistribution`
    - Testar `_parse_prompt_item()` com campo `category`
    - _Requisitos: 3.1, 3.2, 3.3, 3.4_

- [x] 7. Checkpoint — Verificar que testes do backend passam
  - Garantir que todos os testes passam, perguntar ao usuário se houver dúvidas.

- [x] 8. Atualizar tipos TypeScript e componentes do frontend
  - [x] 8.1 Atualizar tipos em `frontend/src/types/index.ts`
    - Adicionar interface `CategoryDistribution` com campos `category`, `count`, `percentage`
    - Adicionar campo `category: string` à interface `RecentPrompt`
    - Adicionar campo `category: string` à interface `PromptMetadata`
    - Adicionar campo `categoryDistribution: CategoryDistribution[]` à interface `UserDetailResponse`
    - _Requisitos: 6.1, 6.2, 6.3, 6.4_

  - [x] 8.2 Adicionar coluna "Categoria" em `frontend/src/components/RecentPromptsTable.tsx`
    - Adicionar coluna com badge/tag colorido por categoria
    - Definir mapa de cores `CATEGORY_COLORS` para as 14 categorias + "Empty"
    - Exibir "N/A" em cor neutra quando `category` estiver vazio
    - _Requisitos: 4.1, 4.2, 4.3_

  - [x] 8.3 Adicionar gráfico de pizza de categorias em `frontend/src/components/DistributionCharts.tsx`
    - Adicionar prop `categoryDistribution: CategoryDistribution[]` à interface
    - Alterar Grid de 2 para 3 colunas (`colspan: 4` cada)
    - Renderizar terceiro PieChart com distribuição de categorias
    - Incluir popover com nome, contagem e porcentagem
    - Tratar estado vazio ("Nenhum dado disponível.") e loading ("Carregando...")
    - _Requisitos: 5.1, 5.2, 5.3, 5.4_

  - [x] 8.4 Atualizar `frontend/src/pages/UserDetailPage.tsx`
    - Passar `categoryDistribution` como prop para `DistributionCharts`
    - _Requisitos: 5.1_

  - [ ]* 8.5 Escrever testes unitários para componentes React
    - Testar `RecentPromptsTable` renderiza coluna "Categoria" com badge
    - Testar badge "N/A" para category vazio
    - Testar `DistributionCharts` renderiza 3 gráficos de pizza
    - Testar estado vazio e loading do gráfico de categorias
    - _Requisitos: 4.1, 4.2, 5.1, 5.3, 5.4_

- [x] 9. Atualizar infraestrutura no `template.yaml`
  - [x] 9.1 Adicionar novas Lambdas ao template SAM
    - Definir `ListUncategorizedFunction` (handler: `list_uncategorized_handler.list_uncategorized_handler`, CodeUri: `etl/`)
    - Definir `CategorizePromptFunction` (handler: `categorize_prompt_handler.categorize_prompt_handler`, CodeUri: `etl/`)
    - Configurar variáveis de ambiente: `ANALYTICS_TABLE`, `DATA_BUCKET`, `BEDROCK_MODEL_ID`, `BEDROCK_REGION`
    - Conceder permissão `bedrock:InvokeModel` à `CategorizePromptFunction` para Nova Micro em us-east-1
    - Conceder permissão DynamoDB (Scan, GetItem, UpdateItem) e S3 (GetObject) às novas Lambdas
    - _Requisitos: 7.1, 7.2, 7.3_

  - [x] 9.2 Adicionar novos steps à State Machine no template SAM
    - Após `RecordStatus`: adicionar step `ListUncategorizedPrompts` (Task → ListUncategorizedFunction)
    - Adicionar `CheckUncategorized` (Choice — se count > 0 → CategorizePrompts, senão → End)
    - Adicionar `CategorizePrompts` (Map Standard, MaxConcurrency=10, ItemsPath: `$.uncategorizedPrompts`)
    - Dentro do Map: invocar `CategorizePromptFunction`
    - Retry no Map: `ErrorEquals: ["ThrottlingException", "Lambda.TooManyRequestsException"]`, IntervalSeconds=2, MaxAttempts=10, BackoffRate=2.0
    - Adicionar `RecordCategorizationStatus` (Pass ou Task para registrar resultado)
    - Atualizar policies da State Machine para invocar as novas Lambdas
    - _Requisitos: 7.1_

- [x] 10. Checkpoint final — Verificar que todos os testes passam
  - Garantir que todos os testes passam, perguntar ao usuário se houver dúvidas.

## Notas

- Tarefas marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada tarefa referencia requisitos específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Testes de propriedade validam propriedades universais de corretude definidas no design
- Testes unitários validam exemplos específicos e edge cases
- A categorização roda FORA do fluxo Express — o pipeline ETL existente salva com `category: "NOT_CATEGORIZED"` e os novos steps Standard categorizam depois
