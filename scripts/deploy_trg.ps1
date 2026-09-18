yc serverless trigger create timer `
  --name email-poller-trigger `
  --cron-expression "0/1 * * * ? *" `
  --invoke-function-name email-poller `
  --invoke-function-tag '$latest' `
  --invoke-function-service-account-id aje1suvv5as4qndn7ktk