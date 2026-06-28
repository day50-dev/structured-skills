# prompt: test auto-commit agent

input $REPO_URL as repo
input $COMMIT_MESSAGE as string

import github from mcp_servers.json

def get_changed_files $repo:
    $files = %github.list_files_in_repository repo=$repo
    return $files
end

def create_commit $repo $message:
    $result = %github.create_commit repo=$repo message=$message
    return $result
end

$files = %get_changed_files $REPO_URL

if $files == "":
    $prompt = "No files found to commit in $REPO_URL."
else:
    $file_list = %join $files "\n"
    $status = %create_commit $REPO_URL $COMMIT_MESSAGE
    $prompt = "Successfully committed changes to $REPO_URL with message: '$COMMIT_MESSAGE'. Files affected: $file_list. Result: $status"
end