output "cognito_client_id" {
  description = "The ID of the Cognito User Pool Client. Use this in the Jupyter Notebook."
  value       = aws_cognito_user_pool_client.financial_agent_client.id
}

output "identity_pool_id" {
  description = "The ID of the Cognito Identity Pool."
  value       = aws_cognito_identity_pool.financial_agent_identity_pool.id
}

output "user_pool_id" {
  description = "The ID of the Cognito User Pool."
  value       = aws_cognito_user_pool.financial_agent_pool.id
}

output "agent_runtime_arn" {
  description = "The ARN of the Bedrock AgentCore Runtime. Use this to construct the invocation URL."
  value       = aws_bedrockagentcore_agent_runtime.financial_agent_runtime.agent_runtime_arn
}

output "agent_runtime_id" {
  description = "The AgentCore runtime identifier extracted from the runtime ARN."
  value       = element(split("/", aws_bedrockagentcore_agent_runtime.financial_agent_runtime.agent_runtime_arn), 1)
}

output "s3_bucket_name" {
  description = "The name of the S3 bucket where financial docs are stored."
  value       = aws_s3_bucket.financial_docs.id
}
