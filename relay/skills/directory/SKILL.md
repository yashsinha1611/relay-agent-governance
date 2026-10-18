# Directory skill
Supported operations: user lookup and group membership planning.
Tools: directory.lookup_user, directory.plan_add_member.
Schemas: Action(operation=add_member, target group, user).
Missing users raise DirectoryNotFound and fail the task; never invent success.
Example: add alice to reviewers.