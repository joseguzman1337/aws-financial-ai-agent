"""
Script to trigger Bedrock Knowledge Base ingestion job.
This ensures the PDFs uploaded to S3 are processed and available for the agent.
"""

import logging
import os
import sys

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def ingest_knowledge_base(kb_id: str, ds_id: str, region: str = "us-east-1"):
    """Starts an ingestion job for the given knowledge base and data source."""
    client = boto3.client("bedrock-agent", region_name=region)

    try:
        logger.info(
            "Starting ingestion job for KB: %s, Data Source: %s", kb_id, ds_id
        )
        response = client.start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id,
        )
        job_id = response["ingestionJob"]["ingestionJobId"]
        logger.info("Successfully started ingestion job. Job ID: %s", job_id)
        return job_id
    except ClientError as e:
        logger.error("Failed to start ingestion job: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    # Note: Use environment variables or manual assignment
    # These can be retrieved via 'terraform output'
    KB_ID = os.environ.get("KB_ID", "YOUR_KNOWLEDGE_BASE_ID")
    DS_ID = os.environ.get("DS_ID", "YOUR_DATA_SOURCE_ID")

    if "YOUR_" in KB_ID or "YOUR_" in DS_ID:
        logger.error(
            "Please set KB_ID and DS_ID env vars or edit the script "
            "with IDs from 'terraform output'."
        )
        sys.exit(1)

    ingest_knowledge_base(KB_ID, DS_ID)
