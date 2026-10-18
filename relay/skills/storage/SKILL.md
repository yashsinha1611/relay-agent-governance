# Storage skill
Supported operations: upload, download, delete (planned, then policy-approved).
Tools: storage.list_objects, storage.read_object, storage.plan_upload, storage.plan_delete, storage.plan_download.
Schemas: Action(operation, target bucket, path key, content, environment).
Validation: bucket grammar <project>-<dev|test|staging|prod>-<raw|curated|archive>; InvalidName/NotFound are typed errors.
Approvals: prod needs data_owner; delete needs two distinct approvers; self-approval escalates.
Failures: missing objects fail; blocked runs leave world.db unchanged.
Example: upload report.csv to acme-dev-raw content hello.