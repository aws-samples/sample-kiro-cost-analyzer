"""Few-Shot Exporter — manages the few-shot examples file in S3.

The file at ``config/few-shot-examples.json`` is the **single source of truth**
for all few-shot examples used by the prompt classifier.  It contains both the
original seed examples (migrated from the hardcoded Python prompt) and
user-feedback examples added through the approval workflow.

There is no separate hardcoded fallback; this file IS the source of truth.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

try:
    import boto3
except ImportError:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

S3_KEY = "config/few-shot-examples.json"
MAX_EXAMPLES_PER_CATEGORY = 5

# ---------------------------------------------------------------------------
# Seed data — extracted from the original SYSTEM_PROMPT in
# etl/prompt_categorizer.py.  Used by ``seed_initial_examples`` to populate
# the S3 file on first deploy.
# ---------------------------------------------------------------------------

_SEED_EXAMPLES: list[dict] = [
    # Code Generation
    {"category": "Code Generation", "example": "cria uma função que calcula o total de créditos"},
    {"category": "Code Generation", "example": "implement a Lambda handler for the new endpoint"},
    {"category": "Code Generation", "example": "gera o componente React pra tabela de usuários"},
    {"category": "Code Generation", "example": "cria um componente de chat"},
    {"category": "Code Generation", "example": "write a Python script to process CSV files"},
    # Debugging
    {"category": "Debugging", "example": "esse erro TypeError tá aparecendo quando clico no botão"},
    {"category": "Debugging", "example": "why is the Lambda timing out?"},
    {"category": "Debugging", "example": "o fetch tá retornando 500, investiga"},
    {"category": "Debugging", "example": "pega o ultimo log e corrige pls"},
    {"category": "Debugging", "example": "travou...pega o erro"},
    # Refactoring
    {"category": "Refactoring", "example": "refatora esse código pra usar hooks"},
    {"category": "Refactoring", "example": "simplifica essa função, tá muito complexa"},
    {"category": "Refactoring", "example": "extract this logic into a reusable utility"},
    {"category": "Refactoring", "example": "extrair componente reutilizável"},
    {"category": "Refactoring", "example": "remove duplicação de código"},
    # Documentation
    {"category": "Documentation", "example": "atualiza o README com as mudanças"},
    {"category": "Documentation", "example": "documenta essa API"},
    {"category": "Documentation", "example": "adiciona JSDoc nos métodos públicos"},
    {"category": "Documentation", "example": "atualiza o README da solucao"},
    {"category": "Documentation", "example": "analisa tudo oq foi feito hoje"},
    # Testing
    {"category": "Testing", "example": "escreve testes unitários pra esse handler"},
    {"category": "Testing", "example": "add property-based tests for the validator"},
    {"category": "Testing", "example": "cria um teste de integração pro endpoint"},
    {"category": "Testing", "example": "roda os testes pra ver se passa"},
    {"category": "Testing", "example": "simula uma categorizacao usando o nova micro"},
    # Code Review
    {"category": "Code Review", "example": "revisa esse código e sugere melhorias"},
    {"category": "Code Review", "example": "o que acha dessa implementação?"},
    {"category": "Code Review", "example": "tem algo errado nesse approach?"},
    {"category": "Code Review", "example": "eh uma boa ideia manter o DateRangePickerPtBR tao localizado?"},
    {"category": "Code Review", "example": "nao é possivel q seja tudo empty"},
    # Architecture/Design
    {"category": "Architecture/Design", "example": "como estruturar o banco pra esse caso?"},
    {"category": "Architecture/Design", "example": "qual a melhor abordagem pra separar esses serviços?"},
    {"category": "Architecture/Design", "example": "vamos discutir a arquitetura do ETL"},
    {"category": "Architecture/Design", "example": "nao é melhor usar o S3 como local temporario desse payload?"},
    {"category": "Architecture/Design", "example": "poderiamos colocar essa classificacao fora desse fluxo express"},
    # DevOps/Infrastructure
    {"category": "DevOps/Infrastructure", "example": "configura o template SAM pra adicionar essa Lambda"},
    {"category": "DevOps/Infrastructure", "example": "ajusta as permissões IAM do backend"},
    {"category": "DevOps/Infrastructure", "example": "como fazer deploy disso no CloudFormation?"},
    {"category": "DevOps/Infrastructure", "example": "manda bala no deploy"},
    {"category": "DevOps/Infrastructure", "example": "commita ai e faz deploy"},
    # Data Analysis
    {"category": "Data Analysis", "example": "analisa os dados de consumo do último mês"},
    {"category": "Data Analysis", "example": "quais usuários gastaram mais créditos?"},
    {"category": "Data Analysis", "example": "gera um relatório de uso por tier"},
    {"category": "Data Analysis", "example": "da um scan na tabela e me totaliza"},
    {"category": "Data Analysis", "example": "verifica se tem as referencias pro arquivo no S3"},
    # Production Troubleshooting
    {"category": "Production Troubleshooting", "example": "o dashboard tá fora do ar"},
    {"category": "Production Troubleshooting", "example": "os dados não estão atualizando desde ontem"},
    {"category": "Production Troubleshooting", "example": "o ETL falhou na última execução, investiga"},
    {"category": "Production Troubleshooting", "example": "eu ja disparei e ela travou"},
    {"category": "Production Troubleshooting", "example": "mesma coisa...nao é melhor usar o S3?"},
    # Feedback/Critique
    {"category": "Feedback/Critique", "example": "essa UI ficou estranha, o layout tá quebrado"},
    {"category": "Feedback/Critique", "example": "não gostei dessa abordagem, prefiro outra"},
    {"category": "Feedback/Critique", "example": "o logo ficou muito pequeno"},
    {"category": "Feedback/Critique", "example": "essa cor não combina"},
    {"category": "Feedback/Critique", "example": "ta na vertical ainda..."},
    # Planning/Discussion
    {"category": "Planning/Discussion", "example": "vamos começar pelos quick wins"},
    {"category": "Planning/Discussion", "example": "me explica sobre a fase 3"},
    {"category": "Planning/Discussion", "example": "quais são os próximos passos?"},
    {"category": "Planning/Discussion", "example": "faz sentido fazer isso agora?"},
    {"category": "Planning/Discussion", "example": "vamos em frente"},
    # General Q&A
    {"category": "General Q&A", "example": "o que é um z-score?"},
    {"category": "General Q&A", "example": "como funciona o EventBridge Scheduler?"},
    {"category": "General Q&A", "example": "qual a diferença entre rate e cron?"},
    {"category": "General Q&A", "example": "tem certeza? verifica a doc"},
    {"category": "General Q&A", "example": "quais categorias vc incluiu?"},
]


class FewShotExporter:
    """Manages the few-shot examples file in S3 (single source of truth).

    The file at ``S3_KEY`` contains ALL examples used by the classifier —
    both the original seed examples (migrated from the hardcoded Python
    prompt) and user-feedback examples.  There is no separate hardcoded
    fallback; this file IS the source of truth.

    Args:
        bucket: Name of the S3 bucket.
        s3_client: Optional boto3 S3 client (for testing).
    """

    def __init__(self, bucket: str, s3_client=None):
        self._bucket = bucket
        self._s3 = s3_client or boto3.client("s3")

    def add_example(
        self,
        category: str,
        prompt_snippet: str,
        feedback_id: str,
        approved_at: str,
    ) -> None:
        """Add an approved example, enforcing the per-category cap.

        Reads the current file (or starts from ``[]`` if missing), appends
        the new example, trims to ``MAX_EXAMPLES_PER_CATEGORY`` per category
        keeping the most recent by ``approvedAt``, and writes back.

        Args:
            category: The category for the example.
            prompt_snippet: The prompt text (up to 200 chars).
            feedback_id: The requestId of the feedback.
            approved_at: ISO-8601 timestamp of approval.
        """
        examples = self.load_examples()

        new_example = {
            "category": category,
            "example": prompt_snippet,
            "source": "feedback",
            "feedbackId": feedback_id,
            "approvedAt": approved_at,
        }
        examples.append(new_example)

        # Group by category and keep only the most recent per category
        by_category: dict[str, list[dict]] = defaultdict(list)
        for ex in examples:
            by_category[ex["category"]].append(ex)

        trimmed: list[dict] = []
        for cat, cat_examples in by_category.items():
            # Sort by approvedAt descending — None/null values sort last
            cat_examples.sort(
                key=lambda e: e.get("approvedAt") or "",
                reverse=True,
            )
            trimmed.extend(cat_examples[:MAX_EXAMPLES_PER_CATEGORY])

        self._save_examples(trimmed)

    def load_examples(self) -> list[dict]:
        """Load all examples from S3.

        Returns:
            List of example dicts.  Returns ``[]`` if the file does not
            exist (``NoSuchKey``).
        """
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=S3_KEY)
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                logger.info(
                    "Few-shot examples file not found at s3://%s/%s",
                    self._bucket,
                    S3_KEY,
                )
                return []
            raise

    def _save_examples(self, examples: list[dict]) -> None:
        """Serialize and write examples to S3 with UTF-8 encoding and indentation.

        Args:
            examples: List of example dicts to persist.
        """
        body = json.dumps(examples, ensure_ascii=False, indent=2)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=S3_KEY,
            Body=body.encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )

    @staticmethod
    def seed_initial_examples(bucket: str, s3_client=None) -> None:
        """One-time migration: write the original hardcoded examples to S3.

        Called during deployment or manually to populate the initial file.
        Skips if the file already exists to avoid overwriting feedback
        examples that may have been added after the first seed.

        Args:
            bucket: Name of the S3 bucket.
            s3_client: Optional boto3 S3 client (for testing).
        """
        client = s3_client or boto3.client("s3")

        # Check if the file already exists
        try:
            client.head_object(Bucket=bucket, Key=S3_KEY)
            logger.info(
                "Few-shot examples file already exists at s3://%s/%s — skipping seed.",
                bucket,
                S3_KEY,
            )
            return
        except Exception as exc:
            # Only proceed if the error is a 404 (file not found)
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if error_code not in ("404", "NoSuchKey"):
                raise

        # Build seed examples with source="seed"
        seed_data = [
            {
                "category": ex["category"],
                "example": ex["example"],
                "source": "seed",
                "feedbackId": None,
                "approvedAt": None,
            }
            for ex in _SEED_EXAMPLES
        ]

        body = json.dumps(seed_data, ensure_ascii=False, indent=2)
        client.put_object(
            Bucket=bucket,
            Key=S3_KEY,
            Body=body.encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
        logger.info(
            "Seeded %d initial few-shot examples to s3://%s/%s",
            len(seed_data),
            bucket,
            S3_KEY,
        )
