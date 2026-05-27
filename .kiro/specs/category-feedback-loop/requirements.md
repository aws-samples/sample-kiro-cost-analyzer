# Documento de Requisitos — Category Feedback Loop

## Introdução

O sistema de categorização de prompts do Kiro Cost Analyzer classifica prompts de usuários em 14 categorias predefinidas usando Amazon Bedrock. Atualmente, o classificador utiliza um system prompt estático com exemplos hardcoded e não oferece mecanismo para corrigir classificações incorretas. Esta feature implementa um ciclo de feedback onde correções de usuários são capturadas, revisadas e transformadas em exemplos few-shot dinâmicos que enriquecem o classificador ao longo do tempo — sem retreinar nenhum modelo.

## Glossário

- **Feedback_API**: Conjunto de endpoints REST no Backend Lambda responsáveis por receber, listar e revisar correções de categoria
- **Feedback_Store**: Registros de feedback armazenados na `FeedbackTable` dedicada do DynamoDB, separada da `Analytics_Table`
- **Feedback_Modal**: Componente modal do frontend (Cloudscape) que permite ao usuário selecionar a categoria correta e fornecer uma justificativa opcional
- **Prompt_Detail_Panel**: Componente `PromptDetailPanel.tsx` existente que exibe detalhes de um prompt selecionado
- **Category_Corrector**: Módulo do backend responsável por aplicar a correção aprovada no registro original do prompt e atualizar os contadores de distribuição
- **Few_Shot_Exporter**: Módulo que exporta exemplos aprovados para um arquivo JSON no S3, consumido pelo classificador
- **Prompt_Categorizer**: Classe `PromptCategorizer` existente em `etl/prompt_categorizer.py` que classifica prompts via Bedrock
- **Admin_Panel**: Interface administrativa no frontend para revisão e aprovação/rejeição de feedbacks pendentes
- **Valid_Categories**: As 14 categorias de classificação: Code Generation, Debugging, Refactoring, Documentation, Testing, Code Review, Architecture/Design, DevOps/Infrastructure, Data Analysis, Production Troubleshooting, Feedback/Critique, Planning/Discussion, General Q&A, Other
- **System_Categories**: Categorias internas não elegíveis para feedback: Empty, NOT_CATEGORIZED, Classification Error
- **Dynamic_Examples**: Exemplos few-shot armazenados em S3 como fonte única de verdade para o classificador, incluindo exemplos seed (migrados do código) e exemplos de feedback aprovados

## Requisitos

### Requisito 1: Submissão de Feedback pelo Usuário

**User Story:** Como usuário do dashboard, eu quero corrigir a categoria de um prompt classificado incorretamente, para que o sistema aprenda com meus ajustes e melhore a precisão da classificação.

#### Critérios de Aceitação

1. WHEN o usuário visualiza um prompt no Prompt_Detail_Panel, THE Prompt_Detail_Panel SHALL exibir a categoria atual do prompt e um botão "Corrigir categoria" ao lado dela
2. WHEN o prompt possui uma categoria pertencente às System_Categories, THE Prompt_Detail_Panel SHALL ocultar o botão "Corrigir categoria" para esse prompt
3. WHEN o usuário clica no botão "Corrigir categoria", THE Feedback_Modal SHALL ser exibido com um Select contendo as 14 Valid_Categories e um campo de texto opcional "Motivo da correção"
4. WHEN o Feedback_Modal é exibido, THE Feedback_Modal SHALL pré-selecionar a categoria atual do prompt no Select e desabilitar a submissão até que o usuário selecione uma categoria diferente da atual
5. WHEN o usuário confirma a correção no Feedback_Modal, THE Feedback_Modal SHALL enviar uma requisição POST para `/api/prompts/{requestId}/feedback` contendo os campos `suggestedCategory` e `reason`
6. WHEN a submissão do feedback é bem-sucedida, THE Feedback_Modal SHALL exibir uma notificação de sucesso e fechar o modal
7. IF a submissão do feedback falha com erro de rede ou servidor, THEN THE Feedback_Modal SHALL exibir uma mensagem de erro e manter o modal aberto para nova tentativa

