"""
GraphQL Router — mounts Strawberry on FastAPI.

Usage in main_local.py:
    from src.api.router import create_graphql_router
    router = create_graphql_router(context_store, job_manager)
    app.include_router(router, prefix="/graphql")
"""

import logging

from strawberry.fastapi import GraphQLRouter

from src.api.schema import create_schema

logger = logging.getLogger(__name__)


def create_graphql_router(context_store, job_manager) -> GraphQLRouter:
    """
    Create a FastAPI-compatible GraphQL router.

    Mounts the Strawberry schema with the GraphiQL IDE enabled.
    """
    schema = create_schema(context_store, job_manager)

    router = GraphQLRouter(
        schema,
        graphql_ide="graphiql",
    )

    logger.info("GraphQL router created (GraphiQL IDE enabled)")
    return router
