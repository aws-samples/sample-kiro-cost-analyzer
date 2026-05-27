# Documento de Requisitos — Análise de Produtividade com Git

## Introdução

Esta feature adiciona ao Kiro Cost Analyzer a capacidade de conectar-se a repositórios Git (GitHub, GitLab, Bitbucket, CodeCommit, etc.) para analisar Pull Requests, commits e outras ações de desenvolvimento. O objetivo é correlacionar o uso do Kiro (prompts, interações, categorias) com as entregas reais dos desenvolvedores nos repositórios, permitindo que gestores avaliem o impacto do Kiro na produtividade da equipe.

A solução se integra à página de produtividade existente (`ProductivityPage`) e ao backend atual, estendendo o modelo de dados Single-Table Design do DynamoDB com novos padrões de chave para atividades Git.

## Glossário

- **Sistema_Git_Connector**: Componente backend responsável por conectar-se a provedores Git (GitHub, GitLab, Bitbucket, CodeCommit) via suas APIs REST, autenticar-se com tokens de acesso e coletar dados de repositórios.
- **Sistema_Git_Sync**: Componente ETL responsável por sincronizar periodicamente os dados de atividades Git (commits, PRs, reviews) dos repositórios configurados para o DynamoDB.
- **Sistema_Correlation_Engine**: Componente backend responsável por calcular métricas de correlação entre o uso do Kiro (prompts/interações) e as atividades Git (commits/PRs) de um desenvolvedor em um período.
- **Sistema_Productivity_API**: Extensão do backend API existente (`handler.py`) que expõe endpoints REST para configuração de repositórios, consulta de atividades Git e análise de impacto de produtividade.
- **Sistema_Productivity_Dashboard**: Extensão da página de produtividade existente (`ProductivityPage.tsx`) que exibe dados de atividades Git, métricas de correlação e visualizações de impacto do Kiro.
- **Git_Provider**: Serviço externo de hospedagem de repositórios Git (GitHub, GitLab, Bitbucket, AWS CodeCommit).
- **Access_Token**: Token de autenticação (Personal Access Token ou OAuth token) usado para acessar a API de um Git_Provider. Armazenado de forma criptografada no SSM Parameter Store.
- **Pull_Request**: Solicitação de merge de código em um repositório Git, contendo commits, revisões e comentários.
- **Commit**: Unidade atômica de alteração de código em um repositório Git, contendo autor, data, mensagem e diff de arquivos.
- **Review**: Revisão de código feita por um desenvolvedor em uma Pull_Request, incluindo comentários e aprovação/rejeição.
- **Índice_de_Impacto**: Métrica calculada pelo Sistema_Correlation_Engine que quantifica a correlação entre uso do Kiro e atividades Git em uma escala de 0 a 100.
- **Repositório_Configurado**: Repositório Git registrado no sistema com URL, provedor, token de acesso e mapeamento de usuários.
- **Mapeamento_de_Usuário**: Associação entre o userId do Kiro e o username/email do desenvolvedor no Git_Provider.

## Requisitos

### Requisito 1: Configuração de Repositórios Git

**User Story:** Como gestor, eu quero configurar repositórios Git para monitoramento, para que o sistema possa coletar dados de atividades dos desenvolvedores.

#### Critérios de Aceitação

