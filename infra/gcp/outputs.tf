output "dashboard_uri" { value = google_cloud_run_v2_service.dashboard.uri }
output "state_bucket" { value = google_storage_bucket.state.name }
output "scanner_job" { value = google_cloud_run_v2_job.scanner.name }
output "scheduler_job" { value = google_cloud_scheduler_job.scan.name }
output "budget_warning" { value = "Budget notifications are delayed alerts, not spending caps. Scheduler starts paused; no model API is configured." }
