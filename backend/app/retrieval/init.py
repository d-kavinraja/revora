import logging

from app.retrieval.engine import retrieval_engine
from app.retrieval.ranking.engine import ranking_engine
from app.retrieval.compression.engine import compression_engine
from app.retrieval.retrievers.changed_file_retriever import ChangedFileRetriever
from app.retrieval.retrievers.import_retriever import ImportRetriever
from app.retrieval.retrievers.call_graph_retriever import CallGraphRetriever
from app.retrieval.retrievers.module_retriever import ModuleRetriever
from app.retrieval.retrievers.api_retriever import APIRetriever
from app.retrieval.retrievers.db_retriever import DBRetriever
from app.retrieval.retrievers.security_retriever import SecurityRetriever
from app.retrieval.retrievers.impact_retriever import ImpactRetriever
from app.retrieval.retrievers.documentation_retriever import DocumentationRetriever
from app.retrieval.retrievers.test_retriever import TestRetriever
from app.retrieval.retrievers.rule_retriever import RuleRetriever
from app.retrieval.retrievers.historical_retriever import HistoricalRetriever
from app.retrieval.retrievers.dependency_retriever import DependencyRetriever

logger = logging.getLogger(__name__)


def initialize_retrieval_engine() -> None:
    retrieval_engine.register_retriever(ChangedFileRetriever())
    retrieval_engine.register_retriever(ImportRetriever())
    retrieval_engine.register_retriever(DependencyRetriever())
    retrieval_engine.register_retriever(CallGraphRetriever())
    retrieval_engine.register_retriever(ModuleRetriever())
    retrieval_engine.register_retriever(APIRetriever())
    retrieval_engine.register_retriever(DBRetriever())
    retrieval_engine.register_retriever(TestRetriever())
    retrieval_engine.register_retriever(SecurityRetriever())
    retrieval_engine.register_retriever(ImpactRetriever())
    retrieval_engine.register_retriever(DocumentationRetriever())
    retrieval_engine.register_retriever(RuleRetriever())
    retrieval_engine.register_retriever(HistoricalRetriever())

    retrieval_engine.set_ranking_engine(ranking_engine)
    retrieval_engine.set_compression_engine(compression_engine)

    logger.info(
        f"Retrieval engine initialized: "
        f"{len(retrieval_engine._retrievers)} retrievers, "
        f"{len(ranking_engine._scorers)} ranking scorers, "
        f"{len(compression_engine._strategies)} compression strategies"
    )