1. WHEN o gestor submete uma configuração de repositório com URL, provedor e Access_Token válidos, THE Sistema_Productivity_API SHALL registrar o Repositório_Configurado no DynamoDB com PK `GITREPO#{repoId}` e SK `CONFIG` e retornar o identificador do repositório.
2. WHEN o gestor submete uma configuração de repositório com URL inválida ou provedor não suportado, THE Sistema_Productivity_API SHALL retornar erro 400 com mensagem descritiva indicando o campo inválido.
3. THE Sistema_Productivity_API SHALL suportar os seguintes Git_Providers: GitHub, GitLab, Bitbucket e AWS CodeCommit.
4. WHEN o gestor fornece um Access_Token, THE Sistema_Productivity_API SHALL armazenar o token de forma criptografada no SSM Parameter Store com caminho `/kiro-cost-analyzer/git-tokens/{repoId}` e armazenar apenas a referência SSM no DynamoDB.
5. WHEN o gestor solicita a listagem de repositórios configurados, THE Sistema_Productivity_API SHALL retornar a lista de Repositórios_Configurados sem expor os Access_Tokens (retornando apenas indicação de que o token está configurado).
6. WHEN o gestor solicita a remoção de um Repositório_Configurado, THE Sistema_Productivity_API SHALL remover o registro do DynamoDB e o Access_Token correspondente do SSM Parameter Store.
7. WHEN o gestor submete uma configuração de repositório, THE Sistema_Git_Connector SHALL validar a conectividade com o Git_Provider usando o Access_Token fornecido antes de persistir a configuração.
8. IF a validação de conectividade com o Git_Provider falhar, THEN THE Sistema_Productivity_API SHALL retornar erro 422 com mensagem indicando falha de autenticação ou conectividade.

### Requisito 2: Mapeamento de Usuários Kiro-Git

**User Story:** Como gestor, eu quero mapear os usuários do Kiro aos seus perfis nos repositórios Git, para que o sistema possa correlacionar atividades entre as duas plataformas.

#### Critérios de Aceitação

1. WHEN o gestor submete um Mapeamento_de_Usuário associando um userId do Kiro a um username ou email do Git_Provider, THE Sistema_Productivity_API SHALL registrar o mapeamento no DynamoDB com PK `USER#{userId}` e SK `GITMAP#{provider}#{gitUsername}`.
2. WHEN o gestor submete um Mapeamento_de_Usuário com userId inexistente no sistema, THE Sistema_Productivity_API SHALL retornar erro 404 indicando que o usuário Kiro não foi encontrado.
3. THE Sistema_Productivity_API SHALL permitir múltiplos mapeamentos por usuário Kiro (um por Git_Provider ou múltiplos usernames no mesmo provedor).
4. WHEN o gestor solicita a listagem de mapeamentos de um usuário, THE Sistema_Productivity_API SHALL retornar todos os Mapeamentos_de_Usuário associados ao userId informado.
5. WHEN o gestor solicita a remoção de um Mapeamento_de_Usuário, THE Sistema_Productivity_API SHALL remover o registro correspondente do DynamoDB.
6. WHEN o Sistema_Git_Sync processa atividades Git, THE Sistema_Git_Sync SHALL utilizar os Mapeamentos_de_Usuário para associar commits e Pull_Requests ao userId correto do Kiro.

### Requisito 3: Sincronização de Atividades Git

**User Story:** Como gestor, eu quero que o sistema colete automaticamente as atividades dos desenvolvedores nos repositórios Git, para que eu tenha dados atualizados para análise.

#### Critérios de Aceitação

1. WHEN o agendamento de sincronização é acionado, THE Sistema_Git_Sync SHALL consultar cada Repositório_Configurado e coletar commits, Pull_Requests e Reviews criados desde a última sincronização.
2. THE Sistema_Git_Sync SHALL armazenar cada commit no DynamoDB com PK `USER#{userId}` e SK `GITCOMMIT#{date}#{commitHash}` contendo autor, mensagem, data, repositório, quantidade de arquivos alterados e linhas adicionadas/removidas.
3. THE Sistema_Git_Sync SHALL armazenar cada Pull_Request no DynamoDB com PK `USER#{userId}` e SK `GITPR#{date}#{prId}` contendo título, estado (aberta, merged, fechada), repositório, data de criação, data de merge, quantidade de commits e quantidade de reviews recebidas.
4. THE Sistema_Git_Sync SHALL armazenar cada Review no DynamoDB com PK `USER#{userId}` e SK `GITREVIEW#{date}#{reviewId}` contendo Pull_Request associada, tipo (aprovação, solicitação de mudanças, comentário), repositório e data.
5. IF o Access_Token de um Repositório_Configurado estiver expirado ou inválido durante a sincronização, THEN THE Sistema_Git_Sync SHALL registrar o erro no log estruturado, marcar o repositório com status `SYNC_ERROR` e continuar processando os demais repositórios.
6. WHEN a sincronização de um repositório é concluída com sucesso, THE Sistema_Git_Sync SHALL atualizar o registro do Repositório_Configurado com a data da última sincronização e status `SYNC_OK`.
7. THE Sistema_Git_Sync SHALL respeitar os rate limits das APIs dos Git_Providers, implementando backoff exponencial com jitter quando receber respostas HTTP 429.
8. WHEN o gestor solicita uma sincronização manual de um repositório específico, THE Sistema_Productivity_API SHALL acionar o Sistema_Git_Sync para aquele repositório e retornar o status da operação.