### Requisito 2: Armazenamento de Feedback no DynamoDB

**User Story:** Como sistema, eu quero armazenar os feedbacks de correção de categoria no DynamoDB, para que possam ser revisados e utilizados para melhorar o classificador.

#### Critérios de Aceitação

1. WHEN a Feedback_API recebe um POST em `/api/prompts/{requestId}/feedback`, THE Feedback_API SHALL validar que `suggestedCategory` pertence às Valid_Categories
2. WHEN a Feedback_API recebe um POST com `suggestedCategory` igual à categoria atual do prompt, THE Feedback_API SHALL rejeitar a requisição com status 400 e mensagem descritiva
3. WHEN a validação é bem-sucedida, THE Feedback_Store SHALL criar um registro com PK=`FEEDBACK#{requestId}`, SK=`FEEDBACK#{timestamp}`, contendo os campos: `originalCategory`, `suggestedCategory`, `promptSnippet` (primeiros 200 caracteres do prompt), `reason`, `submittedBy`, `status` (valor inicial: "pending"), e `createdAt`
4. WHEN o prompt original possui `contentInS3=true`, THE Feedback_API SHALL buscar o conteúdo do prompt no S3 para extrair o `promptSnippet`
5. IF o prompt referenciado pelo `requestId` não existe, THEN THE Feedback_API SHALL retornar status 404 com mensagem descritiva
6. IF já existe um feedback pendente para o mesmo `requestId`, THEN THE Feedback_API SHALL rejeitar a requisição com status 409 e mensagem informando que já existe uma correção pendente

### Requisito 3: Revisão Administrativa de Feedbacks

**User Story:** Como administrador, eu quero revisar os feedbacks de correção pendentes, para que eu possa aprovar correções legítimas e rejeitar incorretas antes que afetem o classificador.

#### Critérios de Aceitação

1. WHEN um administrador acessa GET `/api/feedback`, THE Feedback_API SHALL retornar a lista de feedbacks com suporte a filtro por `status` (pending, approved, rejected) e paginação via `nextToken`
2. WHEN um usuário não-administrador acessa GET `/api/feedback`, THE Feedback_API SHALL retornar status 403
3. WHEN um administrador envia PUT `/api/feedback/{feedbackId}/review` com `action` "approve" ou "reject", THE Feedback_API SHALL atualizar o campo `status` do feedback, registrar `reviewedBy` com o username do administrador e `reviewedAt` com o timestamp da revisão
4. WHEN um administrador tenta revisar um feedback que não está com status "pending", THE Feedback_API SHALL retornar status 400 com mensagem informando que o feedback já foi revisado
5. IF o `feedbackId` não existe, THEN THE Feedback_API SHALL retornar status 404

### Requisito 4: Aplicação da Correção no Prompt Original

**User Story:** Como sistema, eu quero que feedbacks aprovados atualizem a categoria do prompt original e os contadores de distribuição, para que o dashboard reflita as correções imediatamente.

#### Critérios de Aceitação

1. WHEN um feedback é aprovado, THE Category_Corrector SHALL atualizar o campo `category` do registro de prompt original no DynamoDB com o valor de `suggestedCategory`
2. WHEN um feedback é aprovado, THE Category_Corrector SHALL decrementar o contador de distribuição da categoria original (`STATS#CATEGORY#{normalizedOldCategory}`) em 1 para o usuário dono do prompt
3. WHEN um feedback é aprovado, THE Category_Corrector SHALL incrementar o contador de distribuição da nova categoria (`STATS#CATEGORY#{normalizedNewCategory}`) em 1 para o usuário dono do prompt
4. IF o contador da categoria original atingir zero após o decremento, THEN THE Category_Corrector SHALL manter o registro com contagem zero em vez de removê-lo

### Requisito 5: Exportação de Exemplos Few-Shot

**User Story:** Como sistema, eu quero exportar feedbacks aprovados como exemplos few-shot para o S3, para que o classificador possa utilizá-los na próxima execução do ETL.

#### Critérios de Aceitação

