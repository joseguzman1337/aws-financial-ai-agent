resource "aws_kms_key" "app_secrets" {
  description             = "KMS key used to encrypt sensitive application secrets"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "app_secrets_alias" {
  name          = "alias/financial-ai-agent-secrets"
  target_key_id = aws_kms_key.app_secrets.key_id
}

resource "aws_ssm_parameter" "langfuse_public_key" {
  name        = "/financial-ai/langfuse/public-key"
  description = "Langfuse Public Key"
  type        = "SecureString"
  value       = var.langfuse_public_key
  key_id      = aws_kms_key.app_secrets.arn
}

resource "aws_ssm_parameter" "langfuse_secret_key" {
  name        = "/financial-ai/langfuse/secret-key"
  description = "Langfuse Secret Key"
  type        = "SecureString"
  value       = var.langfuse_secret_key
  key_id      = aws_kms_key.app_secrets.arn
}

variable "langfuse_public_key" {
  description = "Public key for Langfuse"
  type        = string
  sensitive   = true
}

variable "langfuse_secret_key" {
  description = "Secret key for Langfuse"
  type        = string
  sensitive   = true
}