### Requisito 4: Consulta de Atividades Git por Desenvolvedor

**User Story:** Como gestor, eu quero visualizar o histórico completo de atividades Git de um desenvolvedor, para que eu possa entender seu padrão de entregas.

#### Critérios de Aceitação

1. WHEN o gestor solicita as atividades Git de um userId com período opcional (startDate, endDate), THE Sistema_Productivity_API SHALL retornar commits, Pull_Requests e Reviews do desenvolvedor no período, agrupados por tipo.
2. THE Sistema_Productivity_API SHALL retornar métricas agregadas de atividades Git incluindo: total de commits, total de PRs abertas, total de PRs merged, total de reviews realizadas, média de linhas alteradas por commit e média de tempo entre abertura e merge de PRs.
3. THE Sistema_Productivity_API SHALL retornar uma timeline diária de atividades Git contendo contagem de commits, PRs e reviews por dia, ordenada por data.
4. WHEN o gestor solicita atividades Git de um userId sem Mapeamento_de_Usuário configurado, THE Sistema_Productivity_API SHALL retornar resposta vazia com mensagem indicando que nenhum mapeamento Git foi encontrado para o usuário.
5. THE Sistema_Productivity_API SHALL suportar paginação nas listagens de commits e Pull_Requests usando o padrão de nextToken existente no sistema.

### Requisito 5: Análise de Correlação Kiro-Git

**User Story:** Como gestor, eu quero visualizar como o uso do Kiro impacta as entregas dos desenvolvedores, para que eu possa avaliar o retorno sobre o investimento na ferramenta.

#### Critérios de Aceitação

1. WHEN o gestor solicita a análise de impacto de um userId com período, THE Sistema_Correlation_Engine SHALL calcular o Índice_de_Impacto correlacionando o volume de interações Kiro com o volume de atividades Git no mesmo período.
2. THE Sistema_Correlation_Engine SHALL calcular as seguintes métricas de correlação: prompts por commit (razão entre total de prompts Kiro e total de commits no período), taxa de merge de PRs (percentual de PRs abertas que foram merged), tempo médio de review (tempo entre abertura da PR e primeiro review) e produtividade relativa (comparação do volume de entregas em períodos com alto vs. baixo uso do Kiro).
3. THE Sistema_Correlation_Engine SHALL gerar uma timeline comparativa diária contendo, para cada dia: contagem de prompts Kiro, contagem de commits, contagem de PRs e o Índice_de_Impacto diário.
4. THE Sistema_Correlation_Engine SHALL categorizar o Índice_de_Impacto em faixas: "Baixo" (0-25), "Moderado" (26-50), "Alto" (51-75) e "Muito Alto" (76-100).
5. IF o período solicitado não contiver dados suficientes de Kiro ou Git (menos de 3 dias com atividade em ambas as plataformas), THEN THE Sistema_Correlation_Engine SHALL retornar o Índice_de_Impacto como nulo com mensagem indicando dados insuficientes para correlação.
6. THE Sistema_Correlation_Engine SHALL calcular a correlação apenas com base em dados do mesmo userId, respeitando os Mapeamentos_de_Usuário configurados.

### Requisito 6: Dashboard de Produtividade com Git

**User Story:** Como gestor, eu quero visualizar em um dashboard integrado os dados de uso do Kiro junto com as atividades Git, para que eu tenha uma visão completa da produtividade do desenvolvedor.

#### Critérios de Aceitação