1. WHEN um feedback é aprovado, THE Few_Shot_Exporter SHALL adicionar o exemplo ao arquivo JSON de exemplos no S3 no caminho `config/few-shot-examples.json`, criando o arquivo caso não exista
2. THE Few_Shot_Exporter SHALL armazenar cada exemplo no formato `{"category": "<categoria>", "example": "<promptSnippet>", "source": "feedback", "feedbackId": "<requestId>", "approvedAt": "<timestamp>"}`
3. WHILE uma categoria possui mais de 5 exemplos, THE Few_Shot_Exporter SHALL manter apenas os 5 exemplos mais recentes para essa categoria
4. THE Few_Shot_Exporter SHALL serializar o arquivo JSON com encoding UTF-8 e formatação legível (indentação)
5. THE Few_Shot_Exporter SHALL fornecer um método `seed_initial_examples` para migrar os exemplos hardcoded do código Python para o arquivo S3 como exemplos com `source: "seed"`, executado uma única vez durante o deploy inicial

### Requisito 6: Carregamento de Exemplos pelo Classificador

**User Story:** Como sistema, eu quero que o classificador carregue todos os exemplos few-shot do S3 e os injete no system prompt, para que a classificação utilize tanto os exemplos originais quanto os de feedback.

#### Critérios de Aceitação

1. WHEN o Prompt_Categorizer é inicializado, THE Prompt_Categorizer SHALL carregar o arquivo `config/few-shot-examples.json` do S3 como fonte única de verdade para os exemplos
2. IF o arquivo de exemplos não existe no S3, THEN THE Prompt_Categorizer SHALL operar com o template base (definições de categorias e regras) sem exemplos, e logar um warning
3. WHEN exemplos são carregados com sucesso, THE Prompt_Categorizer SHALL construir o system prompt combinando o template base com os exemplos do S3, agrupados por categoria
4. THE Prompt_Categorizer SHALL não conter exemplos hardcoded no código Python — todos os exemplos devem vir exclusivamente do arquivo S3
5. FOR ALL prompts classificados, o system prompt construído SHALL conter o template base inalterado acrescido dos exemplos carregados do S3

### Requisito 7: Interface Administrativa de Feedback

**User Story:** Como administrador, eu quero uma interface no dashboard para visualizar e revisar feedbacks pendentes, para que eu possa gerenciar as correções de forma eficiente.

#### Critérios de Aceitação

1. THE Admin_Panel SHALL exibir uma tabela com os feedbacks, contendo as colunas: prompt snippet, categoria original, categoria sugerida, motivo, data de submissão e status
2. WHEN o administrador seleciona um feedback pendente, THE Admin_Panel SHALL exibir botões "Aprovar" e "Rejeitar"
3. WHEN o administrador clica em "Aprovar" ou "Rejeitar", THE Admin_Panel SHALL enviar a requisição PUT correspondente e atualizar a tabela sem recarregar a página
4. THE Admin_Panel SHALL permitir filtrar feedbacks por status (pendente, aprovado, rejeitado) usando um Select
5. WHEN um usuário não-administrador tenta acessar a página de administração de feedbacks, THE Admin_Panel SHALL exibir mensagem de acesso restrito

### Requisito 8: Validação e Integridade dos Dados de Feedback

**User Story:** Como sistema, eu quero garantir a integridade dos dados de feedback em todas as operações, para que correções inválidas não corrompam o classificador ou os dados do dashboard.

#### Critérios de Aceitação

1. THE Feedback_API SHALL validar que o campo `suggestedCategory` contém exatamente uma das 14 Valid_Categories em todas as operações de escrita
2. THE Feedback_API SHALL truncar o campo `reason` em 500 caracteres quando fornecido
3. THE Feedback_Store SHALL armazenar o `promptSnippet` com no máximo 200 caracteres, truncando o conteúdo original quando necessário
4. FOR ALL feedbacks aprovados, a soma dos contadores de distribuição por categoria para um usuário SHALL permanecer igual ao total de prompts desse usuário (propriedade de invariante)
5. FOR ALL operações de exportação de exemplos dinâmicos, serializar e depois deserializar o arquivo JSON SHALL produzir dados equivalentes aos originais (propriedade round-trip)
