resource "aws_s3_bucket" "workflows" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_versioning" "workflows" {
  bucket = aws_s3_bucket.workflows.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Trigger Lambda when manifest.json is written.
resource "aws_s3_bucket_notification" "manifest_trigger" {
  bucket = aws_s3_bucket.workflows.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.router.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = "manifest.json"
  }

  # S3 will reject the notification if Lambda doesn't have permission yet.
  depends_on = [aws_lambda_permission.allow_s3]
}