1. THE Sistema_Productivity_Dashboard SHALL exibir uma seção "Atividades Git" na página de produtividade contendo cards de resumo com total de commits, PRs merged, reviews realizadas e média de linhas por commit no período selecionado.
2. THE Sistema_Productivity_Dashboard SHALL exibir um gráfico de timeline comparativa mostrando, no mesmo eixo temporal, a curva de interações Kiro e a curva de atividades Git (commits + PRs).
3. THE Sistema_Productivity_Dashboard SHALL exibir o Índice_de_Impacto em destaque com a faixa correspondente (Baixo, Moderado, Alto, Muito Alto) e uma barra de progresso visual.
4. THE Sistema_Productivity_Dashboard SHALL exibir uma tabela de Pull Requests recentes do desenvolvedor com colunas: título, repositório, estado, data de criação, data de merge e quantidade de commits.
5. WHEN o usuário selecionado não possui Mapeamento_de_Usuário configurado, THE Sistema_Productivity_Dashboard SHALL exibir uma mensagem informativa com link para a página de configuração de mapeamentos.
6. THE Sistema_Productivity_Dashboard SHALL manter todas as funcionalidades existentes da página de produtividade (timeline de atividades Kiro, distribuição por categoria, uso por modelo, distribuição horária) inalteradas.
7. THE Sistema_Productivity_Dashboard SHALL utilizar exclusivamente componentes do Cloudscape Design System para todas as novas visualizações.

### Requisito 7: Gestão de Repositórios no Frontend

**User Story:** Como gestor, eu quero uma interface para gerenciar repositórios Git e mapeamentos de usuários, para que eu possa configurar o sistema sem acesso direto ao backend.

#### Critérios de Aceitação

1. THE Sistema_Productivity_Dashboard SHALL fornecer uma página de configuração acessível via menu de navegação onde o gestor pode adicionar, listar e remover Repositórios_Configurados.
2. WHEN o gestor adiciona um novo repositório, THE Sistema_Productivity_Dashboard SHALL apresentar um formulário com campos: nome do repositório, URL, Git_Provider (seleção entre GitHub, GitLab, Bitbucket, CodeCommit) e Access_Token.
3. WHEN o gestor submete o formulário de novo repositório, THE Sistema_Productivity_Dashboard SHALL exibir indicador de carregamento durante a validação de conectividade e exibir mensagem de sucesso ou erro conforme resultado.
4. THE Sistema_Productivity_Dashboard SHALL fornecer uma seção de mapeamento de usuários onde o gestor pode associar userIds do Kiro a usernames Git, com seleção do Git_Provider.
5. WHEN o gestor adiciona um mapeamento, THE Sistema_Productivity_Dashboard SHALL validar que o userId do Kiro existe no sistema antes de submeter ao backend.
6. THE Sistema_Productivity_Dashboard SHALL restringir o acesso às páginas de configuração de repositórios e mapeamentos a usuários do grupo Admins.

### Requisito 8: Segurança e Auditoria

**User Story:** Como gestor, eu quero que os tokens de acesso Git sejam armazenados de forma segura e que as operações sejam auditáveis, para que eu tenha confiança na segurança do sistema.

#### Critérios de Aceitação

1. THE Sistema_Productivity_API SHALL armazenar Access_Tokens exclusivamente no SSM Parameter Store com tipo `SecureString` e criptografia KMS.
2. THE Sistema_Productivity_API SHALL registrar em log estruturado (via StructuredLogger) todas as operações de criação, atualização e remoção de Repositórios_Configurados e Mapeamentos_de_Usuário, incluindo o userId do operador.
3. THE Sistema_Git_Connector SHALL utilizar conexões HTTPS para todas as comunicações com Git_Providers.
4. THE Sistema_Productivity_API SHALL validar que o usuário autenticado pertence ao grupo Admins antes de permitir operações de configuração de repositórios e mapeamentos.
5. IF uma requisição à API de um Git_Provider retornar erro de autenticação (HTTP 401 ou 403), THEN THE Sistema_Git_Connector SHALL registrar o erro no log estruturado sem expor o Access_Token na mensagem de log.
6. THE Sistema_Productivity_API SHALL aplicar rate limiting nas chamadas de sincronização manual para evitar abuso (máximo de 1 sincronização por repositório a cada 5 minutos).
