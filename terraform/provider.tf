terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.43.0" # latest used
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.8.1"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2.4"
    }
  }
}

provider "aws" {
  region  = "us-east-1"
  profile = "t1cx"
}
